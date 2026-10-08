"""Karte „Automatisch abholen“ (Startseite, unter dem Makro): Fixer Gigs und Gilden-Missionen als eigene Schalter –
keine Aufgaben der Warteschlange (Wunsch des Eigentümers 08.10.2026). Das Makro schiebt sie ein, sobald sie fällig
sind: zwischen den Aufgaben der Schlange, während ein Raid farmt oder – läuft nichts – über den Takt dieser Karte."""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QGridLayout, QMessageBox

from .. import winapi
from ..i18n import tr
from .widgets import Card, label


class ExtrasCard(Card):
    def __init__(self, main, macro_card) -> None:
        super().__init__(tr("Automatisch abholen"),
                         tr("Fixer Gigs (W21): fertige Gigs abholen und neue losschicken – je Gig ein Pet, reihum "
                            "eins der letzten drei im Pets-Fenster. Das Makro merkt sich die Laufzeiten (20 Min. / "
                            "1 Std. / 3 Std.) und kommt erst wieder, wenn einer fertig ist.\n\nGilden-Missionen: "
                            "alle 3 Stunden „Personal“ und „Guild Weekly“ abholen.\n\nBeides läuft nur mit „Makro "
                            "erlauben“ – zwischen den Aufgaben der Warteschlange, während ein Raid farmt oder für "
                            "sich allein."))
        self.main = main
        self.macro = macro_card
        s = main.engine.settings
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self.gigs = QCheckBox(tr("Fixer Gigs"))
        self.gigs.setChecked(bool(s.auto_gigs))
        self.guild = QCheckBox(tr("Gilden-Missionen"))
        self.guild.setChecked(bool(s.auto_guild))
        self.gigs_state = label("", "small")
        self.guild_state = label("", "small")
        grid.addWidget(self.gigs, 0, 0)
        grid.addWidget(self.gigs_state, 0, 1)
        grid.addWidget(self.guild, 1, 0)
        grid.addWidget(self.guild_state, 1, 1)
        self.body.addLayout(grid)
        for box in (self.gigs, self.guild):
            box.toggled.connect(self._save)
        self.timer = QTimer(self)
        self.timer.setInterval(15_000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._update_state()

    def _save(self, *_args) -> None:
        s = self.main.engine.settings
        s.auto_gigs, s.auto_guild = self.gigs.isChecked(), self.guild.isChecked()
        try:
            s.save()                                      # sofort, ohne Speichern-Leiste
        except OSError as exc:
            QMessageBox.critical(self, tr("Speichern"), tr("Konnte nicht speichern: {error}", error=exc))
        self._update_state()
        if self.gigs.isChecked() or self.guild.isChecked():
            QTimer.singleShot(500, self._tick)

    def _update_state(self) -> None:
        nav = self.macro.navigator
        now = time.monotonic()
        for box, state, nxt in ((self.gigs, self.gigs_state, nav.gigs_next if nav else 0.0),
                                (self.guild, self.guild_state, nav.guild_next if nav else 0.0)):
            if not box.isChecked():
                state.setText(tr("aus"))
            elif nxt > now:
                state.setText(tr("nächste in {minutes} Min.", minutes=int((nxt - now) // 60) + 1))
            else:
                state.setText(tr("fällig"))

    def _tick(self) -> None:
        """Läuft gerade nichts im Makro: Fälliges selbst anstoßen (nur mit „Makro erlauben“ und offenem Roblox)."""
        self._update_state()
        if not (self.gigs.isChecked() or self.guild.isChecked()) or not self.macro.enabled.isChecked():
            return
        nav = self.macro._ensure_navigator()
        if nav.busy or not nav.due_extras():
            return
        if winapi.find_window(self.main.engine.settings.window_title) is None:
            return                                        # Roblox nicht offen: still warten
        nav.run_extras()
