"""Karte „Makro-Warteschlange“ (Startseite, links unten): Aufgaben nacheinander ausführen, auf Wunsch in Schleife –
z. B. „Pets rollen W4 → Warten 10 Min. → Pets rollen W5“. Ausgeführt vom Makro der Karte darüber (automation.py);
Meldungen erscheinen dort. Liste und Schleife werden sofort gespeichert (settings.macro_queue, macro_loop)."""
from __future__ import annotations

import re

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox, \
    QPushButton, QSpinBox

from ..automation import task_label
from ..i18n import N_, tr
from ..uimap import natural
from . import theme
from .widgets import Card, smooth

KINDS = [("autoroll", N_("Auto Roll")), ("raid_farm", N_("Raid farmen")), ("raid_leave", N_("Raid verlassen")),
         ("raid_create", N_("Raid starten")), ("raid_join", N_("Raid beitreten")), ("wait", N_("Warten (Min.)"))]                  # reines Öffnen bringt in der Schlange nichts (Eigentümer)


class _TaskList(QListWidget):
    """Liste, die den freien Platz der Spalte füllt, aber selbst keinen fordert (Startseite ohne Scrollen)."""

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), self.minimumHeight())


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
        self.kind.setMinimumContentsLength(6)             # schmal halten: Startseite sonst zu breit
        for key, text in KINDS:
            self.kind.addItem(tr(text), key)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.param = QComboBox()
        self.param.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.param.setMinimumContentsLength(5)
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
        farm = QHBoxLayout()                              # nur bei „Raid farmen“: Anzahl, Auto Leave, beitreten
        self.runs = QSpinBox()
        self.runs.setRange(1, 9999)
        self.runs.setValue(100)
        self.runs.setPrefix("× ")
        self.runs.setToolTip(tr("So viele Raids farmen (zählt die Überwachung), dann Auto Retry aus und verlassen"))
        self.leave_wave = QSpinBox()
        self.leave_wave.setRange(0, 2000)
        self.leave_wave.setSpecialValueText(tr("Auto Leave aus"))
        self.leave_wave.setPrefix(tr("Leave ab Welle "))
        self.leave_wave.setToolTip(tr("Auto Leave ab dieser Welle (0 = aus) – spart die Wartezeit, wenn man nicht "
                                      "weiter kommt"))
        self.join = QCheckBox(tr("beitreten"))
        self.join.setToolTip(tr("„Join“ statt „Create/Start“ (eigener Raid kostet einen Schlüssel)"))
        farm.addWidget(self.runs)
        farm.addWidget(self.leave_wave, 1)
        farm.addWidget(self.join)
        self.body.addLayout(farm)
        self._farm = [self.runs, self.leave_wave, self.join]

        self.list = _TaskList()
        smooth(self.list)
        theme.track_min_height(self.list, 84)             # wächst in den freien Platz der Spalte
        self.list.itemDoubleClicked.connect(lambda _i: self._remove())
        self.body.addWidget(self.list, 1)

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
        remove = QPushButton("✕")
        remove.setToolTip(tr("Entfernen"))
        remove.clicked.connect(self._remove)
        self.run = QPushButton(tr("Starten"))
        self.run.setObjectName("primary")
        self.run.clicked.connect(self._start)
        stop = QPushButton(tr("Stopp"))
        stop.clicked.connect(lambda: self.macro.navigator and self.macro.navigator.stop())
        for w in (self.loop, up, down, remove):
            row.addWidget(w)
        row.addStretch(1)                                 # eine Zeile (Seite passt ohne Scrollen)
        row.addWidget(self.run)
        row.addWidget(stop)
        self.body.addLayout(row)
        self._controls = [self.kind, self.param, self.minutes, add, up, down, remove, self.run, self.loop,
                          *self._farm]

        for task in s.macro_queue or []:
            self._append(task)
        self._kind_changed()                              # Felder passend zur ersten Aufgabe ein-/ausblenden

    def reload(self) -> None:
        """Nach dem Erkunden: neue Ziele in die Auswahl."""
        self._kind_changed()
        self._kind_changed()
        self.macro.enabled.toggled.connect(lambda _on: self._update())
        self._update()

    # ------------------------------------------------------------------ Liste
    def _kind_changed(self, _i: int = 0) -> None:
        kind = self.kind.currentData()
        self.param.clear()
        for w in getattr(self, "_farm", []):
            w.setVisible(kind == "raid_farm")
        if kind not in ("wait", "raid_leave"):
            names = [w["name"] for w in self.macro.map.targets() if w["name"] != "Teleporter Fenster"]
            if kind in ("raid_farm", "raid_create", "raid_join"):    # Raids/Defense zuerst
                names.sort(key=lambda n: (not re.search(r"raid|defense|castle|gate", n, re.I), natural(n)))
            for name in names:
                self.param.addItem(name, name)
        self.param.setVisible(kind not in ("wait", "raid_leave"))
        self.minutes.setVisible(kind == "wait")

    def _add(self) -> None:
        kind = self.kind.currentData()
        task: dict = {"kind": kind}
        if kind == "wait":
            task["seconds"] = self.minutes.value() * 60
        elif kind == "raid_leave":
            pass
        else:
            if not self.param.currentData():
                return
            task["target"] = self.param.currentData()
            if kind == "raid_farm":
                task.update(runs=self.runs.value(), leave_wave=self.leave_wave.value(), join=self.join.isChecked())
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
