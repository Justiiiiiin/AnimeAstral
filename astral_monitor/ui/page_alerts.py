"""Seite „Meldungen": Webhook, Ereignisse, Ping."""
from __future__ import annotations

import threading

from PySide6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from .. import messages
from ..i18n import tr
from . import theme
from ..discord_client import DiscordSender
from ..settings import EVENT_DEFS, is_valid_webhook
from .widgets import Card, SpinBox, label


class AlertsPage(QWidget):
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
        show.toggled.connect(lambda on: self.url.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
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
        hook.body.addLayout(grid)
        row = QHBoxLayout()
        test = QPushButton(tr("Test-Nachricht senden"))
        test.clicked.connect(self._send_test)
        row.addWidget(test)
        row.addStretch(1)
        hook.body.addLayout(row)
        root.addWidget(hook)

        live = Card(tr("Live-Status"))
        self.status_enabled = QCheckBox(tr("Eine Statusnachricht verwenden, die sich selbst aktualisiert (ersetzt die Uptime-Meldungen)"))
        live.body.addWidget(self.status_enabled)
        lrow = QHBoxLayout()
        lrow.addWidget(label(tr("Aktualisieren alle")))
        self.status_interval = SpinBox()
        self.status_interval.setRange(20, 3600)
        self.status_interval.setSuffix(" s")
        lrow.addWidget(self.status_interval)
        lrow.addStretch(1)
        live.body.addLayout(lrow)
        self.status_bottom = QCheckBox(tr("Nach jeder Meldung des Programms automatisch ganz nach unten schieben"))
        live.body.addWidget(self.status_bottom)
        brow = QHBoxLayout()
        resend = QPushButton(tr("Jetzt unten neu senden"))
        resend.clicked.connect(self.main.resend_status)
        brow.addWidget(resend)
        brow.addStretch(1)
        live.body.addLayout(brow)
        live.body.addWidget(label(tr("Tipp: Rechtsklick auf die Statusnachricht → „Anheften“. Eine angeheftete Nachricht bleibt "
                                  "angeheftet und wird nur bearbeitet. Per Webhook lässt sie sich nicht automatisch anheften; "
                                  "„Neu senden“ erzeugt eine neue Nachricht (neu anheften)."), "small", wrap=True))
        self.report_on_stop = QCheckBox(tr("Beim Stoppen eine Statistik-Karte senden"))
        live.body.addWidget(self.report_on_stop)
        root.addWidget(live)

        events = Card(tr("Ereignisse"))
        table = QGridLayout()
        table.setColumnStretch(0, 1)
        table.setVerticalSpacing(6)
        table.addWidget(label(tr("Ereignis"), "small"), 0, 0)
        table.addWidget(label(tr("Senden"), "small"), 0, 1)
        table.addWidget(label(tr("Ping"), "small"), 0, 2)
        self.send_boxes: dict[str, QCheckBox] = {}
        self.ping_boxes: dict[str, QCheckBox] = {}
        for i, (key, text, _s, _p) in enumerate(EVENT_DEFS, start=1):
            table.addWidget(label(tr(text)), i, 0)
            send, ping = QCheckBox(), QCheckBox()
            self.send_boxes[key], self.ping_boxes[key] = send, ping
            table.addWidget(send, i, 1)
            table.addWidget(ping, i, 2)
        events.body.addLayout(table)
        self.attach = QCheckBox(tr("Quest-Fortschritt in Raid- und Uptime-Meldungen anhängen"))
        events.body.addWidget(self.attach)
        root.addWidget(events)

        save = QPushButton(tr("Speichern"))
        save.setObjectName("primary")
        save.clicked.connect(lambda: self.main.save_settings())
        row2 = QHBoxLayout()
        row2.addStretch(1)
        row2.addWidget(save)
        root.addLayout(row2)
        root.addStretch(1)

    def load(self, s) -> None:
        self.url.setText(s.webhook_url)
        self.name.setText(s.username)
        self.ping.setText(s.ping_user_id)
        for key in self.send_boxes:
            entry = s.events.get(key, {})
            self.send_boxes[key].setChecked(bool(entry.get("send")))
            self.ping_boxes[key].setChecked(bool(entry.get("ping")))
        self.attach.setChecked(s.attach_quests)
        self.status_enabled.setChecked(s.status_enabled)
        self.status_interval.setValue(s.status_interval)
        self.status_bottom.setChecked(s.status_auto_bottom)
        self.report_on_stop.setChecked(s.report_on_stop)

    def apply(self, s) -> None:
        s.webhook_url = self.url.text().strip()
        s.username = self.name.text().strip() or "Anime Astral Monitor"
        ping = self.ping.text().strip()
        if ping and not ping.isdigit():
            raise ValueError(tr("Die Discord-ID darf nur aus Ziffern bestehen."))
        s.ping_user_id = ping
        for key in self.send_boxes:
            s.events[key] = {"send": self.send_boxes[key].isChecked(),
                             "ping": self.ping_boxes[key].isChecked()}
        s.attach_quests = self.attach.isChecked()
        s.status_enabled = self.status_enabled.isChecked()
        s.status_interval = self.status_interval.value()
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
