"""Karte „Makro (Beta)“ (Startseite, links oben): erste Wege im Spiel – Menü per Karte öffnen, Pets-Roll „Auto!“
drücken und danach wieder schließen. Standard aus; Einschalten nur nach Warnung (Roblox-Regeln).
Die Logik steckt in automation.py (ohne Qt)."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QListWidget, QMessageBox, QPushButton

from ..i18n import tr
from ..uimap import UiMap, natural
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
        self.target.setMinimumContentsLength(12)             # lange Namen machen die Seite sonst zu breit
        for w in self.map.targets():
            if w["name"] != "Teleporter Fenster":
                self.target.addItem(w["name"], w["name"])
        self.go = QPushButton(tr("Hin navigieren"))
        self.go.setObjectName("primary")
        self.go.clicked.connect(lambda: self._start("navigate", self.target.currentData()))
        row.addWidget(self.target, 1)
        row.addWidget(self.go)
        self.body.addLayout(row)

        row2 = QHBoxLayout()
        self.world = QComboBox()
        worlds = sorted({m.group(1) for w in self.map.entries
                         if (m := re.match(r"(W\d+) Pets-Roll$", w.get("name", "")))}, key=natural)
        for w in worlds:
            self.world.addItem(w, w)
        self.pets = QPushButton(tr("Pets rollen (Auto!)"))
        self.pets.clicked.connect(lambda: self._start("pets", self.world.currentData()))
        self.close_after = QCheckBox(tr("Danach schließen"))
        self.close_after.setToolTip(tr("Klickt nach „Auto!“ gleich „CLOSE“ – Auto-Roll läuft im Hintergrund "
                                       "weiter."))
        self.close_after.setChecked(True)
        self.close_btn = QPushButton(tr("Menü schließen"))
        self.close_btn.clicked.connect(lambda: self._start("close", None))
        self.stop_btn = QPushButton(tr("Stopp"))
        self.stop_btn.clicked.connect(lambda: self.navigator and self.navigator.stop())
        row2.addWidget(self.world)
        row2.addWidget(self.pets, 1)
        row2.addWidget(self.close_after)
        self.body.addLayout(row2)
        row0.addWidget(self.close_btn)
        row0.addWidget(self.stop_btn)

        self.log = QListWidget()
        smooth(self.log)
        theme.track_fixed_height(self.log, 66)
        self.body.addWidget(self.log)
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
        for w in (self.target, self.go, self.world, self.pets, self.close_after, self.close_btn):
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
        return self.navigator

    def _start(self, what: str, arg) -> None:
        if not self.enabled.isChecked():
            return
        nav = self._ensure_navigator()
        if nav.busy:
            self._add_log(tr("Läuft schon – erst „Stopp“."))
            return
        if what == "navigate" and arg:
            nav.navigate(arg)
        elif what == "pets" and arg:
            nav.pets_auto(arg, close_after=self.close_after.isChecked())
        elif what == "close":
            nav.close_menu()

    def _add_log(self, text: str) -> None:
        self.log.addItem(text)
        while self.log.count() > 60:
            self.log.takeItem(0)
        self.log.scrollToBottom()
        self.log.item(self.log.count() - 1).setFlags(Qt.ItemFlag.ItemIsEnabled)
