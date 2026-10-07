"""Eigenes Hintergrundbild hinter den Seiten: füllend skaliert, mit der Hintergrundfarbe des Designs abgedunkelt.
Karten bleiben deckend, nur die Flächen dazwischen werden durchsichtig (theme: Eigenschaft „glass“)."""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImageReader, QPainter, QPixmap, QRegion
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
        self._decor = ""                            # Saison-Deko des Designs („halloween“, „winter“)
        self._particles: list = []
        self._last = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)   # gleichmäßige Abstände = ruhigere Bewegung
        self._timer.timeout.connect(self._tick)

    def refresh_decor(self) -> None:
        """Nach Design-/Animationswechsel: Deko des aktiven Designs übernehmen, Bewegung an/aus."""
        from . import seasonal
        decor = theme.design_info().get("decor", "")
        if decor != self._decor:
            self._decor = decor
            self._particles = seasonal.make_particles(decor, seasonal.COUNTS.get(decor, 30)) if decor else []
        theme.set_backdrop(self._pixmap is not None or bool(self._decor))
        self._sync_timer()
        self.update()

    def _sync_timer(self) -> None:
        from . import seasonal
        run = bool(self._decor) and theme.animations() and self.isVisible() and not self.window().isMinimized()
        if run and not self._timer.isActive():
            self._last = time.monotonic()
            self._timer.start(1000 // seasonal.FPS)
        elif not run:
            self._timer.stop()

    def _tick(self) -> None:
        from . import seasonal
        if not self.isVisible() or self.window().isMinimized():
            self._timer.stop()
            return
        now = time.monotonic()
        area = QRectF(self.rect())
        before = seasonal.bounds(self._decor, area, self._particles)
        seasonal.step(self._particles, now, min(0.2, now - self._last))
        self._last = now
        # Nur die Stellen neu zeichnen, an denen ein Teilchen war oder jetzt ist – nicht das ganze Fenster mit allen
        # Karten (gemessen: das war der Großteil der Rechenzeit)
        region = QRegion()
        for r in before + seasonal.bounds(self._decor, area, self._particles):
            region += r.toAlignedRect()
        self.update(region)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

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
        theme.set_backdrop(self._pixmap is not None or bool(self._decor))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        bg = QColor(theme.color("bg"))
        if self._pixmap is None:
            p.fillRect(self.rect(), bg)
            self._paint_decor(p)
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        src = QRectF(self._pixmap.rect())
        scale = max(self.width() / src.width(), self.height() / src.height())     # füllen, mittig zuschneiden
        w, h = self.width() / scale, self.height() / scale
        p.drawPixmap(QRectF(self.rect()), self._pixmap, QRectF((src.width() - w) / 2, (src.height() - h) / 2, w, h))
        bg.setAlphaF(self._dim)
        p.fillRect(self.rect(), bg)
        self._paint_decor(p)
        p.end()

    def _paint_decor(self, p: QPainter) -> None:
        if self._decor:
            from . import seasonal
            seasonal.paint(p, self._decor, QRectF(self.rect()), self._particles)


def accent_from_image(path) -> Optional[str]:
    """Kräftigste wiederkehrende Farbe eines Bildes als Akzent (Farbton mit dem meisten satten, hellen Anteil),
    auf gut lesbare Helligkeit gebracht. None = Bild ohne kräftige Farben (z. B. schwarz-weiß)."""
    from PySide6.QtGui import QImage
    image = QImage(str(path))
    if image.isNull():
        return None
    small = image.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    bins: dict = {}
    for y in range(small.height()):
        for x in range(small.width()):
            h, s, v, _a = small.pixelColor(x, y).getHsvF()
            if h < 0 or s < 0.35 or v < 0.35:
                continue                              # graue, blasse und dunkle Stellen zählen nicht
            b = int(h * 36) % 36
            weight = s * v
            acc = bins.setdefault(b, [0.0, 0.0, 0.0, 0.0])
            acc[0] += weight
            acc[1] += h * weight
            acc[2] += s * weight
            acc[3] += v * weight
    if not bins:
        return None
    total, hs, ss, vs = max(bins.values(), key=lambda a: a[0])
    if total < 4:                                     # zu wenig Farbe im Bild
        return None
    color = QColor.fromHsvF(hs / total, min(0.85, max(0.55, ss / total)), max(0.85, vs / total))
    return color.name().upper()
