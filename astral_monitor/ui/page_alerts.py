"""Seite „Meldungen": Webhook, Ereignisse, Ping."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QGridLayout, QHBoxLayout, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QToolButton, QVBoxLayout, QWidget)

from ..i18n import tr
from . import theme
from ..settings import EVENT_DEFS, is_hex_color, is_valid_webhook
from .widgets import Card, InfoButton, SpinBox, form_grid, label


class ColorButton(QToolButton):
    """Farbfeld für die Embed-Farbe eines Ereignisses; leer = Standardfarbe des Programms."""

    def __init__(self) -> None:
        super().__init__()
        self.value = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.addAction(tr("Farbe wählen …"), self._pick)
        menu.addAction(tr("Standardfarbe"), lambda: self.set_value(""))
        self.setMenu(menu)
        self.setFixedSize(theme.px(34), theme.px(22))
        self.set_value("")

    def _pick(self) -> None:
        color = QColorDialog.getColor(QColor(self.value or theme.color("accent")), self, tr("Embed-Farbe"))
        if color.isValid():
            self.set_value(color.name().upper())

    def set_value(self, value: str) -> None:
        self.value = value if is_hex_color(value) else ""
        if self.value:
            self.setText("")
            self.setStyleSheet(f"QToolButton {{ background: {self.value}; border-radius: 6px; }}"
                               "QToolButton::menu-indicator { image: none; width: 0; }")
            self.setToolTip(tr("Eigene Farbe {color}", color=self.value))
        else:
            self.setText(tr("Auto"))
            self.setStyleSheet("QToolButton { font-size: 8pt; padding: 0; }"
                               "QToolButton::menu-indicator { image: none; width: 0; }")
            self.setToolTip(tr("Standardfarbe des Programms"))


class AlertsPage(QWidget):
    SAVES = True                                   # Speichern-Leiste unten (main_window)

    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.engine = main.engine

        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 16)
        root.addWidget(label(tr("Meldungen"), "h1"))
        root.addWidget(label(tr("Was wird an Discord gesendet, und wann gibt es einen Ping?"), "muted"))

        hook = Card(tr("Discord"))
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)
        self.url = QLineEdit()
        self.url.setEchoMode(QLineEdit.EchoMode.Password)
        self.url.setPlaceholderText(tr("https://discord.com/api/webhooks/…"))
        show = QCheckBox(tr("anzeigen"))
        show.toggled.connect(lambda on: [f.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
                                         for f in (self.url, self.forum)])
        self.name = QLineEdit()
        self.ping = QLineEdit()
        self.ping.setPlaceholderText(tr("Deine Discord-ID (nur Ziffern)"))
        grid.addWidget(label(tr("Webhook-URL")), 0, 0)
        grid.addWidget(self.url, 0, 1)
        grid.addWidget(show, 0, 2)
        grid.addWidget(label(tr("Anzeigename")), 1, 0)
        grid.addWidget(self.name, 1, 1, 1, 2)
        grid.addWidget(label(tr("Ping-Ziel")), 2, 0)
        grid.addWidget(self.ping, 2, 1, 1, 2)
        self.forum = QLineEdit()
        self.forum.setEchoMode(QLineEdit.EchoMode.Password)
        self.forum.setPlaceholderText(tr("optional – Webhook eines Forum-Kanals"))
        forum_label = QHBoxLayout()
        forum_label.addWidget(label(tr("Tages-Beiträge")))
        forum_label.addWidget(InfoButton(tr(
            "Raid-, Quest-, Rekord- und Wand-Meldungen landen in einem Forum-Kanal – jeden Tag in einem eigenen "
            "Beitrag „Raids · Datum“. Der Hauptkanal bleibt für Live-Status und Alarme frei.\n\nSo geht's: "
            "Forum-Kanal anlegen → Kanal bearbeiten → Integrationen → Webhooks → neuen Webhook, URL hier "
            "einfügen. Leer lassen = alles in den Hauptkanal.")))
        forum_label.addStretch(1)
        grid.addLayout(forum_label, 3, 0)
        grid.addWidget(self.forum, 3, 1, 1, 2)
        hook.body.addLayout(grid)
        row = QHBoxLayout()
        test = QPushButton(tr("Test-Nachricht senden"))
        test.clicked.connect(self._send_test)
        row.addWidget(test)
        row.addStretch(1)
        hook.body.addLayout(row)
        root.addWidget(hook)

        live = Card(tr("Live-Status"),
                    tr("Eine Nachricht im Kanal, die sich laufend aktualisiert, statt vieler Uptime-Meldungen."
                       "\n\nTipp: Rechtsklick auf die Statusnachricht → „Anheften“. Sie wird danach nur noch "
                       "bearbeitet. „Neu senden“ erzeugt eine neue Nachricht, die du neu anheftest."))
        self.status_enabled = QCheckBox(tr("Eine Statusnachricht verwenden, die sich selbst aktualisiert"))
        self.status_enabled.toggled.connect(self._sync_uptime)
        live.body.addWidget(self.status_enabled)
        lg = form_grid()
        self.status_interval = SpinBox()
        self.status_interval.setRange(20, 3600)
        self.status_interval.setSuffix(" s")
        self.uptime = SpinBox()
        self.uptime.setRange(1, 1440)
        self.uptime.setSuffix(tr(" Min"))
        lg.addWidget(label(tr("Aktualisieren alle")), 0, 0)
        lg.addWidget(self.status_interval, 0, 1)
        self.uptime_label = label(tr("Sonst Uptime-Meldung alle"))
        lg.addWidget(self.uptime_label, 1, 0)
        lg.addWidget(self.uptime, 1, 1)
        live.body.addLayout(lg)
        self.status_bottom = QCheckBox(tr("Nach jeder Meldung automatisch wieder ganz nach unten schieben"))
        live.body.addWidget(self.status_bottom)
        brow = QHBoxLayout()
        resend = QPushButton(tr("Jetzt unten neu senden"))
        resend.clicked.connect(self.main.resend_status)
        brow.addWidget(resend)
        brow.addStretch(1)
        live.body.addLayout(brow)
        root.addWidget(live)

        events = Card(tr("Ereignisse"))
        table = QGridLayout()
        table.setColumnStretch(0, 1)
        theme.track_spacing(table, 6)
        center = Qt.AlignmentFlag.AlignCenter
        table.addWidget(label(tr("Ereignis"), "small"), 0, 0)
        table.addWidget(label(tr("Senden"), "small"), 0, 1, center)
        table.addWidget(label(tr("Ping"), "small"), 0, 2, center)
        table.addWidget(label(tr("Farbe"), "small"), 0, 3, center)
        table.setColumnMinimumWidth(1, 64)
        table.setColumnMinimumWidth(2, 64)
        table.setColumnMinimumWidth(3, 64)
        self.send_boxes: dict[str, QCheckBox] = {}
        self.ping_boxes: dict[str, QCheckBox] = {}
        self.color_buttons: dict[str, ColorButton] = {}
        for i, (key, text, _s, _p) in enumerate(EVENT_DEFS, start=1):
            table.addWidget(label(tr(text)), i, 0)
            send, ping = QCheckBox(), QCheckBox()
            send.toggled.connect(ping.setEnabled)             # Ping nur bei gesendeten Ereignissen
            self.send_boxes[key], self.ping_boxes[key] = send, ping
            table.addWidget(send, i, 1, center)
            table.addWidget(ping, i, 2, center)
            self.color_buttons[key] = ColorButton()
            table.addWidget(self.color_buttons[key], i, 3, center)
        events.body.addLayout(table)
        self.attach = QCheckBox(tr("Quest-Fortschritt an Raid- und Uptime-Meldungen anhängen"))
        events.body.addWidget(self.attach)
        self.report_on_stop = QCheckBox(tr("Beim Stoppen eine Statistik-Karte senden"))
        events.body.addWidget(self.report_on_stop)
        root.addWidget(events)
        root.addStretch(1)

    def _sync_uptime(self, live_on: bool) -> None:
        self.uptime.setEnabled(not live_on)
        self.uptime_label.setEnabled(not live_on)

    def load(self, s) -> None:
        self.url.setText(s.webhook_url)
        self.name.setText(s.username)
        self.ping.setText(s.ping_user_id)
        self.forum.setText(s.forum_webhook_url)
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
            raise ValueError(tr("Die Discord-ID darf nur aus Ziffern bestehen."))
        s.ping_user_id = ping
        forum = self.forum.text().strip()
        if forum and not is_valid_webhook(forum):
            raise ValueError(tr("Der Forum-Webhook ist keine gültige Discord-Webhook-URL (Seite „Meldungen“)."))
        s.forum_webhook_url = forum
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
            QMessageBox.warning(self, tr("Webhook"), tr("Bitte zuerst eine gültige Webhook-URL eintragen."))
            return
        self.main.test_webhook(url, lambda ok, info: QMessageBox.information(self, tr("Discord"), tr("Test-Nachricht gesendet ✅"))
                               if ok else QMessageBox.critical(self, tr("Discord"), tr("Senden fehlgeschlagen:\n{error}", error=info)))
