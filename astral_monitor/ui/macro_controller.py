"""Macro control without a card of its own (since 0.9.9-beta.7): holds the UI map, the navigator (automation.py) and
the macro log. The start page only shows the farm routine and “Auto collect”; the switch “Allow macro”, exploring
and the log are under Settings → Macro (owner's wish 08.10.2026: no duplicate buttons, everything through the
routine). Owned by the main window (MainWindow.macro)."""
from __future__ import annotations

import re
import time
from collections import deque

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox

from ..i18n import tr
from ..uimap import UiMap

LOG_LINES = 400


class MacroController(QObject):
    def __init__(self, main) -> None:
        super().__init__(main)
        self.main = main
        self.map = UiMap.load()
        self.navigator = None
        self.lines: deque[tuple[str, str]] = deque(maxlen=LOG_LINES)   # (time, text)
        self.log_listeners: list = []                     # f(time, text) – log views
        self.clear_listeners: list = []                   # f() – log cleared
        self.enabled_listeners: list = []                 # f(on) – “Allow macro” changed
        self.map_listeners: list = []                     # f() – map reloaded (new targets)
        self._afk_restore = False
        QTimer.singleShot(2500, self._restore_learned)

    # ------------------------------------------------------------------ State
    @property
    def enabled(self) -> bool:
        return bool(self.main.engine.settings.automation_enabled) and bool(self.map.entries)

    @property
    def busy(self) -> bool:
        return self.navigator is not None and self.navigator.busy

    def set_enabled(self, on: bool, parent=None) -> bool:
        """“Allow macro” – switching on only after a warning (Roblox rules). Returns the new state."""
        s = self.main.engine.settings
        if on and not s.automation_enabled:
            answer = QMessageBox.warning(
                parent or self.main, tr("Allow macro"),
                tr("The macro clicks in Roblox by itself (mouse clicks and wheel via SendInput, like AutoHotkey or "
                   "an autoclicker).\n\nMacros are not allowed by the Roblox rules. Using them risks a ban – at "
                   "your own risk.\n\nTurn it on anyway?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        s.automation_enabled = bool(on)
        try:
            s.save()                                      # right away (like server favorites), without the save bar
        except OSError as exc:
            QMessageBox.critical(parent or self.main, tr("Save"), tr("Could not save: {error}",
                                                                          error=exc))
        if not on:
            self.stop()
        for f in list(self.enabled_listeners):
            f(self.enabled)
        return bool(on)

    def stop(self) -> None:
        if self.navigator is not None:
            self.navigator.stop()

    # ------------------------------------------------------------------ Log
    def add_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.lines.append((stamp, text))
        for f in list(self.log_listeners):
            f(stamp, text)

    def clear_log(self) -> None:
        self.lines.clear()
        for f in list(self.clear_listeners):
            f()

    # ------------------------------------------------------------------ Navigator
    def ensure_navigator(self):
        if self.navigator is None:
            from .. import automation
            from ..app_paths import data_dir
            engine = self.main.engine
            # always read the settings fresh: “Save” replaces engine.settings with a new object – a remembered
            # old object didn't see the switches anymore afterwards (auto collect did nothing)
            nav = automation.Navigator(
                source_factory=lambda: engine._source_factory(engine.settings.capture_mode,
                                                              engine.settings.window_title),
                window_title=engine.settings.window_title,
                ocr_factory=engine.get_ocr,              # one Tesseract model for monitoring + macro (RAM)
                log=lambda text: self.main.post(lambda: self.add_log(text)),
                uimap=self.map)
            nav.raid_count = lambda: engine.stats.snapshot().total_attempts   # raid ends (monitoring)
            nav.monitoring = lambda: engine.running
            nav.wave_visible = lambda: engine.state.wave_value is not None   # the raid is really running (no loading screen)
            # raid task: start monitoring itself, take over the raid for the statistics (both in the GUI thread)
            nav.start_monitoring = lambda: self.main.post(
                lambda: None if engine.running else self.main.toggle_monitoring())
            nav.set_raid = lambda target: self.main.post(lambda: self._set_raid(target))
            nav.auto_gigs = lambda: bool(engine.settings.auto_gigs)     # switch “Auto collect”
            nav.auto_guild = lambda: bool(engine.settings.auto_guild)
            nav.state_path = data_dir() / "extras_state.json"   # collect times survive restarts
            nav._load_state()
            self.navigator = nav
        return self.navigator

    def _set_raid(self, target: str) -> None:
        """Set the routine's raid as the current raid of the statistics – only if there is a matching raid name
        (“Alvarez War” for “W20 Alvarez War”); otherwise the selection stays as it is."""
        engine = self.main.engine
        key = re.sub(r"[^a-z0-9]", "", re.sub(r"^W\d+\s+", "", target).lower())
        for name in engine.profile_store.names():
            norm = re.sub(r"[^a-z0-9]", "", name.lower())
            if norm and (norm == key or norm in key or key in norm):
                if engine.settings.current_raid != name:
                    engine.set_current_raid(name)
                return

    def _ready(self) -> bool:
        if not self.enabled:
            self.add_log(tr("The macro is off – Settings → Macro → “Allow macro”."))
            return False
        if self.busy:
            self.add_log(tr("The macro is already running – press “Stop” first."))
            return False
        return True

    def start_queue(self, tasks: list[dict], loop: bool) -> bool:
        if not self._ready():
            return False
        if not tasks:
            self.add_log(tr("The farm routine is empty."))
            return False
        return self.ensure_navigator().run_queue(tasks, loop)

    def run_progression(self) -> bool:
        """Press “Auto All” once in the first progression window (applies to all progressions)."""
        if not self._ready():
            return False
        return self.ensure_navigator().progression()

    def run_extras(self) -> bool:
        if not self._ready():
            return False
        return self.ensure_navigator().run_extras()

    # ------------------------------------------------------------------ Explore
    def start_explore(self, parent=None) -> None:
        if not self.enabled:
            QMessageBox.information(parent or self.main, tr("Explore"),
                                    tr("Turn on “Allow macro” first (Settings → Macro)."))
            return
        s = self.main.engine.settings
        minutes = int(s.explore_minutes)
        answer = QMessageBox.question(
            parent or self.main, tr("Explore"),
            tr("The macro takes over Roblox for up to {minutes} minutes and opens menus in the game (only opening "
               "and closing, no buying or rolling).\n\nDo not move the mouse – that cancels it (Esc too). Start?", minutes=minutes))
        if answer != QMessageBox.StandardButton.Yes:
            return
        nav = self.ensure_navigator()
        if nav.busy:
            self.add_log(tr("The macro is already running – press “Stop” first."))
            return
        from ..app_paths import data_dir
        # Anti-AFK off while exploring (the macro clicks anyway), on again afterwards (owner's wish)
        self._afk_restore = s.anti_afk_enabled
        if self._afk_restore:
            self.main.set_anti_afk(False)
            self.add_log(tr("Anti-AFK paused while exploring."))
        nav.explore(minutes, data_dir(), revisit=bool(s.explore_revisit))
        self._watch_explore()

    def _watch_explore(self) -> None:
        """After exploring, reload the map so new targets can be chosen."""
        if self.busy:
            QTimer.singleShot(1000, self._watch_explore)
            return
        if self._afk_restore:
            self._afk_restore = False
            self.main.set_anti_afk(True)                   # the counter starts again with a full interval
            self.add_log(tr("Anti-AFK back on."))
        self.reload_map()
        self.open_review()

    def open_review(self, always: bool = False) -> None:
        """Let the user confirm the findings of exploring (only if something is open, unless always)."""
        from .. import app_paths, review
        if not always and not review.pending(app_paths.data_dir()):
            return
        from .explore_review import ReviewDialog
        ReviewDialog(self.main).exec()
        self.reload_map()                                 # confirmed kinds apply right away

    def open_report(self) -> None:
        import os
        from ..app_paths import data_dir
        folder = data_dir() / "explore"
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))                          # noqa: S606 – own data folder

    def reload_map(self) -> None:
        self.map = UiMap.load()
        if self.navigator is not None:
            self.navigator.map = self.map
        for f in list(self.map_listeners):
            f()

    def _restore_learned(self) -> None:
        """At start-up: take world windows from earlier explore reports that are missing in the map back in."""
        from ..app_paths import data_dir
        from ..explorer import restore_from_reports
        if self.busy:
            return
        try:
            from ..review import dedupe
            dedupe(data_dir())                            # duplicate findings (e.g. “Sword 1” / “Sword 1 Fenster”)
            count = restore_from_reports(data_dir(), self.map)
        except Exception:  # noqa: BLE001 – only an extra, never disturb the start
            return
        if count:
            self.add_log(tr("{count} learned windows restored from earlier explore runs.", count=count))
            self.reload_map()
