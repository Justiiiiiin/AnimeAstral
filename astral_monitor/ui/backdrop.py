"""Eigenes Hintergrundbild hinter den Seiten: füllend skaliert, mit der Hintergrundfarbe des Designs abgedunkelt.
Karten bleiben deckend, nur die Flächen dazwischen werden durchsichtig (theme: Eigenschaft „glass“)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractScrollArea, QCheckBox, QLabel, QRadioButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import app_paths
from . import theme

GLASS_TYPES = (QWidget, QStackedWidget, QLabel, QCheckBox, QRadioButton)
MAX_SIDE = 2560                                   # größere Bilder werden beim Laden verkleinert (spart Speicher)


def stored_path(name: str) -> Optional[Path]:
    path = app_paths.data_dir() / name if name else None
    return path if path and path.is_file() else None


def import_image(source: str) -> str:
    """Bild in den Datenordner kopieren (bleibt auch, wenn das Original gelöscht wird). Gibt den Dateinamen zurück."""
    reader = QImageReader(source)
    if not reader.canRead():
        raise ValueError(reader.errorString())
    suffix = Path(source).suffix.lower() or ".png"
    for old in app_paths.data_dir().glob("background.*"):
        old.unlink(missing_ok=True)
    name = "background" + suffix
    shutil.copyfile(source, app_paths.data_dir() / name)
    return name


def mark_glass(root: QWidget) -> None:
    """Reine Container-Flächen (keine Karten, Felder, Knöpfe) als „glass“ markieren."""
    for w in [root] + root.findChildren(QWidget):
        if type(w) in GLASS_TYPES or isinstance(w, QAbstractScrollArea) or w.property("page"):
            w.setProperty("glass", True)
        if isinstance(w, QAbstractScrollArea):
            w.viewport().setProperty("glass", True)


class Backdrop(QWidget):
    def __init__(self, content: QWidget) -> None:
        super().__init__()
        self.setProperty("glass", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(content)
        self._pixmap: Optional[QPixmap] = None
        self._dim = 0.7

    def set_image(self, name: str, dim_percent: int) -> None:
        path = stored_path(name)
        self._pixmap = None
        if path:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > MAX_SIDE:
                reader.setScaledSize(size.scaled(MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
            if not image.isNull():
                self._pixmap = QPixmap.fromImage(image)
        self._dim = max(0, min(95, dim_percent)) / 100
        theme.set_backdrop(self._pixmap is not None)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        bg = QColor(theme.color("bg"))
        if self._pixmap is None:
            p.fillRect(self.rect(), bg)
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        src = QRectF(self._pixmap.rect())
        scale = max(self.width() / src.width(), self.height() / src.height())     # füllen, mittig zuschneiden
        w, h = self.width() / scale, self.height() / scale
        p.drawPixmap(QRectF(self.rect()), self._pixmap, QRectF((src.width() - w) / 2, (src.height() - h) / 2, w, h))
        bg.setAlphaF(self._dim)
        p.fillRect(self.rect(), bg)
        p.end()
