"""Karte „Makro (Beta)“ (Startseite, links oben): erste Wege im Spiel – Menü per Karte öffnen, Pets-Roll „Auto!“
drücken und danach wieder schließen. Standard aus; Einschalten nur nach Warnung (Roblox-Regeln).
Die Logik steckt in automation.py (ohne Qt)."""
from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QListWidget, QMessageBox, QPushButton, QSpinBox

from ..i18n import tr
from ..uimap import UiMap
from . import theme
from .widgets import Card, label, smooth


class AutomationCard(Card):
    def __init__(self, main) -> None:
        super().__init__(tr("Makro (Beta)"),
                         tr("Öffnet Menüs im Spiel anhand der mitgelieferten Oberflächen-Karte: Teleporter auf, zur "
                            "Welt scrollen, Symbol anklicken, Titel prüfen. „Pets rollen“ öffnet das Roll-Menü der "
                            "Welt, drückt „Auto!“ und schließt das Menü gleich wieder – Auto-Roll läuft im "
                            "Hintergrund weiter. Kein Laufen, kein Teleportieren.\n\nNot-Aus: Maus bewegen, Esc "
                            "oder „Stopp“. Roblox muss sichtbar sein (nicht minimiert) und wird dafür "
                            "nach vorne geholt.\n\nHinweis: Makros sind laut Roblox-Regeln nicht erlaubt – Nutzung "
                            "auf eigene Verantwortung."))
        self.main = main
        self.map = UiMap.load()
        self.navigator = None
        self.enabled = QCheckBox(tr("Makro erlauben"))
        self.enabled.setChecked(bool(main.engine.settings.automation_enabled))
        self.enabled.toggled.connect(self._toggle)
        row0 = QHBoxLayout()                              # Schalter + Schließen/Stopp in einer Zeile (Höhe sparen)
        row0.addWidget(self.enabled)
        row0.addStretch(1)
        self.body.addLayout(row0)

        row = QHBoxLayout()
        self.target = QComboBox()
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.setMinimumContentsLength(8)              # lange Namen machen die Seite sonst zu breit
        for text, name in self.map.sorted_targets():       # nach Welt sortiert, Progression nur einmal
            self.target.addItem(text, name)
        self.go = QPushButton(tr("Hin navigieren"))
        self.go.setObjectName("primary")
        self.go.clicked.connect(lambda: self._start("navigate", self.target.currentData()))
        row.addWidget(self.target, 1)
        row.addWidget(self.go)
        self.body.addLayout(row)

        self.roll = QPushButton(tr("Auto Roll"))
        self.roll.setToolTip(tr("Ziel öffnen, „Auto Roll“ bzw. „Auto!“ drücken und gleich wieder schließen – das "
                                "Spiel rollt im Hintergrund weiter (Gachas, Titans, Pets-Roll)."))
        self.roll.clicked.connect(lambda: self._start("autoroll", self.target.currentData()))
        row.insertWidget(2, self.roll)
        self.close_btn = QPushButton(tr("Menü schließen"))
        self.close_btn.clicked.connect(lambda: self._start("close", None))
        self.stop_btn = QPushButton(tr("Stopp"))
        self.stop_btn.clicked.connect(lambda: self.navigator and self.navigator.stop())
        row0.addWidget(self.close_btn)
        row0.addWidget(self.stop_btn)
        row2 = QHBoxLayout()                              # Erkunden steht unter Einstellungen → Makro
        self.prog = QPushButton(tr("Progressions: Roll All"))
        self.prog.setToolTip(tr("Erstes Progression-Fenster öffnen und „Roll All“ drücken – gilt für alle "
                                "Progressions; danach schließen."))
        self.prog.clicked.connect(lambda: self._start("progression", None))
        row2.addWidget(self.prog)
        row2.addStretch(1)
        self.body.addLayout(row2)
        self._explore_controls = [self.prog]

        self.log = QListWidget()
        smooth(self.log)
        theme.track_min_height(self.log, 58)               # wächst mit der Spalte (Startseite = Makro)
        self.body.addWidget(self.log, 1)
        if not self.map.entries:
            self.body.addWidget(label(tr("Keine Oberflächen-Karte vorhanden."), "muted"))
        self._update()

    # ------------------------------------------------------------------ Schalter
    def _toggle(self, on: bool) -> None:
        s = self.main.engine.settings
        if on and not s.automation_enabled:
            answer = QMessageBox.warning(
                self, tr("Makro (Beta)"),
                tr("Das Makro klickt selbst in Roblox (Mausklicks und Mausrad per SendInput, wie AutoHotkey "
                   "oder ein Autoclicker).\n\nMakros sind laut Roblox-Regeln nicht erlaubt. Wer sie nutzt, "
                   "riskiert eine Sperre – auf eigene Verantwortung.\n\nTrotzdem einschalten?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.enabled.blockSignals(True)
                self.enabled.setChecked(False)
                self.enabled.blockSignals(False)
                return
        s.automation_enabled = bool(on)
        try:
            s.save()                                      # sofort (wie Server-Favoriten), ohne Speichern-Leiste
        except OSError as exc:
            QMessageBox.critical(self, tr("Speichern"), tr("Konnte nicht speichern: {error}", error=exc))
        if not on and self.navigator is not None:
            self.navigator.stop()
        self._update()

    def _update(self) -> None:
        on = self.enabled.isChecked() and bool(self.map.entries)
        for w in (self.target, self.go, self.roll, self.close_btn, *getattr(self, "_explore_controls", [])):
            w.setEnabled(on)
        self.stop_btn.setEnabled(on)

    # ------------------------------------------------------------------ Aufgaben
    def _ensure_navigator(self):
        if self.navigator is None:
            from .. import automation
            from ..ocr import OcrEngine
            engine = self.main.engine
            s = engine.settings
            self.navigator = automation.Navigator(
                source_factory=lambda: engine._source_factory(s.capture_mode, s.window_title),
                window_title=s.window_title,
                ocr_factory=lambda: OcrEngine(s.tesseract_path),
                log=lambda text: self.main.post(lambda: self._add_log(text)),
                uimap=self.map)
            self.navigator.raid_count = lambda: engine.stats.snapshot().total_attempts   # Raid-Enden (Überwachung)
            self.navigator.monitoring = lambda: engine.running
            # Raid-Aufgabe: Überwachung selbst starten, Raid für die Statistik übernehmen (beides im GUI-Thread)
            self.navigator.start_monitoring = lambda: self.main.post(
                lambda: None if engine.running else self.main.toggle_monitoring())
            self.navigator.set_raid = lambda target: self.main.post(lambda: self._set_raid(target))
            self.navigator.auto_gigs = lambda: bool(s.auto_gigs)        # Schalter „Automatisch abholen“
            self.navigator.auto_guild = lambda: bool(s.auto_guild)
        return self.navigator

    def _set_raid(self, target: str) -> None:
        """Raid der Warteschlange als aktuellen Raid der Statistik setzen – nur, wenn es einen passenden Raid-Namen
        gibt („Alvarez War“ zu „W20 Alvarez War“); sonst bleibt die Auswahl, wie sie ist."""
        import re
        engine = self.main.engine
        key = re.sub(r"[^a-z0-9]", "", re.sub(r"^W\d+\s+", "", target).lower())
        for name in engine.profile_store.names():
            norm = re.sub(r"[^a-z0-9]", "", name.lower())
            if norm and (norm == key or norm in key or key in norm):
                if engine.settings.current_raid != name:
                    engine.set_current_raid(name)
                return

    def _start(self, what: str, arg) -> None:
        if not self.enabled.isChecked():
            return
        nav = self._ensure_navigator()
        if nav.busy:
            self._add_log(tr("Läuft schon – erst „Stopp“."))
            return
        if what == "navigate" and arg:
            nav.navigate(arg)
        elif what == "autoroll" and arg:
            nav.autoroll(arg)
        elif what == "close":
            nav.close_menu()
        elif what == "progression":
            nav.progression()

    def start_explore(self) -> None:
        """Erkunden starten (Knopf unter Einstellungen → Makro)."""
        if not self.enabled.isChecked():
            QMessageBox.information(self, tr("Erkunden"), tr("Erst auf der Startseite „Makro erlauben“ einschalten."))
            return
        s = self.main.engine.settings
        minutes = int(s.explore_minutes)
        answer = QMessageBox.question(
            self, tr("Erkunden"),
            tr("Das Makro übernimmt Roblox für bis zu {minutes} Minuten und öffnet dabei Menüs im Spiel (nur öffnen "
               "und schließen, nichts kaufen oder rollen).\n\nNicht die Maus bewegen – das bricht ab (Esc ebenso). "
               "Starten?", minutes=minutes))
        if answer != QMessageBox.StandardButton.Yes:
            return
        nav = self._ensure_navigator()
        if nav.busy:
            self._add_log(tr("Läuft schon – erst „Stopp“."))
            return
        from ..app_paths import data_dir
        # Anti-AFK während des Erkundens aus (das Makro klickt ohnehin), danach wieder an (Wunsch des Eigentümers)
        self._afk_restore = self.main.engine.settings.anti_afk_enabled
        if self._afk_restore:
            self.main.set_anti_afk(False)
            self._add_log(tr("Anti-AFK pausiert, solange das Erkunden läuft."))
        nav.explore(minutes, data_dir(), revisit=bool(s.explore_revisit))
        self._watch_explore()

    def _watch_explore(self) -> None:
        """Nach dem Erkunden die Karte neu laden, damit neue Ziele auswählbar sind."""
        from PySide6.QtCore import QTimer
        if self.navigator is not None and self.navigator.busy:
            QTimer.singleShot(1000, self._watch_explore)
            return
        if getattr(self, "_afk_restore", False):
            self._afk_restore = False
            self.main.set_anti_afk(True)                   # Zähler beginnt neu mit einem vollen Intervall
            self._add_log(tr("Anti-AFK wieder an."))
        self.reload_map()

    def reload_map(self) -> None:
        self.map = UiMap.load()
        if self.navigator is not None:
            self.navigator.map = self.map
        current = self.target.currentData()
        self.target.clear()
        for text, name in self.map.sorted_targets():
            self.target.addItem(text, name)
        self.target.setCurrentIndex(max(0, self.target.findData(current)))
        queue = getattr(self.main.pages.built(0), "queue", None)
        if queue is not None:
            queue.reload()

    def open_report(self) -> None:
        import os
        from ..app_paths import data_dir
        folder = data_dir() / "explore"
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))                          # noqa: S606 – eigener Datenordner

    def _add_log(self, text: str) -> None:
        self.log.addItem(text)
        while self.log.count() > 60:
            self.log.takeItem(0)
        self.log.scrollToBottom()
        self.log.item(self.log.count() - 1).setFlags(Qt.ItemFlag.ItemIsEnabled)
