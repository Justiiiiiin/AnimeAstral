"""Page “Alerts”: webhook, events, ping."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QGridLayout, QHBoxLayout, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget)

from ..i18n import tr
from . import theme
from ..settings import EVENT_DEFS, is_hex_color, is_valid_webhook
from .widgets import Card, InfoButton, SpinBox, form_grid, label, page_header


class ColorButton(QToolButton):
    """Color field for the embed color of an event; empty = the program's default color."""

    def __init__(self) -> None:
        super().__init__()
        self.value = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.addAction(tr("Choose color …"), self._pick)
        menu.addAction(tr("Default color"), lambda: self.set_value(""))
        self.setMenu(menu)
        self.setFixedSize(theme.px(44), theme.px(22))
        self.set_value("")

    def _pick(self) -> None:
        color = QColorDialog.getColor(QColor(self.value or theme.color("accent")), self, tr("Embed color"))
        if color.isValid():
            self.set_value(color.name().upper())

    def set_value(self, value: str) -> None:
        self.value = value if is_hex_color(value) else ""
        h = theme.px(22)
        flat = (f"min-height: {h}px; max-height: {h}px; padding: 0; border-radius: {h // 2}px;")   # flat like a chip
        if self.value:
            self.setText("")
            self.setStyleSheet(f"QToolButton {{ background: {self.value}; {flat} }}"
                               "QToolButton::menu-indicator { image: none; width: 0; }")
            self.setToolTip(tr("Custom color {color}", color=self.value))
        else:
            self.setText(tr("Auto"))
            self.setStyleSheet(f"QToolButton {{ font-size: 8pt; {flat} }}"
                               "QToolButton::menu-indicator { image: none; width: 0; }")
            self.setToolTip(tr("The program's default color"))


