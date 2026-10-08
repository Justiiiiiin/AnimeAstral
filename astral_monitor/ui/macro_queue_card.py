"""Karte „Farm-Routine“ (Startseite, links; bis 0.9.9-beta.6 „Makro-Warteschlange“): Schritte nacheinander ausführen,
auf Wunsch in Runden – z. B. „Raid W20 Alvarez War · 50 Raids → Auto Roll W21 Cyberware → Warten 10 Min.“.
Ausgeführt vom Navigator des MacroController (automation.py); Meldungen im Makro-Protokoll. Liste und Runden werden
sofort gespeichert (settings.macro_queue, macro_loop).

Aufbau (Wunsch des Eigentümers 08.10.2026: übersichtlicher, gleiche Breite für jede Art): oben „Was?“ + „Wo?“, darunter
die Optionen der gewählten Art in einem Stapel fester Größe – die Karte ändert ihre Breite beim Umschalten nicht."""
from __future__ import annotations

import re

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem, \
    QMessageBox, QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QWidget

from ..automation import task_label
from ..i18n import N_, tr
from . import theme
from .widgets import Card, label, smooth

# Ein Raid-Schritt mit Ende-Bedingung (Eigentümer 08.10.2026): verlassen wird nur, wenn danach ein anderer Raid/Modus
# folgt (automation.leave_before). Fixer Gigs, Gilde und Progressions stehen unter „Automatisch abholen“.
KINDS = [("raid", N_("Raid / Defense farmen")), ("autoroll", N_("Auto Roll starten")),
         ("progression", N_("Progressions: Roll All")), ("wait", N_("Pause"))]
UNTIL = [("runs", N_("nach Anzahl Raids")), ("minutes", N_("nach Minuten")), ("never", N_("nie (bis Stopp)"))]
RAID_CATS = ("raid", "defense")
ROLL_CATS = ("gacha", "pets")


class _TaskList(QListWidget):
    """Liste, die den freien Platz der Spalte füllt, aber selbst keinen fordert (Startseite ohne Scrollen)."""

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), self.minimumHeight())


def _caption(text: str) -> QWidget:
    """Beschriftung links mit fester Breite – alle Zeilen (auch im Optionen-Stapel) beginnen gleich."""
    lbl = label(text, "small")
    theme.track_fixed_width(lbl, 112)
    return lbl


