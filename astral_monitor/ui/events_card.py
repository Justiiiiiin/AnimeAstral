"""Karte „Ereignisse (Debug)“ (Einstellungen → Programm): Start, Raid-Enden, Alarme, Rejoins, Anti-AFK – zum Testen
und für die Fehlersuche. Die Einträge sammelt das Hauptfenster von Programmstart an (MainWindow.event_log), damit beim
ersten Öffnen der Einstellungen nichts fehlt."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from ..i18n import tr
from . import theme
from .widgets import Card, smooth

LEVEL_TOKENS = {"ok": "accent", "warn": "warn", "error": "danger", "info": "info"}
KEEP = 200


class EventsCard(Card):
    def __init__(self, history) -> None:
        super().__init__(tr("Ereignisse (Debug)"),
                         tr("Was das Programm zuletzt gemacht hat: Start/Stopp, Raid-Enden, Alarme, Rejoins, Anti-AFK. "
                            "Zum Testen und für Fehlermeldungen – das ausführliche Protokoll steckt im "
                            "Diagnose-Paket."))
        self.list = QListWidget()
        self.list.setWordWrap(False)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setUniformItemSizes(True)
        smooth(self.list)
        theme.track_fixed_height(self.list, 180)
        self.body.addWidget(self.list)
        for data in history:
            self.add(data)

    def add(self, data: dict) -> None:
        ts = data.get("ts", time.time())
        item = QListWidgetItem(f"{time.strftime('%H:%M:%S', time.localtime(ts))}  {data.get('text', '')}")
        item.setToolTip(data.get("text", ""))
        item.setData(Qt.ItemDataRole.UserRole, data.get("level", "info"))
        item.setForeground(QColor(theme.color(LEVEL_TOKENS.get(data.get("level", "info"), "info"))))
        self.list.insertItem(0, item)
        while self.list.count() > KEEP:
            self.list.takeItem(self.list.count() - 1)

    def recolor(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            token = LEVEL_TOKENS.get(item.data(Qt.ItemDataRole.UserRole) or "info", "info")
            item.setForeground(QColor(theme.color(token)))
