"""Makro-Steuerung ohne eigene Karte (seit 0.9.9-beta.7): hält Oberflächen-Karte, Navigator (automation.py) und das
Makro-Protokoll. Die Startseite zeigt nur noch Farm-Routine und „Automatisch abholen“; Schalter „Makro erlauben“,
Erkunden und das Protokoll stehen unter Einstellungen → Makro (Wunsch des Eigentümers 08.10.2026: keine doppelten
Knöpfe, alles über die Routine). Gehört dem Hauptfenster (MainWindow.macro)."""
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
        self.lines: deque[tuple[str, str]] = deque(maxlen=LOG_LINES)   # (Uhrzeit, Text)
        self.log_listeners: list = []                     # f(zeit, text) – Protokoll-Ansichten
        self.clear_listeners: list = []                   # f() – Protokoll geleert
        self.enabled_listeners: list = []                 # f(an) – „Makro erlauben“ geändert
        self.map_listeners: list = []                     # f() – Karte neu geladen (neue Ziele)
        self._afk_restore = False
        QTimer.singleShot(2500, self._restore_learned)

    # ------------------------------------------------------------------ Zustand
    @property
    def enabled(self) -> bool:
        return bool(self.main.engine.settings.automation_enabled) and bool(self.map.entries)

    @property
    def busy(self) -> bool:
        return self.navigator is not None and self.navigator.busy

    def set_enabled(self, on: bool, parent=None) -> bool:
        """„Makro erlauben“ – Einschalten nur nach Warnung (Roblox-Regeln). Rückgabe: neuer Zustand."""
        s = self.main.engine.settings
        if on and not s.automation_enabled:
            answer = QMessageBox.warning(
                parent or self.main, tr("Makro erlauben"),
                tr("Das Makro klickt selbst in Roblox (Mausklicks und Mausrad per SendInput, wie AutoHotkey "
                   "oder ein Autoclicker).\n\nMakros sind laut Roblox-Regeln nicht erlaubt. Wer sie nutzt, "
                   "riskiert eine Sperre – auf eigene Verantwortung.\n\nTrotzdem einschalten?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        s.automation_enabled = bool(on)
        try:
            s.save()                                      # sofort (wie Server-Favoriten), ohne Speichern-Leiste
        except OSError as exc:
            QMessageBox.critical(parent or self.main, tr("Speichern"), tr("Konnte nicht speichern: {error}",
                                                                          error=exc))
        if not on:
            self.stop()
        for f in list(self.enabled_listeners):
            f(self.enabled)
        return bool(on)

    def stop(self) -> None:
        if self.navigator is not None:
            self.navigator.stop()

    # ------------------------------------------------------------------ Protokoll
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
            from ..ocr import OcrEngine
            engine = self.main.engine
            # Einstellungen immer frisch lesen: „Speichern“ ersetzt engine.settings durch ein neues Objekt – ein
            # gemerktes altes Objekt sah danach die Schalter nicht mehr (Automatisch abholen tat nichts)
            nav = automation.Navigator(
                source_factory=lambda: engine._source_factory(engine.settings.capture_mode,
                                                              engine.settings.window_title),
                window_title=engine.settings.window_title,
                ocr_factory=lambda: OcrEngine(engine.settings.tesseract_path),
                log=lambda text: self.main.post(lambda: self.add_log(text)),
                uimap=self.map)
            nav.raid_count = lambda: engine.stats.snapshot().total_attempts   # Raid-Enden (Überwachung)
            nav.monitoring = lambda: engine.running
            nav.wave_visible = lambda: engine.state.wave_value is not None   # Raid läuft wirklich (kein Ladebild)
            # Raid-Aufgabe: Überwachung selbst starten, Raid für die Statistik übernehmen (beides im GUI-Thread)
            nav.start_monitoring = lambda: self.main.post(
                lambda: None if engine.running else self.main.toggle_monitoring())
            nav.set_raid = lambda target: self.main.post(lambda: self._set_raid(target))
            nav.auto_gigs = lambda: bool(engine.settings.auto_gigs)     # Schalter „Automatisch abholen“
            nav.auto_guild = lambda: bool(engine.settings.auto_guild)
            nav.state_path = data_dir() / "extras_state.json"   # Zeiten der Abholungen überdauern Neustarts
            nav._load_state()
            self.navigator = nav
        return self.navigator

    def _set_raid(self, target: str) -> None:
        """Raid der Routine als aktuellen Raid der Statistik setzen – nur, wenn es einen passenden Raid-Namen gibt
        („Alvarez War“ zu „W20 Alvarez War“); sonst bleibt die Auswahl, wie sie ist."""
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
            self.add_log(tr("Das Makro ist aus – Einstellungen → Makro → „Makro erlauben“."))
            return False
        if self.busy:
            self.add_log(tr("Das Makro läuft schon – erst „Stopp“."))
            return False
        return True

    def start_queue(self, tasks: list[dict], loop: bool) -> bool:
        if not self._ready():
            return False
        if not tasks:
            self.add_log(tr("Die Farm-Routine ist leer."))
            return False
        return self.ensure_navigator().run_queue(tasks, loop)

    def run_progression(self) -> bool:
        """Einmal „Auto All“ im ersten Progression-Fenster (gilt für alle Progressions)."""
        if not self._ready():
            return False
        return self.ensure_navigator().progression()

    def run_extras(self) -> bool:
        if not self._ready():
            return False
        return self.ensure_navigator().run_extras()

    # ------------------------------------------------------------------ Erkunden
    def start_explore(self, parent=None) -> None:
        if not self.enabled:
            QMessageBox.information(parent or self.main, tr("Erkunden"),
                                    tr("Erst „Makro erlauben“ einschalten (Einstellungen → Makro)."))
            return
        s = self.main.engine.settings
        minutes = int(s.explore_minutes)
        answer = QMessageBox.question(
            parent or self.main, tr("Erkunden"),
            tr("Das Makro übernimmt Roblox für bis zu {minutes} Minuten und öffnet dabei Menüs im Spiel (nur öffnen "
               "und schließen, nichts kaufen oder rollen).\n\nNicht die Maus bewegen – das bricht ab (Esc ebenso). "
               "Starten?", minutes=minutes))
        if answer != QMessageBox.StandardButton.Yes:
            return
        nav = self.ensure_navigator()
        if nav.busy:
            self.add_log(tr("Das Makro läuft schon – erst „Stopp“."))
            return
        from ..app_paths import data_dir
        # Anti-AFK während des Erkundens aus (das Makro klickt ohnehin), danach wieder an (Wunsch des Eigentümers)
        self._afk_restore = s.anti_afk_enabled
        if self._afk_restore:
            self.main.set_anti_afk(False)
            self.add_log(tr("Anti-AFK pausiert, solange das Erkunden läuft."))
        nav.explore(minutes, data_dir(), revisit=bool(s.explore_revisit))
        self._watch_explore()

    def _watch_explore(self) -> None:
        """Nach dem Erkunden die Karte neu laden, damit neue Ziele auswählbar sind."""
        if self.busy:
            QTimer.singleShot(1000, self._watch_explore)
            return
        if self._afk_restore:
            self._afk_restore = False
            self.main.set_anti_afk(True)                   # Zähler beginnt neu mit einem vollen Intervall
            self.add_log(tr("Anti-AFK wieder an."))
        self.reload_map()
        self.open_review()

    def open_review(self, always: bool = False) -> None:
        """Funde des Erkundens bestätigen lassen (nur wenn etwas offen ist, außer always)."""
        from .. import app_paths, review
        if not always and not review.pending(app_paths.data_dir()):
            return
        from .explore_review import ReviewDialog
        ReviewDialog(self.main).exec()
        self.reload_map()                                 # bestätigte Arten gelten sofort

    def open_report(self) -> None:
        import os
        from ..app_paths import data_dir
        folder = data_dir() / "explore"
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))                          # noqa: S606 – eigener Datenordner

    def reload_map(self) -> None:
        self.map = UiMap.load()
        if self.navigator is not None:
            self.navigator.map = self.map
        for f in list(self.map_listeners):
            f()

    def _restore_learned(self) -> None:
        """Beim Start: Welt-Fenster aus früheren Erkundungs-Berichten, die der Karte fehlen, wieder aufnehmen."""
        from ..app_paths import data_dir
        from ..explorer import restore_from_reports
        if self.busy:
            return
        try:
            from ..review import dedupe
            dedupe(data_dir())                            # doppelte Funde (z. B. „Sword 1“ / „Sword 1 Fenster“)
            count = restore_from_reports(data_dir(), self.map)
        except Exception:  # noqa: BLE001 – nur eine Ergänzung, nie den Start stören
            return
        if count:
            self.add_log(tr("{count} gelernte Fenster aus früheren Erkundungen übernommen.", count=count))
            self.reload_map()
