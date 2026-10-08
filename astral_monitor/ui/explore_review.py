"""Rückfrage nach dem Erkunden: Fund für Fund zeigen, was das Fenster liefert (Bild, Art, Reiter, scrollbare Bereiche,
Knöpfe, Text) – der Nutzer bestätigt, korrigiert die Art oder setzt „nochmal prüfen“ (review.py)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QTextEdit, QVBoxLayout)

from .. import app_paths, review
from ..i18n import tr
from ..knowledge import CATEGORIES
from . import theme
from .widgets import label


class ReviewDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Erkunden: Funde prüfen"))
        self.data_dir = app_paths.data_dir()
        theme.track(self, lambda o, f: o.resize(round(900 * f), round(560 * f)))
        root = QHBoxLayout(self)
        self.list = QListWidget()
        theme.track_fixed_width(self.list, 240)
        self.list.currentRowChanged.connect(self._show)
        root.addWidget(self.list)
        right = QVBoxLayout()
        self.title = label("", "h2")
        right.addWidget(self.title)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.track_min_height(self.image, 200)
        right.addWidget(self.image, 1)
        cat_row = QHBoxLayout()
        cat_row.addWidget(label(tr("Art:")))
        self.category = QComboBox()
        for key, (text, _t, _w) in CATEGORIES.items():
            self.category.addItem(tr(text), key)
        self.category.addItem(tr("Unbekannt"), "unknown")
        cat_row.addWidget(self.category, 1)
        right.addLayout(cat_row)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        theme.track_min_height(self.info, 140)
        right.addWidget(self.info, 1)
        buttons = QHBoxLayout()
        ok = QPushButton(tr("Stimmt ✓"))
        ok.setObjectName("primary")
        ok.clicked.connect(lambda: self._decide(review.OK))
        again = QPushButton(tr("Nochmal prüfen"))
        again.setToolTip(tr("Beim nächsten Erkunden wird dieses Fenster erneut gründlich gescannt."))
        again.clicked.connect(lambda: self._decide(review.RECHECK))
        later = QPushButton(tr("Später"))
        later.clicked.connect(self._next)
        for b in (ok, again, later):
            buttons.addWidget(b)
        buttons.addStretch(1)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        right.addLayout(buttons)
        root.addLayout(right, 1)
        self._fill()

    def _fill(self) -> None:
        self.items = review.pending(self.data_dir)
        self.list.clear()
        for name, entry in self.items:
            self.list.addItem(QListWidgetItem(f"{name}  ·  {entry.get('label') or entry.get('category', '')}"))
        if self.items:
            self.list.setCurrentRow(0)
        else:
            self.title.setText(tr("Alles geprüft ✓"))
            self.info.clear()
            self.image.clear()

    def _show(self, row: int) -> None:
        if not 0 <= row < len(self.items):
            return
        name, entry = self.items[row]
        self.title.setText(name + (f"  ({entry['title']})" if entry.get("title") and entry["title"] != name else ""))
        pix = QPixmap(entry.get("image", "")) if entry.get("image") and Path(entry["image"]).is_file() else QPixmap()
        if not pix.isNull():
            self.image.setPixmap(pix.scaled(self.image.width(), max(160, self.image.height()),
                                            Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        else:
            self.image.setText(tr("Kein Bild"))
        self.category.setCurrentIndex(max(0, self.category.findData(entry.get("category", "unknown"))))
        text = review.summary(entry)
        lines = entry.get("lines") or []
        if lines:
            text += "\n\n" + tr("Gelesen:") + "\n" + "\n".join(lines)
        self.info.setPlainText(text)

    def _decide(self, status: str) -> None:
        row = self.list.currentRow()
        if not 0 <= row < len(self.items):
            return
        name, _entry = self.items[row]
        review.set_status(self.data_dir, name, status, self.category.currentData())
        self._fill()
        if self.items:
            self.list.setCurrentRow(min(row, len(self.items) - 1))

    def _next(self) -> None:
        row = self.list.currentRow()
        if row + 1 < self.list.count():
            self.list.setCurrentRow(row + 1)
