"""Logo-Animation beim Start: das Logo erscheint kurz in der Mitte und gibt dann das Fenster frei (~1 s)."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from .. import app_paths
from . import theme

DURATION_MS = 1100


class IntroOverlay(QWidget):
    """Liegt über dem ganzen Fenster: Logo wächst sanft und leuchtet auf (erste Hälfte), danach blendet die Ebene aus.
    Klick überspringt. Löscht sich am Ende selbst."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._t = 0.0
        self._logo = QPixmap(str(app_paths.resource_path("assets/app.png")))
        self.setGeometry(parent.rect())
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self.deleteLater)
        parent.installEventFilter(self)

    def start(self) -> None:
        self.raise_()
        self.show()
        self._anim.start()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parent() and event.type() == event.Type.Resize:
            self.setGeometry(self.parent().rect())
        return False

    def mousePressEvent(self, _event) -> None:
        self._anim.stop()
        self.deleteLater()

    def _step(self, value) -> None:
        self._t = float(value)
        self.update()

    def paintEvent(self, _event) -> None:
        t = self._t
        grow = QEasingCurve(QEasingCurve.Type.OutCubic).valueForProgress(min(1.0, t / 0.5))
        fade = 1.0 - QEasingCurve(QEasingCurve.Type.InOutQuad).valueForProgress(max(0.0, (t - 0.55) / 0.45))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(fade)
        bg = QColor(theme.color("bg"))
        p.fillRect(self.rect(), bg)
        size = theme.px(96) * (0.82 + 0.18 * grow)
        cx, cy = self.width() / 2, self.height() / 2 - theme.px(16)
        glow = QColor(theme.color("accent"))                       # weicher Schein hinter dem Logo
        for i, radius in enumerate((2.2, 1.7, 1.3)):
            glow.setAlphaF(0.05 * (i + 1) * grow)
            p.setBrush(glow)
            p.setPen(Qt.PenStyle.NoPen)
            r = size * radius / 2
            p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        p.setOpacity(fade * min(1.0, grow * 1.4))
        if not self._logo.isNull():
            p.drawPixmap(QRectF(cx - size / 2, cy - size / 2, size, size), self._logo, QRectF(self._logo.rect()))
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * 1.25)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 104)
        p.setFont(font)
        p.setPen(QColor(theme.color("text")))
        p.setOpacity(fade * max(0.0, min(1.0, (t - 0.15) / 0.3)))
        p.drawText(QRectF(0, cy + size / 2 + theme.px(14), self.width(), theme.px(30)),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Anime Astral Monitor")
        p.end()
