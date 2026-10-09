"""Pumpkin night surprise: now and then a creepy face peeks up briefly from the bottom edge of the window.
Gentle instead of a full-screen scare: no flash, no sound, at most once an hour, only with the window open, a click
ends it. Can be switched off; skipped with “Reduce animations”."""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import theme

FIRST_MIN, NEXT_MIN, NEXT_MAX = 10 * 60, 60 * 60, 120 * 60     # after 10 min at the earliest, then every 1–2 h
SHOW_MS = 2600                                                  # up, stay briefly, down again


def next_delay(first: bool, rnd: random.Random = random.Random()) -> float:
    return rnd.uniform(FIRST_MIN, FIRST_MIN * 3) if first else rnd.uniform(NEXT_MIN, NEXT_MAX)


def paint_face(p: QPainter, cx: float, top: float, w: float, blink: float = 0.0) -> None:
    """Pale, crooked face with empty eyes and a too wide grin."""
    h = w * 1.25
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    skin = QRadialGradient(cx, top + h * 0.45, w * 0.7)
    skin.setColorAt(0, QColor("#E9E2D0"))
    skin.setColorAt(0.75, QColor("#B9B09A"))
    skin.setColorAt(1, QColor("#6E6656"))
    p.setBrush(skin)
    head = QPainterPath()
    head.addEllipse(QRectF(cx - w / 2, top, w, h))
    p.drawPath(head)
    eye_w, eye_h = w * 0.2, w * 0.26 * (1 - blink)
    for sx, tilt in ((-1, 0.04), (1, -0.02)):                   # slightly crooked = creepier
        ex = cx + sx * w * 0.2
        ey = top + h * (0.36 + tilt)
        hole = QRadialGradient(ex, ey, eye_w)
        hole.setColorAt(0, QColor("#000000"))
        hole.setColorAt(0.7, QColor("#120606"))
        hole.setColorAt(1, QColor(30, 10, 10, 0))
        p.setBrush(hole)
        p.drawEllipse(QRectF(ex - eye_w * 0.75, ey - eye_h * 0.75, eye_w * 1.5, max(1.0, eye_h * 1.5)))
        glint = QColor("#FF3B1F")
        glint.setAlphaF(0.85 * (1 - blink))
        p.setBrush(glint)
        p.drawEllipse(QRectF(ex - w * 0.018, ey - w * 0.018, w * 0.036, w * 0.036))
    mouth = QPainterPath(QPointF(cx - w * 0.34, top + h * 0.62))
    mouth.cubicTo(QPointF(cx - w * 0.15, top + h * 0.86), QPointF(cx + w * 0.18, top + h * 0.86),
                  QPointF(cx + w * 0.36, top + h * 0.6))
    mouth.cubicTo(QPointF(cx + w * 0.16, top + h * 0.72), QPointF(cx - w * 0.16, top + h * 0.73),
                  QPointF(cx - w * 0.34, top + h * 0.62))
    p.setBrush(QColor("#140404"))
    p.drawPath(mouth)
    p.setBrush(QColor("#D8D0B8"))
    for i in range(7):                                            # sharp teeth
        x = cx - w * 0.27 + i * w * 0.09
        y = top + h * (0.665 + 0.012 * math.sin(i))
        tooth = QPainterPath(QPointF(x - w * 0.025, y))
        tooth.lineTo(QPointF(x + w * 0.025, y))
        tooth.lineTo(QPointF(x, y + w * 0.06))
        tooth.closeSubpath()
        p.drawPath(tooth)


class Peek(QWidget):
    """Only as big as the face at the bottom edge (the rest of the window stays usable); deletes itself."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._t = 0.0
        self._w = theme.px(150)
        x = parent.width() * random.uniform(0.2, 0.8)
        self.setGeometry(round(x - self._w / 2), round(parent.height() - self._w * 1.25 * 0.88),
                         round(self._w), round(self._w * 1.25 * 0.88))
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(SHOW_MS)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self.deleteLater)

    def start(self) -> None:
        self.raise_()
        self.show()
        self._anim.start()

    def _step(self, value) -> None:
        self._t = float(value)
        self.update()

    def _rise(self) -> float:
        """0 = hidden, 1 = fully up: quickly up, stay briefly (with a blink), slowly down again."""
        t = self._t
        if t < 0.18:
            return QEasingCurve(QEasingCurve.Type.OutBack).valueForProgress(t / 0.18)
        if t < 0.7:
            return 1.0
        return 1.0 - QEasingCurve(QEasingCurve.Type.InCubic).valueForProgress((t - 0.7) / 0.3)

    def _face_rect(self) -> QRectF:
        h = self._w * 1.25
        return QRectF(0, self.height() - h * 0.88 * self._rise(), self._w, h)

    def mousePressEvent(self, _event) -> None:
        self._anim.stop()
        self.deleteLater()

    def paintEvent(self, _event) -> None:
        r = self._face_rect()
        p = QPainter(self)
        blink = 1.0 if 0.45 < self._t < 0.48 else 0.0
        paint_face(p, r.center().x(), r.top(), r.width(), blink)
        p.end()


class SpookyScheduler:
    """Schedules the surprise: only pumpkin night, window visible and active, setting on, animations on."""

    def __init__(self, window, enabled) -> None:
        self.window = window
        self._enabled = enabled                      # Callable[[], bool] (setting)
        self._due = time.monotonic() + next_delay(first=True)
        self._timer = QTimer(window)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._check)
        self._timer.start()

    def _check(self) -> None:
        w = self.window
        allowed = (self._enabled() and theme.design_info().get("decor") == "halloween" and theme.animations()
                   and w.isVisible() and not w.isMinimized() and w.isActiveWindow())
        if not allowed or time.monotonic() < self._due:
            return
        self._due = time.monotonic() + next_delay(first=False)
        Peek(w).start()
