"""Bereichsauswahl: Rechteck auf einem Bild aufziehen."""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from ..settings import Roi
from .widgets import bgr_to_pixmap


class ImageSelector(QWidget):
    def __init__(self, pixmap: QPixmap, initial: Optional[Roi] = None) -> None:
        super().__init__()
        self._pix = pixmap
        self._start: Optional[tuple[float, float]] = None
        self._sel: Optional[tuple[float, float, float, float]] = None
        if initial is not None and initial.is_valid():
            self._sel = (initial.x0, initial.y0, initial.x1, initial.y1)
        self.setMinimumSize(720, 400)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _target(self) -> QRectF:
        w, h = self.width(), self.height()
        pw, ph = self._pix.width(), self._pix.height()
        scale = min(w / pw, h / ph)
        tw, th = pw * scale, ph * scale
        return QRectF((w - tw) / 2, (h - th) / 2, tw, th)

    def _frac(self, pos: QPointF) -> tuple[float, float]:
        t = self._target()
        x = (pos.x() - t.x()) / t.width()
        y = (pos.y() - t.y()) / t.height()
        return min(1.0, max(0.0, x)), min(1.0, max(0.0, y))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0B0F14"))
        t = self._target()
        p.drawPixmap(t.toRect(), self._pix)
        if self._sel:
            x0, y0, x1, y1 = self._sel
            rect = QRectF(t.x() + x0 * t.width(), t.y() + y0 * t.height(),
                          (x1 - x0) * t.width(), (y1 - y0) * t.height())
            p.setPen(QPen(QColor("#FF3B30"), 2))
            p.setBrush(QColor(255, 59, 48, 50))
            p.drawRect(rect)
        p.end()

    def mousePressEvent(self, event) -> None:
        self._start = self._frac(event.position())
        self._sel = (*self._start, *self._start)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._start:
            x, y = self._frac(event.position())
            sx, sy = self._start
            self._sel = (min(sx, x), min(sy, y), max(sx, x), max(sy, y))
            self.update()

    def mouseReleaseEvent(self, _event) -> None:
        self._start = None

    def selection(self) -> Optional[Roi]:
        if not self._sel:
            return None
        x0, y0, x1, y1 = self._sel
        if x1 - x0 < 0.004 or y1 - y0 < 0.004:
            return None
        return Roi(x0, y0, x1, y1)


class RegionDialog(QDialog):
    def __init__(self, parent, image_bgr: np.ndarray, title: str, hint: str,
                 initial: Optional[Roi] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1100, 680)
        lay = QVBoxLayout(self)
        info = QLabel(hint)
        info.setWordWrap(True)
        lay.addWidget(info)
        self.selector = ImageSelector(bgr_to_pixmap(image_bgr), initial)
        lay.addWidget(self.selector, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def roi(self) -> Optional[Roi]:
        return self.selector.selection()
