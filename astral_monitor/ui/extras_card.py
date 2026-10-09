"""Karte „Automatisch abholen“ (Startseite, rechts ganz unten – Quests haben darüber Platz, ohne dass die Karte
springt): Fixer Gigs und Gilden-Missionen als Schalter, „Progressions: Auto All“ als Knopf für einmal
(Wunsch des Eigentümers 08.10.2026). Das Makro schiebt Fälliges ein: zwischen den Schritten der Farm-Routine,
während ein Raid farmt oder – läuft nichts – über den Takt dieser Karte. Zeiten: Gigs je Karte gelesen
(20 Min. / 1 Std. / 3 Std., zufällig), Gilde einmal am Tag; beides überdauert einen Neustart."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QMessageBox, QPushButton

from .. import winapi
from ..automation import fmt_wait
from ..i18n import tr
from .widgets import Card, ToggleSwitch, label


def _shown(widget) -> bool:
    """Nur zeichnen, wenn man es sieht (Fenster offen, nicht minimiert) – spart Last im Hintergrund."""
    return widget.isVisible() and not widget.window().isMinimized()


class _ClickLabel(QLabel):
    """Beschriftung eines Schalters: ein Klick darauf schaltet um (wie der Text neben einem Häkchen)."""

    def __init__(self, text: str, switch) -> None:
        super().__init__(text)
        self.switch = switch
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if self.switch.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.switch.toggle()
        super().mouseReleaseEvent(event)


class ExtrasCard(Card):
    def __init__(self, main) -> None:
        super().__init__(tr("Auto collect"),
                         tr("Fixer Gigs (W21): the macro claims finished gigs and sends new ones with one pet each "
                            "– one of the last three. Each gig takes 20 min, 1 h or 3 h; the macro reads the time "
                            "left and only comes back when one is done. It never presses “Finish Now”.\n\nGuild "
                            "missions: claim “Personal” and “Guild Weekly” once a day.\n\nProgressions: presses "
                            "“Auto All” once – it applies to all worlds.\n\nOnly works with “Allow macro” – between "
                            "the steps of the farm routine, while a raid is farming or on its own."))
        self.main = main
        self.macro = main.macro
        s = main.engine.settings
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self.gigs = ToggleSwitch()
        self.gigs.setChecked(bool(s.auto_gigs))
        self.guild = ToggleSwitch()
        self.guild.setChecked(bool(s.auto_guild))
        self.gigs_state = label("", "small")
        self.guild_state = label("", "small")
        grid.addWidget(self.gigs, 0, 0)
        grid.addWidget(_ClickLabel(tr("Fixer Gigs (W21)"), self.gigs), 0, 1)   # Text klickbar wie bei Häkchen
        grid.addWidget(self.gigs_state, 0, 2)
        grid.addWidget(self.guild, 1, 0)
        grid.addWidget(_ClickLabel(tr("Guild missions"), self.guild), 1, 1)
        grid.addWidget(self.guild_state, 1, 2)
        self.prog = QPushButton(tr("Progressions: Auto All"))
        self.prog.setToolTip(tr("Run once: opens the first progression, presses “Auto All” and closes it again"))
        self.prog.clicked.connect(self._progression)
        self.prog_state = label("", "small")
        grid.addWidget(self.prog, 2, 0, 1, 2)
        grid.addWidget(self.prog_state, 2, 2)
        self.body.addLayout(grid)
        for box in (self.gigs, self.guild):
            box.toggled.connect(self._save)
        self.macro.enabled_listeners.append(lambda _on: self._update_state())
        self.timer = QTimer(self)
        self.timer.setInterval(15_000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.fast = QTimer(self)                          # Anzeige (Knopf/Zeiten) öfter als der Takt
        self.fast.setInterval(1000)
        self.fast.timeout.connect(lambda: self._update_state() if _shown(self) else None)
        self.fast.start()
        self._update_state()

    def _save(self, *_args) -> None:
        s = self.main.engine.settings
        s.auto_gigs, s.auto_guild = self.gigs.isChecked(), self.guild.isChecked()
        try:
            s.save()                                      # sofort, ohne Speichern-Leiste
        except OSError as exc:
            QMessageBox.critical(self, tr("Save"), tr("Could not save: {error}", error=exc))
        self._update_state()
        if self.gigs.isChecked() or self.guild.isChecked():
            QTimer.singleShot(500, self._tick)

    def _progression(self) -> None:
        if self.macro.run_progression():
            self.prog_state.setText(tr("last {time}", time=time.strftime("%H:%M")))

    def _update_state(self) -> None:
        on = self.macro.enabled
        nav = self.macro.navigator
        if on and nav is None and (self.gigs.isChecked() or self.guild.isChecked()):
            nav = self.macro.ensure_navigator()           # gemerkte Zeiten laden (überdauern Neustarts)
        now = time.time()
        for box, state, nxt in ((self.gigs, self.gigs_state, nav.gigs_next if nav else 0.0),
                                (self.guild, self.guild_state, nav.guild_next if nav else 0.0)):
            box.setEnabled(on)
            if not on:
                text = tr("Macro off")
            elif not box.isChecked():
                text = tr("off")
            elif nxt > now:
                text = tr("in {time}", time=fmt_wait(nxt - now))
            else:
                text = tr("due")
            if state.text() != text:
                state.setText(text)
        self.prog.setEnabled(on and not self.macro.busy)

    def _tick(self) -> None:
        """Läuft gerade nichts im Makro: Fälliges selbst anstoßen (nur mit „Makro erlauben“ und offenem Roblox)."""
        self._update_state()
        if not (self.gigs.isChecked() or self.guild.isChecked()) or not self.macro.enabled:
            return
        nav = self.macro.ensure_navigator()
        if nav.busy or not nav.due_extras():
            return
        if winapi.find_window(self.main.engine.settings.window_title) is None:
            return                                        # Roblox nicht offen: still warten
        nav.run_extras()