def _fixed(combo: QComboBox, chars: int) -> QComboBox:
    """Auswahlfeld mit fester Mindestbreite (lange Namen verbreitern die Seite nicht)."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return combo


class MacroQueueCard(Card):
    def __init__(self, main) -> None:
        super().__init__(tr("Farm-Routine"),
                         tr("Deine Schritte im Spiel, von oben nach unten – mit „Wiederholen“ immer wieder von vorn, "
                            "bis „Stopp“, Esc oder Mausbewegung.\n\nRaid / Defense farmen: startet (oder tritt bei), "
                            "stellt Auto Retry und Auto Leave ein und zählt die Raids über die Überwachung. Verlassen "
                            "wird nur, wenn danach ein anderer Raid kommt.\nAuto Roll: öffnet Gacha/Pets-Roll, "
                            "drückt Auto Roll und schließt – das Spiel rollt weiter.\nPause: Roblox ist frei, "
                            "Anti-AFK läuft.\n\nFixer Gigs und Gilden-Missionen holt das Makro zwischendurch "
                            "selbst ab (Karte „Automatisch abholen“). Doppelklick entfernt einen Schritt."))
        self.main = main
        self.macro = main.macro
        s = main.engine.settings

        self.off_hint = QWidget()                         # Makro aus: Hinweis statt grauer Knöpfe ohne Erklärung
        hint = QHBoxLayout(self.off_hint)
        hint.setContentsMargins(0, 0, 0, 0)
        hint.addWidget(label(tr("Das Makro ist aus."), "muted"), 1)
        to_settings = QPushButton(tr("Einschalten …"))
        to_settings.clicked.connect(lambda: self.main.open_settings_tab("Makro"))
        hint.addWidget(to_settings)
        self.body.addWidget(self.off_hint)

        grid = QGridLayout()
        theme.track_spacing(grid, 6)
        grid.setColumnStretch(1, 1)
        self.kind = _fixed(QComboBox(), 12)
        for key, text in KINDS:
            self.kind.addItem(tr(text), key)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.target = _fixed(QComboBox(), 12)
        grid.addWidget(_caption(tr("Was?")), 0, 0)
        grid.addWidget(self.kind, 0, 1)
        grid.addWidget(_caption(tr("Wo?")), 1, 0)
        grid.addWidget(self.target, 1, 1)

        # Optionen je Art: fester Stapel (Größe = größte Seite), damit die Karte nicht springt
        self.options = QStackedWidget()
        self.options.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        raid_page = QWidget()
        rp = QGridLayout(raid_page)
        rp.setContentsMargins(0, 0, 0, 0)
        theme.track_spacing(rp, 6)
        self.until = _fixed(QComboBox(), 8)
        for key, text in UNTIL:
            self.until.addItem(tr(text), key)
        self.until.setToolTip(tr("Wann der Schritt endet. Verlassen wird nur, wenn danach ein anderer Raid kommt – "
                                 "sonst farmt Auto Retry weiter."))
        self.until.currentIndexChanged.connect(lambda _i: self._until_changed())
        self.runs = QSpinBox()
        self.runs.setRange(1, 9999)
        self.runs.setValue(50)
        self.leave_wave = QSpinBox()
        self.leave_wave.setRange(0, 2000)
        self.leave_wave.setSpecialValueText(tr("aus"))
        self.leave_wave.setToolTip(tr("Auto Leave ab dieser Welle (aus = bis zum Ende) – spart Zeit, wenn man nicht "
                                      "weiter kommt"))
        self.join = QCheckBox(tr("beitreten statt starten"))
        self.join.setToolTip(tr("„Join“ statt „Create/Start“ (ein eigener Raid kostet einen Schlüssel)"))
        rp.addWidget(_caption(tr("Ende")), 0, 0)
        rp.addWidget(self.until, 0, 1)
        rp.addWidget(self.runs, 0, 2)
        rp.addWidget(_caption(tr("Auto Leave ab Welle")), 1, 0)
        rp.addWidget(self.leave_wave, 1, 1)
        rp.addWidget(self.join, 1, 2)
        rp.setColumnStretch(1, 1)
        self.options.addWidget(raid_page)
        self.options.addWidget(self._note(tr("Öffnet das Fenster, drückt „Auto Roll“ und schließt es wieder – das "
                                             "Spiel rollt im Hintergrund weiter.")))
        self.options.addWidget(self._note(tr("Drückt „Roll All“ in der ersten Progression – das gilt für die "
                                             "Progressions aller Welten.")))
        wait_page = QWidget()
        wp = QHBoxLayout(wait_page)
        wp.setContentsMargins(0, 0, 0, 0)
        wp.addWidget(_caption(tr("Dauer")))
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setValue(10)
        self.minutes.setSuffix(tr(" Min"))
        wp.addWidget(self.minutes)
        wp.addWidget(label(tr("Roblox ist so lange frei, Anti-AFK läuft."), "small"), 1)
        self.options.addWidget(wait_page)
        grid.addWidget(self.options, 2, 0, 1, 2)
        add = QPushButton(tr("＋ Schritt hinzufügen"))
        add.setObjectName("primary")
        add.clicked.connect(self._add)
        grid.addWidget(add, 3, 0, 1, 2)
        self.body.addLayout(grid)

        self.list = _TaskList()
        smooth(self.list)
        self.list.setObjectName("routine")
        self.list.setWordWrap(True)
        theme.track_min_height(self.list, 84)             # wächst in den freien Platz der Spalte
        self.list.itemDoubleClicked.connect(lambda _i: self._remove())
        self.body.addWidget(self.list, 1)

        row = QHBoxLayout()
        theme.track_spacing(row, 6)
        self.loop = QCheckBox(tr("Wiederholen"))
        self.loop.setToolTip(tr("Nach dem letzten Schritt wieder von vorn"))
        self.loop.setChecked(bool(s.macro_loop))
        self.loop.toggled.connect(self._save)
        up = QPushButton("↑")
        up.setToolTip(tr("Nach oben"))
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton("↓")
        down.setToolTip(tr("Nach unten"))
        down.clicked.connect(lambda: self._move(1))
        remove = QPushButton("✕")
        remove.setToolTip(tr("Schritt entfernen"))
        remove.clicked.connect(self._remove)
        for btn in (up, down, remove):
            btn.setObjectName("glyph")                    # nur ein Zeichen: ohne Innenabstand
            theme.track_fixed_width(btn, 38)
        self.run = QPushButton(tr("▶ Starten"))
        self.run.setObjectName("primary")
        self.run.clicked.connect(self._start)
        self.stop_btn = QPushButton(tr("■ Stopp"))
        self.stop_btn.clicked.connect(self.macro.stop)
        for w in (self.loop, up, down, remove):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.run)
        row.addWidget(self.stop_btn)
        self.body.addLayout(row)
        self.state = label("", "small", wrap=True)
        self.body.addWidget(self.state)
        self._controls = [self.kind, self.target, self.options, add, up, down, remove, self.run, self.loop]

        for task in s.macro_queue or []:
            self._append(task)
        self._kind_changed()
        self.macro.enabled_listeners.append(lambda _on: self._update())
        self.macro.map_listeners.append(self.reload)
        self._shown_pos = -2
        self.timer = QTimer(self)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._update()

    @staticmethod
    def _note(text: str) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_caption(""))
        lay.addWidget(label(text, "muted", wrap=True), 1)
        return w

    def reload(self) -> None:
        """Nach dem Erkunden: neue Ziele in die Auswahl."""
        self._kind_changed()

    # ------------------------------------------------------------------ Auswahl
    def _kind_changed(self, _i: int = 0) -> None:
        kind = self.kind.currentData()
        self.options.setCurrentIndex([k for k, _t in KINDS].index(kind))
        current = self.target.currentData()
        self.target.clear()
        if kind in ("raid", "autoroll"):
            for text, name in self._targets(kind):
                self.target.addItem(text, name)
            idx = self.target.findData(current)
            self.target.setCurrentIndex(max(0, idx))
        else:
            self.target.addItem(tr("– (gilt überall)") if kind == "progression" else "–", None)
        self.target.setEnabled(kind in ("raid", "autoroll") and self.macro.enabled)
        if kind == "raid":
            self._until_changed()

    def _targets(self, kind: str) -> list[tuple[str, str]]:
        """Ziele nach Welt: bei Raid nur Raids/Defense, bei Auto Roll nur Gachas/Pets-Roll (sonst alles)."""
        targets = self.macro.map.sorted_targets()
        want = RAID_CATS if kind == "raid" else ROLL_CATS
        picked = [t for t in targets if self._category(t[1]) in want]
        return picked or targets

    def _category(self, name: str) -> str:
        w = self.macro.map.container(name) or {}
        cat = (w.get("extra") or {}).get("category") or ""
        if cat:
            return cat
        low = name.lower()                                # mitgelieferte Karte: Art aus dem Namen
        if re.search(r"pets-roll", low):
            return "pets"
        if re.search(r"defense mode|defense$", low):
            return "defense"
        if re.search(r"raid|rush|war\b|tower|castle", low) and not re.search(r"battlepass|shop|upgrade|merchant",
                                                                              low):
            return "raid"
        if re.search(r"titans|grimoires|hakis|races|doujutsu|monarchs|family|zenkai|saya|attributes|squad|"
                     r"arsenal|beasts|sword", low) and not re.search(r"passive|upgrade|shop", low):
            return "gacha"
        return ""

    def _until_changed(self) -> None:
        until = self.until.currentData()
        self.runs.setEnabled(until != "never")
        self.runs.setPrefix("× " if until == "runs" else "")
        self.runs.setSuffix(tr(" Min") if until == "minutes" else "")

    # ------------------------------------------------------------------ Liste
    def _add(self) -> None:
        kind = self.kind.currentData()
        task: dict = {"kind": kind}
        if kind == "wait":
            task["seconds"] = self.minutes.value() * 60
        elif kind in ("raid", "autoroll"):
            if not self.target.currentData():
                return
            task["target"] = self.target.currentData()
            if kind == "raid":
                until = self.until.currentData()
                task.update(until=until, leave_wave=self.leave_wave.value(), join=self.join.isChecked())
                if until == "runs":
                    task["runs"] = self.runs.value()
                elif until == "minutes":
                    task["minutes"] = self.runs.value()
        self._append(task)
        self.list.setCurrentRow(self.list.count() - 1)
        self._save()

    def _append(self, task: dict) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, dict(task))
        self.list.addItem(item)
        self._label(self.list.count() - 1, False)

    def _label(self, row: int, running: bool) -> None:
        item = self.list.item(row)
        task = item.data(Qt.ItemDataRole.UserRole)
        item.setText(("▶  " if running else f"{row + 1}.  ") + task_label(task))
        font = QFont(item.font())
        font.setBold(running)
        item.setFont(font)

    def _tasks(self) -> list[dict]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def _relabel(self) -> None:
        for i in range(self.list.count()):
            self._label(i, False)
        self._shown_pos = -2

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self._relabel()
            self._save()

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(new, item)
        self.list.setCurrentRow(new)
        self._relabel()
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
        on = self.macro.enabled
        self.off_hint.setVisible(not on)
        for w in self._controls:
            w.setEnabled(on)
        self.stop_btn.setEnabled(on)
        self._kind_changed()

    def _tick(self) -> None:
        """Laufenden Schritt hervorheben, Zustand darunter."""
        nav = self.macro.navigator
        busy = self.macro.busy
        pos = nav.queue_pos if busy and nav is not None and nav.queue_pos is not None else -1
        if pos != self._shown_pos:
            if 0 <= self._shown_pos < self.list.count():
                self._label(self._shown_pos, False)
            if 0 <= pos < self.list.count():
                self._label(pos, True)
            self._shown_pos = pos
        if not self.macro.enabled:
            text = ""
        elif pos >= 0:
            text = tr("Läuft: Schritt {n} von {count}", n=pos + 1, count=self.list.count())
        elif busy:
            text = tr("Das Makro arbeitet gerade (Abholen oder Erkunden).")
        else:
            text = tr("Bereit – {count} Schritte.", count=self.list.count()) if self.list.count() else \
                tr("Noch keine Schritte – oben auswählen und hinzufügen.")
        if text != self.state.text():
            self.state.setText(text)
        self.run.setEnabled(self.macro.enabled and not busy)

    def _start(self) -> None:
        self.macro.start_queue(self._tasks(), self.loop.isChecked())
