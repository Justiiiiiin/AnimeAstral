"""Wiederverwendbare Bausteine."""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTextOption
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)


def bgr_to_pixmap(bgr: np.ndarray, max_width: Optional[int] = None) -> QPixmap:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    pix = QPixmap.fromImage(image)
    if max_width and pix.width() > max_width:
        pix = pix.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
    return pix


class _NoWheelMixin:
    """Das Mausrad ändert den Wert nur bei fokussiertem Feld; sonst scrollt die Seite weiter."""

    def _init_nowheel(self) -> None:
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class SpinBox(_NoWheelMixin, QSpinBox):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._init_nowheel()


class DoubleSpinBox(_NoWheelMixin, QDoubleSpinBox):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._init_nowheel()


class ComboBox(_NoWheelMixin, QComboBox):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._init_nowheel()


def smooth(view: QAbstractItemView) -> None:
    """Pixelweises, ruhiges Scrollen statt sprunghaftem Zeilen-Scrollen."""
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.verticalScrollBar().setSingleStep(16)


def scroll_page(page: QWidget) -> QScrollArea:
    """Verpackt eine Seite: bei kleinem Fenster wird gescrollt, statt dass Elemente überlappen."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.verticalScrollBar().setSingleStep(24)
    area.setWidget(page)
    return area


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


class Card(QFrame):
    def __init__(self, title: str = "") -> None:
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(10)
        if title:
            self.body.addWidget(label(title, "h2"))


class StatCard(Card):
    def __init__(self, title: str, value: str = "–") -> None:
        super().__init__()
        self.body.setSpacing(2)
        self.title_label = label(title, "small")
        self.body.addWidget(self.title_label)
        self.value = label(value, "kpi")
        self.body.addWidget(self.value)

    def set_title(self, text: str) -> None:
        if self.title_label.text() != text:
            self.title_label.setText(text)

    def set_value(self, text: str) -> None:
        if self.value.text() != text:
            self.value.setText(text)


class QuestRow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(4)
        top = QHBoxLayout()
        self.title = QLabel("")
        self.value = QLabel("")
        self.value.setObjectName("muted")
        top.addWidget(self.title, 1)
        top.addWidget(self.value)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        lay.addLayout(top)
        lay.addWidget(self.bar)

    def set_quest(self, q: dict) -> None:
        cur = "?" if q["cur"] is None else f"{q['cur']:,}".replace(",", ".")
        tot = "?" if not q["total"] else f"{q['total']:,}".replace(",", ".")
        self.title.setText(q["title"])
        self.value.setText(f"{cur} / {tot}")
        self.bar.setValue(q["percent"] or 0)


class BarChart(QWidget):
    """Einfaches Balkendiagramm ohne Zusatzbibliothek."""

    def __init__(self) -> None:
        super().__init__()
        self._data: list[tuple[str, int]] = []
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: list[tuple[str, int]]) -> None:
        self._data = data
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._data)
        top_pad, bottom_pad, gap = 22, 22, 8
        bw = (w - gap * (n - 1)) / n
        max_v = max(1, max(v for _, v in self._data))
        for i, (name, value) in enumerate(self._data):
            x = i * (bw + gap)
            bh = (h - top_pad - bottom_pad) * value / max_v
            rect = QRectF(x, h - bottom_pad - bh, bw, max(bh, 1))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3DD6B5" if i == n - 1 else "#2B6B60"))
            p.drawRoundedRect(rect, 3, 3)
            p.setPen(QColor("#8B97A8"))
            center = QTextOption(Qt.AlignmentFlag.AlignCenter)
            p.drawText(QRectF(x, h - bottom_pad + 4, bw, 16), name, center)
            p.drawText(QRectF(x, h - bottom_pad - bh - 18, bw, 16), str(value), center)
        p.end()
