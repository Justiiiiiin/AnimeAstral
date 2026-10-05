"""Seite „Erkennung": Aufnahme, Wellenzähler, Quests, OCR, Tests."""
from __future__ import annotations

import time

import cv2
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..engine import EngineError
from ..settings import DEFAULT_QUEST_ROI, DEFAULT_WAVE_ROI, Roi
from ..tracker import QuestTracker
from .region_dialog import RegionDialog
from .widgets import SpinBox, ComboBox, Card, bgr_to_pixmap, label


class DetectPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.engine = main.engine
        self.wave_roi = Roi(**vars(DEFAULT_WAVE_ROI))
        self.quest_roi = Roi(**vars(DEFAULT_QUEST_ROI))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(12)
        outer.addWidget(label("Erkennung", "h1"))
        outer.addWidget(label("Bereiche, Auslöser und Tests. Alles wird live am Roblox-Fenster geprüft.", "muted"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(14)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        lay.addWidget(self._capture_card())
        lay.addWidget(self._wave_card())
        lay.addWidget(self._quest_card())
        lay.addWidget(self._ocr_card())
        lay.addStretch(1)

        save = QPushButton("Speichern")
        save.setObjectName("primary")
        save.clicked.connect(lambda: self.main.save_settings())
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(save)
        outer.addLayout(row)

    # ------------------------------------------------------------------ Karten
    def _capture_card(self) -> Card:
        card = Card("Aufnahme")
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)
        self.title = QLineEdit()
        self.mode = ComboBox()
        self.mode.addItem("Automatisch (Fenster-Capture, sonst Bildschirm)", "auto")
        self.mode.addItem("Fenster-Capture (Roblox darf verdeckt sein)", "wgc")
        self.mode.addItem("Bildschirm (Roblox muss sichtbar sein)", "screen")
        grid.addWidget(label("Fenstertitel"), 0, 0)
        grid.addWidget(self.title, 0, 1)
        grid.addWidget(label("Aufnahmeart"), 1, 0)
        grid.addWidget(self.mode, 1, 1)
        card.body.addLayout(grid)
        row = QHBoxLayout()
        test = QPushButton("Capture-Test")
        test.clicked.connect(self._test_capture)
        row.addWidget(test)
        row.addStretch(1)
        card.body.addLayout(row)
        card.body.addWidget(label("Aufnahmeart-Änderungen gelten nach einem Neustart der Überwachung. "
                                  "Wechselst du zwischen Vollbild und Fenstermodus, Bereiche neu auswählen.",
                                  "small", wrap=True))
        return card

    def _wave_card(self) -> Card:
        card = Card("Wellenzähler („Wave 12/100“)")
        card.body.addWidget(label("Wähle den Bereich großzügig (z. B. die ganze obere Mitte des Fensters). Das "
                                  "Programm findet „Wave x/100“ darin selbst, auch im Fenstermodus oder bei "
                                  "verschobenem Layout. Der Bereich muss den Zähler nur enthalten.", "small", wrap=True))
        row = QHBoxLayout()
        self.lbl_wave_roi = label("")
        row.addWidget(self.lbl_wave_roi, 1)
        pick = QPushButton("Bereich auswählen …")
        pick.clicked.connect(lambda: self._pick("wave"))
        reset = QPushButton("Standard")
        reset.clicked.connect(lambda: self._reset("wave"))
        row.addWidget(pick)
        row.addWidget(reset)
        card.body.addLayout(row)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)
        self.totals = QLineEdit()
        self.totals.setPlaceholderText("z. B. 100  oder  100, 50")
        self.offset = SpinBox()
        self.offset.setRange(0, 5)
        self.confirm = SpinBox()
        self.confirm.setRange(1, 4)
        self.cooldown = SpinBox()
        self.cooldown.setRange(0, 3600)
        self.cooldown.setSuffix(" s")
        grid.addWidget(label("Erlaubte Gesamtwellen"), 0, 0)
        grid.addWidget(self.totals, 0, 1)
        grid.addWidget(label("Auslöser: Gesamt minus"), 1, 0)
        grid.addWidget(self.offset, 1, 1)
        grid.addWidget(label("Bestätigungen"), 2, 0)
        grid.addWidget(self.confirm, 2, 1)
        grid.addWidget(label("Sperrzeit zwischen Raids"), 3, 0)
        grid.addWidget(self.cooldown, 3, 1)
        card.body.addLayout(grid)
        card.body.addWidget(label("Auslöser 1 = ab 99/100 (auch 100/100 zählt). Bestätigungen = so oft wird der Wert "
                                  "frisch gelesen, bevor der Raid zählt (2 empfohlen).", "small", wrap=True))

        card.body.addWidget(label("Fehlversuche und Neustarts (z. B. nach einer Niederlage) werden automatisch in "
                                  "der Statistik erfasst: Anzahl, Ø Dauer und erreichte Welle.", "small", wrap=True))
        test_row = QHBoxLayout()
        test = QPushButton("Wellenzähler testen")
        test.clicked.connect(self._test_wave)
        test_row.addWidget(test)
        test_row.addStretch(1)
        card.body.addLayout(test_row)
        self.wave_result = label("", "muted", wrap=True)
        self.wave_preview = label("", "preview")
        self.wave_preview.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.wave_preview.setVisible(False)
        card.body.addWidget(self.wave_result)
        card.body.addWidget(self.wave_preview)
        return card

    def _quest_card(self) -> Card:
        card = Card("Quests (Liste oben rechts)")
        self.read_quests = QCheckBox("Quests lesen und melden")
        card.body.addWidget(self.read_quests)
        row = QHBoxLayout()
        self.lbl_quest_roi = label("")
        row.addWidget(self.lbl_quest_roi, 1)
        pick = QPushButton("Bereich auswählen …")
        pick.clicked.connect(lambda: self._pick("quest"))
        reset = QPushButton("Standard")
        reset.clicked.connect(lambda: self._reset("quest"))
        row.addWidget(pick)
        row.addWidget(reset)
        card.body.addLayout(row)
        card.body.addWidget(label("Wähle die ganze Quest-Liste (Titel und Fortschrittsbalken).", "small"))
        test_row = QHBoxLayout()
        test = QPushButton("Quests testen")
        test.clicked.connect(self._test_quests)
        test_row.addWidget(test)
        test_row.addStretch(1)
        card.body.addLayout(test_row)
        self.quest_result = QPlainTextEdit()
        self.quest_result.setReadOnly(True)
        self.quest_result.setMaximumHeight(130)
        self.quest_result.setVisible(False)
        card.body.addWidget(self.quest_result)
        return card

    def _ocr_card(self) -> Card:
        card = Card("Texterkennung (Tesseract)")
        row = QHBoxLayout()
        self.tess = QLineEdit()
        self.tess.setPlaceholderText("Leer = automatisch suchen")
        browse = QPushButton("Durchsuchen …")
        browse.clicked.connect(self._browse_tesseract)
        check = QPushButton("Prüfen")
        check.clicked.connect(self._check_ocr)
        row.addWidget(self.tess, 1)
        row.addWidget(browse)
        row.addWidget(check)
        card.body.addLayout(row)
        self.ocr_result = label("", "muted", wrap=True)
        card.body.addWidget(self.ocr_result)
        self.debug = QCheckBox("Debug-Bilder bei Lesefehlern speichern (max. 40, Ordner siehe Statistik)")
        card.body.addWidget(self.debug)
        return card

    # ------------------------------------------------------------------ Einstellungen
    def load(self, s) -> None:
        self.title.setText(s.window_title)
        self.mode.setCurrentIndex(max(0, self.mode.findData(s.capture_mode)))
        self.wave_roi, self.quest_roi = s.wave_roi, s.quest_roi
        self.totals.setText(s.allowed_totals)
        self.offset.setValue(s.trigger_offset)
        self.confirm.setValue(s.confirm_reads)
        self.cooldown.setValue(s.cooldown_seconds)
        self.read_quests.setChecked(s.read_quests)
        self.tess.setText(s.tesseract_path)
        self.debug.setChecked(s.debug_images)
        self._refresh_labels()

    def apply(self, s) -> None:
        s.window_title = self.title.text().strip() or "Roblox"
        s.capture_mode = self.mode.currentData()
        s.wave_roi, s.quest_roi = self.wave_roi, self.quest_roi
        s.allowed_totals = self.totals.text().strip()
        s.trigger_offset = self.offset.value()
        s.confirm_reads = self.confirm.value()
        s.cooldown_seconds = self.cooldown.value()
        s.read_quests = self.read_quests.isChecked()
        s.tesseract_path = self.tess.text().strip()
        s.debug_images = self.debug.isChecked()

    def refresh(self) -> None:
        pass

    def _refresh_labels(self) -> None:
        for lbl, roi in ((self.lbl_wave_roi, self.wave_roi), (self.lbl_quest_roi, self.quest_roi)):
            lbl.setText(f"Bereich: x {roi.x0:.0%}–{roi.x1:.0%}, y {roi.y0:.0%}–{roi.y1:.0%} des Fensters")

    # ------------------------------------------------------------------ Aktionen
    def _pick(self, which: str) -> None:
        self.main.apply_form()
        try:
            res = self.engine.grab_for_ui(full=True)
        except EngineError as exc:
            QMessageBox.warning(self, "Aufnahme", str(exc))
            return
        if res is None or res.full is None:
            QMessageBox.warning(self, "Aufnahme", "Kein Bild vom Roblox-Fenster erhalten.")
            return
        wave = which == "wave"
        hint = ("Ziehe ein Rechteck um den Wellenzähler („Wave 12/100“) – mit etwas Rand."
                if wave else "Ziehe ein Rechteck um die ganze Quest-Liste (Titel und Fortschrittsbalken).")
        dialog = RegionDialog(self, res.full, "Bereich auswählen", hint,
                              self.wave_roi if wave else self.quest_roi)
        if dialog.exec() and dialog.roi():
            if wave:
                self.wave_roi = dialog.roi()
            else:
                self.quest_roi = dialog.roi()
            self._refresh_labels()

    def _reset(self, which: str) -> None:
        if which == "wave":
            self.wave_roi = Roi(**vars(DEFAULT_WAVE_ROI))
        else:
            self.quest_roi = Roi(**vars(DEFAULT_QUEST_ROI))
        self._refresh_labels()

    def _test_capture(self) -> None:
        self.main.apply_form()
        t0 = time.perf_counter()
        try:
            res = self.engine.grab_for_ui(full=True)
        except EngineError as exc:
            QMessageBox.warning(self, "Capture-Test", str(exc))
            return
        if res is None:
            QMessageBox.warning(self, "Capture-Test", "Kein Bild empfangen (Fenster minimiert?).")
            return
        ms = (time.perf_counter() - t0) * 1000
        QMessageBox.information(self, "Capture-Test",
                                f"Bild empfangen: {res.size[0]} × {res.size[1]} Pixel ({ms:.0f} ms inkl. Start).")

    def _test_wave(self) -> None:
        self.main.apply_form()
        try:
            result = self.engine.test_wave()
        except EngineError as exc:
            QMessageBox.warning(self, "Test", str(exc))
            return
        if not result["ok"]:
            self.wave_result.setText(result["error"])
            return
        reading = result["reading"]
        if reading:
            self.wave_result.setText(f"✅ Gelesen: {reading.value}/{reading.total}  ({result['ms']:.0f} ms)")
        else:
            self.wave_result.setText("❌ Kein Wellenzähler erkannt. Bereich neu wählen oder zuerst einen Raid starten.")
        preview = result["crop"].copy()
        if result.get("box"):
            x0, y0, x1, y1 = result["box"]
            cv2.rectangle(preview, (x0, y0), (x1 - 1, y1 - 1), (80, 214, 61), 2)     # grün = hier wurde der Zähler gefunden
        self.wave_preview.setPixmap(bgr_to_pixmap(preview, 640))
        self.wave_preview.setVisible(True)

    def _test_quests(self) -> None:
        self.main.apply_form()
        try:
            result = self.engine.test_quests()
        except EngineError as exc:
            QMessageBox.warning(self, "Test", str(exc))
            return
        self.quest_result.setVisible(True)
        if not result["ok"]:
            self.quest_result.setPlainText(result["error"])
            return
        tracker = QuestTracker()
        tracker.update(result["lines"])
        lines = [f"• {q['title']}  —  {q['cur'] if q['cur'] is not None else '?'} / {q['total'] or '?'}"
                 for q in tracker.snapshot()]
        self.quest_result.setPlainText(f"{len(lines)} Quests ({result['ms']:.0f} ms)\n" + "\n".join(lines)
                                       if lines else "Keine Quests erkannt. Bereich prüfen.")

    def _browse_tesseract(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "tesseract.exe auswählen", "", "Programm (*.exe);;Alle (*)")
        if path:
            self.tess.setText(path)

    def _check_ocr(self) -> None:
        self.main.apply_form()
        try:
            ocr = self.engine.get_ocr()
        except EngineError as exc:
            self.ocr_result.setText(f"❌ {exc}")
            return
        self.ocr_result.setText(f"✅ Tesseract {ocr.version} gefunden: {ocr.cmd}")
