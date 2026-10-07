"""Karte „Makro-Warteschlange“ (Startseite, links unten): Aufgaben nacheinander ausführen, auf Wunsch in Schleife –
z. B. „Pets rollen W4 → Warten 10 Min. → Pets rollen W5“. Ausgeführt vom Makro der Karte darüber (automation.py);
Meldungen erscheinen dort. Liste und Schleife werden sofort gespeichert (settings.macro_queue, macro_loop)."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox, \
    QPushButton, QSpinBox

from ..automation import task_label
from ..i18n import N_, tr
from ..uimap import natural
from . import theme
from .widgets import Card, smooth

KINDS = [("navigate", N_("Öffnen")), ("pets", N_("Pets rollen (Auto!)")), ("close", N_("Menü schließen")),
         ("wait", N_("Warten (Min.)"))]


class MacroQueueCard(Card):
    def __init__(self, main, macro_card) -> None:
        super().__init__(tr("Makro-Warteschlange"),
                         tr("Aufgaben nacheinander ausführen – mit „Schleife“ immer wieder von vorn, bis „Stopp“, Esc "
                            "oder Mausbewegung beim Klicken. Während „Warten“ ist Roblox frei (Anti-AFK läuft weiter). "
                            "Doppelklick entfernt eine Aufgabe."))
        self.main = main
        self.macro = macro_card
        s = main.engine.settings

        add_row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.kind.setMinimumContentsLength(8)             # schmal halten: Startseite sonst zu breit
        for key, text in KINDS:
            self.kind.addItem(tr(text), key)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.param = QComboBox()
        self.param.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.param.setMinimumContentsLength(6)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setValue(10)
        self.minutes.setSuffix(tr(" Min"))
        add = QPushButton(tr("Hinzufügen"))
        add.clicked.connect(self._add)
        add_row.addWidget(self.kind)
        add_row.addWidget(self.param, 1)
        add_row.addWidget(self.minutes)
        add_row.addWidget(add)
        self.body.addLayout(add_row)

        self.list = QListWidget()
        smooth(self.list)
        theme.track_fixed_height(self.list, 104)          # feste Höhe: sonst wächst die Startseite über den Rand
        self.list.itemDoubleClicked.connect(lambda _i: self._remove())
        self.body.addWidget(self.list)

        row = QHBoxLayout()
        self.loop = QCheckBox(tr("Schleife"))
        self.loop.setChecked(bool(s.macro_loop))
        self.loop.toggled.connect(self._save)
        up = QPushButton("↑")
        up.setToolTip(tr("Nach oben"))
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton("↓")
        down.setToolTip(tr("Nach unten"))
        down.clicked.connect(lambda: self._move(1))
        remove = QPushButton(tr("Entfernen"))
        remove.clicked.connect(self._remove)
        self.run = QPushButton(tr("Warteschlange starten"))
        self.run.setObjectName("primary")
        self.run.clicked.connect(self._start)
        stop = QPushButton(tr("Stopp"))
        stop.clicked.connect(lambda: self.macro.navigator and self.macro.navigator.stop())
        for w in (self.loop, up, down, remove):
            row.addWidget(w)
        row.addStretch(1)
        self.body.addLayout(row)
        run_row = QHBoxLayout()                           # eigene Zeile: sonst wird die Startseite zu breit
        run_row.addStretch(1)
        run_row.addWidget(self.run)
        run_row.addWidget(stop)
        self.body.addLayout(run_row)
        self._controls = [self.kind, self.param, self.minutes, add, up, down, remove, self.run, self.loop]

        for task in s.macro_queue or []:
            self._append(task)
        self._kind_changed()
        self.macro.enabled.toggled.connect(lambda _on: self._update())
        self._update()

    # ------------------------------------------------------------------ Liste
    def _kind_changed(self, _i: int = 0) -> None:
        kind = self.kind.currentData()
        self.param.clear()
        if kind == "navigate":
            for w in self.macro.map.targets():
                if w["name"] != "Teleporter Fenster":
                    self.param.addItem(w["name"], w["name"])
        elif kind == "pets":
            worlds = sorted({m.group(1) for w in self.macro.map.entries
                             if (m := re.match(r"(W\d+) Pets-Roll$", w.get("name", "")))}, key=natural)
            for w in worlds:
                self.param.addItem(w, w)
        self.param.setVisible(kind in ("navigate", "pets"))
        self.minutes.setVisible(kind == "wait")

    def _add(self) -> None:
        kind = self.kind.currentData()
        task: dict = {"kind": kind}
        if kind == "navigate":
            task["target"] = self.param.currentData()
        elif kind == "pets":
            task["world"], task["close"] = self.param.currentData(), True
        elif kind == "wait":
            task["seconds"] = self.minutes.value() * 60
        if kind in ("navigate", "pets") and not self.param.currentData():
            return
        self._append(task)
        self.list.setCurrentRow(self.list.count() - 1)
        self._save()

    def _append(self, task: dict) -> None:
        item = QListWidgetItem(task_label(task))
        item.setData(Qt.ItemDataRole.UserRole, dict(task))
        self.list.addItem(item)

    def _tasks(self) -> list[dict]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self._save()

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(new, item)
        self.list.setCurrentRow(new)
        self._save()

    def _save(self, *_args) -> None:
        s = self.main.engine.settings
        s.macro_queue, s.macro_loop = self._tasks(), self.loop.isChecked()
        try:
            s.save()                                      # sofort, ohne Speichern-Leiste
        except OSError as exc:
            QMessageBox.critical(self, tr("Speichern"), tr("Konnte nicht speichern: {error}", error=exc))

    # ------------------------------------------------------------------ Ausführen
    def _update(self) -> None:
        on = self.macro.enabled.isChecked() and bool(self.macro.map.entries)
        for w in self._controls:
            w.setEnabled(on)

    def _start(self) -> None:
        if not self.macro.enabled.isChecked():
            return
        tasks = self._tasks()
        if not tasks:
            self.macro._add_log(tr("Die Warteschlange ist leer."))
            return
        nav = self.macro._ensure_navigator()
        if nav.busy:
            self.macro._add_log(tr("Läuft schon – erst „Stopp“."))
            return
        nav.run_queue(tasks, self.loop.isChecked())