class AlertsPage(QWidget):
    SAVES = True                                   # save bar at the bottom (main_window)

    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.engine = main.engine

        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 14)
        head = page_header(tr("Alerts"), tr("What is sent to Discord, and when is there a ping?"))
        head.addStretch(1)
        root.addLayout(head)
        cols = QHBoxLayout()                               # left Discord + live status, right events
        theme.track_spacing(cols, 14)
        left = QVBoxLayout()
        theme.track_spacing(left, 14)
        cols.addLayout(left, 1)

        hook = Card(tr("Discord"))
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)
        self.url = QLineEdit()
        self.url.setEchoMode(QLineEdit.EchoMode.Password)
        self.url.setPlaceholderText(tr("https://discord.com/api/webhooks/…"))
        show = QCheckBox(tr("show"))
        show.toggled.connect(lambda on: [f.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
                                         for f in (self.url, self.forum)])
        self.name = QLineEdit()
        self.ping = QLineEdit()
        self.ping.setPlaceholderText(tr("Your Discord ID (digits only)"))
        grid.addWidget(label(tr("Webhook URL")), 0, 0)
        grid.addWidget(self.url, 0, 1)
        grid.addWidget(show, 0, 2)
        grid.addWidget(label(tr("Display name")), 1, 0)
        grid.addWidget(self.name, 1, 1, 1, 2)
        grid.addWidget(label(tr("Ping target")), 2, 0)
        grid.addWidget(self.ping, 2, 1, 1, 2)
        self.forum = QLineEdit()
        self.forum.setEchoMode(QLineEdit.EchoMode.Password)
        self.forum.setPlaceholderText(tr("optional – webhook of a forum channel"))
        forum_label = QHBoxLayout()
        forum_label.addWidget(label(tr("Daily posts")))
        forum_label.addWidget(InfoButton(tr(
            "Raid, quest, record and wall messages go to a forum channel – each day in its own post “Raids · date”. "
            "The main channel stays free for the live status and alerts.\n\nHow to: create a forum channel → edit "
            "channel → Integrations → Webhooks → new webhook, paste the URL here. Leave empty = everything goes to "
            "the main channel.")))
        forum_label.addStretch(1)
        grid.addLayout(forum_label, 3, 0)
        grid.addWidget(self.forum, 3, 1, 1, 2)
        style_row = QHBoxLayout()
        theme.track_spacing(style_row, 6)
        self.style_group = QButtonGroup(self)
        self.style_group.setExclusive(True)
        for key, text in (("detailed", tr("Detailed")), ("compact", tr("Compact"))):
            btn = QPushButton(text)
            btn.setObjectName("chipbtn")
            btn.setCheckable(True)
            btn.setProperty("style_key", key)
            self.style_group.addButton(btn)
            style_row.addWidget(btn)
        style_row.addWidget(InfoButton(tr(
            "Detailed: figures as separate fields.\n\nCompact: one calm line with the key values – the live status "
            "gets slimmer too.")))
        style_row.addStretch(1)
        test = QPushButton(tr("Send test message"))     # in the same row (page fits without scrolling)
        test.clicked.connect(self._send_test)
        style_row.addWidget(test)
        grid.addWidget(label(tr("Message style")), 4, 0)
        grid.addLayout(style_row, 4, 1, 1, 2)
        hook.body.addLayout(grid)
        left.addWidget(hook)

        live = Card(tr("Live status"),
                    tr("One message in the channel that keeps updating, instead of many uptime messages.\n\nTip: "
                       "right-click the status message → “Pin”. From then on it is only edited. “Resend” creates a "
                       "new message that you pin again."))
        self.status_enabled = QCheckBox(tr("Use one status message that updates itself"))
        self.status_enabled.toggled.connect(self._sync_uptime)
        live.body.addWidget(self.status_enabled)
        lg = form_grid()
        self.status_interval = SpinBox()
        self.status_interval.setRange(20, 3600)
        self.status_interval.setSuffix(" s")
        self.uptime = SpinBox()
        self.uptime.setRange(1, 1440)
        self.uptime.setSuffix(tr(" min"))
        lg.addWidget(label(tr("Update every")), 0, 0)
        lg.addWidget(self.status_interval, 0, 1)
        self.uptime_label = label(tr("Otherwise uptime message every"))
        lg.addWidget(self.uptime_label, 1, 0)
        lg.addWidget(self.uptime, 1, 1)
        live.body.addLayout(lg)
        self.status_bottom = QCheckBox(tr("Automatically move it back to the bottom after every message"))
        live.body.addWidget(self.status_bottom)
        brow = QHBoxLayout()
        resend = QPushButton(tr("Resend at the bottom now"))
        resend.clicked.connect(self.main.resend_status)
        brow.addWidget(resend)
        brow.addStretch(1)
        live.body.addLayout(brow)
        left.addWidget(live)
        left.addStretch(1)

        events = Card(tr("Events"))
        table = QGridLayout()
        table.setColumnStretch(0, 1)
        theme.track_spacing(table, 6)
        center = Qt.AlignmentFlag.AlignCenter
        table.addWidget(label(tr("Event"), "small"), 0, 0)
        table.addWidget(label(tr("Send"), "small"), 0, 1, center)
        table.addWidget(label(tr("Ping"), "small"), 0, 2, center)
        table.addWidget(label(tr("Color"), "small"), 0, 3, center)
        for col in (1, 2, 3):
            theme.track(table, lambda o, f, c=col: o.setColumnMinimumWidth(c, round(56 * f)))
        self.send_boxes: dict[str, QCheckBox] = {}
        self.ping_boxes: dict[str, QCheckBox] = {}
        self.color_buttons: dict[str, ColorButton] = {}
        for i, (key, text, _s, _p) in enumerate(EVENT_DEFS, start=1):
            table.addWidget(label(tr(text)), i, 0)
            send, ping = QCheckBox(), QCheckBox()
            send.toggled.connect(ping.setEnabled)             # ping only for events that are sent
            self.send_boxes[key], self.ping_boxes[key] = send, ping
            table.addWidget(send, i, 1, center)
            table.addWidget(ping, i, 2, center)
            self.color_buttons[key] = ColorButton()
            table.addWidget(self.color_buttons[key], i, 3, center)
        events.body.addLayout(table)
        self.attach = QCheckBox(tr("Attach quest progress to raid and uptime messages"))
        events.body.addWidget(self.attach)
        self.report_on_stop = QCheckBox(tr("Send a stats card when stopping"))
        events.body.addWidget(self.report_on_stop)
        events.body.addStretch(1)
        cols.addWidget(events, 1)
        root.addLayout(cols, 1)

    def _sync_uptime(self, live_on: bool) -> None:
        self.uptime.setEnabled(not live_on)
        self.uptime_label.setEnabled(not live_on)

    def load(self, s) -> None:
        self.url.setText(s.webhook_url)
        self.name.setText(s.username)
        self.ping.setText(s.ping_user_id)
        self.forum.setText(s.forum_webhook_url)
        for btn in self.style_group.buttons():
            btn.setChecked(btn.property("style_key") == s.message_style)
        for key in self.send_boxes:
            entry = s.events.get(key, {})
            self.send_boxes[key].setChecked(bool(entry.get("send")))
            self.ping_boxes[key].setChecked(bool(entry.get("ping")))
            self.ping_boxes[key].setEnabled(bool(entry.get("send")))
            self.color_buttons[key].set_value(entry.get("color", ""))
        self.attach.setChecked(s.attach_quests)
        self.status_enabled.setChecked(s.status_enabled)
        self._sync_uptime(s.status_enabled)
        self.status_interval.setValue(s.status_interval)
        self.uptime.setValue(s.uptime_minutes)
        self.status_bottom.setChecked(s.status_auto_bottom)
        self.report_on_stop.setChecked(s.report_on_stop)

    def apply(self, s) -> None:
        s.webhook_url = self.url.text().strip()
        s.username = self.name.text().strip() or "Anime Astral Monitor"
        ping = self.ping.text().strip()
        if ping and not ping.isdigit():
            raise ValueError(tr("The Discord ID may only contain digits."))
        s.ping_user_id = ping
        forum = self.forum.text().strip()
        if forum and not is_valid_webhook(forum):
            raise ValueError(tr("The forum webhook is not a valid Discord webhook URL (“Alerts” page)."))
        s.forum_webhook_url = forum
        checked = self.style_group.checkedButton()
        s.message_style = checked.property("style_key") if checked else "detailed"
        for key in self.send_boxes:
            s.events[key] = {"send": self.send_boxes[key].isChecked(),
                             "ping": self.ping_boxes[key].isChecked()}
            if self.color_buttons[key].value:
                s.events[key]["color"] = self.color_buttons[key].value
        s.attach_quests = self.attach.isChecked()
        s.status_enabled = self.status_enabled.isChecked()
        s.status_interval = self.status_interval.value()
        s.uptime_minutes = self.uptime.value()
        s.status_auto_bottom = self.status_bottom.isChecked()
        s.report_on_stop = self.report_on_stop.isChecked()

    def refresh(self) -> None:
        pass

    def _send_test(self) -> None:
        url = self.url.text().strip()
        if not is_valid_webhook(url):
            QMessageBox.warning(self, tr("Webhook"), tr("Please enter a valid webhook URL first."))
            return
        self.main.test_webhook(url, lambda ok, info: QMessageBox.information(self, tr("Discord"), tr("Test message sent ✅"))
                               if ok else QMessageBox.critical(self, tr("Discord"), tr("Sending failed:\n{error}", error=info)))
