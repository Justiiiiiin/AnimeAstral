"""Card “Auto collect” (start page, bottom right – the quests have room above it without the card jumping):
Fixer Gigs and guild missions as switches, “Progressions: Auto All” as a one-shot button (owner's wish
08.10.2026). The macro slots in whatever is due: between the steps of the farm routine, while a raid is farming
or – if nothing runs – via this card's timer. Times: gigs read per card (20 min / 1 h / 3 h, random), guild once a
day; both survive a restart."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QMessageBox, QPushButton

from .. import winapi
from ..automation import fmt_wait
from ..i18n import tr
from .widgets import Card, ToggleSwitch, label


def _shown(widget) -> bool:
    """Only draw when visible (window open, not minimized) – saves load in the background."""
    return widget.isVisible() and not widget.window().isMinimized()


class _ClickLabel(QLabel):
    """Label of a switch: a click on it toggles (like the text next to a checkbox)."""

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
                            "– one of the last three. It reads every slot (running, done, needs a pet, empty) and "
                            "the time left, and comes back as soon as a gig is done or new gigs arrive. It never "
                            "presses “Finish Now”.\n\nGuild missions: claim “Personal” and “Guild Weekly” once per "
                            "day (your PC's date). If there is nothing to claim yet, it tries again 3 hours later."
                            "\n\nProgressions: presses "
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
        grid.addWidget(_ClickLabel(tr("Fixer Gigs (W21)"), self.gigs), 0, 1)   # text clickable like next to a checkbox
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
        self.fast = QTimer(self)                          # display (button/times) more often than the tick
        self.fast.setInterval(1000)
        self.fast.timeout.connect(lambda: self._update_state() if _shown(self) else None)
        self.fast.start()
        self._update_state()

    def _save(self, *_args) -> None:
        s = self.main.engine.settings
        s.auto_gigs, s.auto_guild = self.gigs.isChecked(), self.guild.isChecked()
        try:
            s.save()                                      # right away, without the save bar
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
            nav = self.macro.ensure_navigator()           # load remembered times (survive restarts)
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
        """If the macro isn't doing anything: start what is due (only with “Allow macro” and Roblox open)."""
        self._update_state()
        if not (self.gigs.isChecked() or self.guild.isChecked()) or not self.macro.enabled:
            return
        nav = self.macro.ensure_navigator()
        if nav.busy or not nav.due_extras():
            return
        if winapi.find_window(self.main.engine.settings.window_title) is None:
            return                                        # Roblox not open: wait quietly
        nav.run_extras()
