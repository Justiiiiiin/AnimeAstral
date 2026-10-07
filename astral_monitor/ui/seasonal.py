"""Saison-Deko hinter den Seiten: Kürbisse und fallende Herbstblätter (Kürbisnacht), Schneeflocken (Frost).
Bewegt sich nur, solange das Fenster sichtbar ist und Animationen an sind – sonst steht alles still."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from . import theme

LEAF_COLORS = ("#E8742A", "#C9502A", "#E3A23B", "#9C4A26", "#D9622E")
FPS = 15                              # ruhig und sparsam (gemessen: 0,7–2,6 ms je Bild)


@dataclass
class Flake:
    x: float                          # 0–1 relativ zur Breite
    y: float                          # 0–1 relativ zur Höhe
    size: float
    speed: float                      # Höhe je Sekunde (relativ)
    sway: float                       # Ausschlag seitlich
    phase: float
    spin: float
    color: str


def make_particles(kind: str, count: int, seed: int = 7) -> list[Flake]:
    rnd = random.Random(seed)
    out = []
    for _ in range(count):
        if kind == "halloween":
            out.append(Flake(rnd.random(), rnd.random(), rnd.uniform(14, 24), rnd.uniform(0.025, 0.05),
                             rnd.uniform(0.01, 0.03), rnd.uniform(0, 6.28), rnd.uniform(-1.2, 1.2),
                             rnd.choice(LEAF_COLORS)))
        else:
            out.append(Flake(rnd.random(), rnd.random(), rnd.uniform(3, 7), rnd.uniform(0.02, 0.045),
                             rnd.uniform(0.005, 0.02), rnd.uniform(0, 6.28), rnd.uniform(-0.6, 0.6), "#FFFFFF"))
    return out


def step(particles: list[Flake], t: float, dt: float) -> None:
    """Teilchen weiterbewegen (oben wieder herein, wenn sie unten heraus sind)."""
    for f in particles:
        f.y += f.speed * dt
        if f.y > 1.05:
            f.y -= 1.1
        f.phase += dt


def _leaf(p: QPainter, cx: float, cy: float, size: float, angle: float, color: str) -> None:
    p.save()
    p.translate(cx, cy)
    p.rotate(math.degrees(angle))
    path = QPainterPath(QPointF(0, -size / 2))
    path.cubicTo(QPointF(size * 0.45, -size * 0.3), QPointF(size * 0.4, size * 0.3), QPointF(0, size / 2))
    path.cubicTo(QPointF(-size * 0.4, size * 0.3), QPointF(-size * 0.45, -size * 0.3), QPointF(0, -size / 2))
    c = QColor(color)
    c.setAlphaF(0.55)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPath(path)
    vein = QColor(color).darker(140)
    vein.setAlphaF(0.5)
    p.setPen(QPen(vein, max(1.0, size / 14)))
    p.drawLine(QPointF(0, -size / 2), QPointF(0, size / 2 + size * 0.15))
    p.restore()


def _flake(p: QPainter, cx: float, cy: float, size: float, angle: float) -> None:
    c = QColor("#FFFFFF")
    c.setAlphaF(0.45 if theme.is_dark() else 0.0)
    if not theme.is_dark():
        c = QColor(theme.color("accent"))
        c.setAlphaF(0.35)
    p.setPen(QPen(c, max(1.0, size / 5), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i in range(3):
        a = angle + i * math.pi / 3
        dx, dy = math.cos(a) * size, math.sin(a) * size
        p.drawLine(QPointF(cx - dx, cy - dy), QPointF(cx + dx, cy + dy))


def _pumpkin(p: QPainter, cx: float, bottom: float, w: float, alpha: float = 0.75) -> None:
    h = w * 0.78
    body = QRectF(cx - w / 2, bottom - h, w, h)
    orange = QColor("#E8742A")
    orange.setAlphaF(alpha)
    rib = QColor("#B4501C")
    rib.setAlphaF(alpha)
    p.setPen(Qt.PenStyle.NoPen)
    for frac, shade in ((0.0, rib), (0.18, orange), (-0.18, orange)):
        p.setBrush(shade if frac else orange)
        p.drawEllipse(QRectF(body.x() + w * (0.22 + frac), body.y(), w * 0.56, h))
    p.setBrush(orange)
    p.drawEllipse(QRectF(body.x() + w * 0.08, body.y() + h * 0.02, w * 0.5, h * 0.96))
    p.drawEllipse(QRectF(body.x() + w * 0.42, body.y() + h * 0.02, w * 0.5, h * 0.96))
    stem = QColor("#5E7B33")
    stem.setAlphaF(0.85)
    p.setBrush(stem)
    p.drawRoundedRect(QRectF(cx - w * 0.06, body.y() - h * 0.18, w * 0.12, h * 0.24), w * 0.03, w * 0.03)
    face = QColor("#2A1206")
    face.setAlphaF(0.55)
    p.setBrush(face)
    eye = w * 0.12
    for sx in (-1, 1):                                   # dreieckige Augen
        tri = QPainterPath(QPointF(cx + sx * w * 0.2, body.y() + h * 0.32))
        tri.lineTo(QPointF(cx + sx * w * 0.2 - eye / 2, body.y() + h * 0.32 + eye))
        tri.lineTo(QPointF(cx + sx * w * 0.2 + eye / 2, body.y() + h * 0.32 + eye))
        tri.closeSubpath()
        p.drawPath(tri)
    mouth = QPainterPath(QPointF(cx - w * 0.25, body.y() + h * 0.62))
    mouth.quadTo(QPointF(cx, body.y() + h * 0.86), QPointF(cx + w * 0.25, body.y() + h * 0.62))
    mouth.quadTo(QPointF(cx, body.y() + h * 0.74), QPointF(cx - w * 0.25, body.y() + h * 0.62))
    p.drawPath(mouth)


def pumpkin_pixmap(size: int):
    """Kleiner Kürbis als Bild (Seitenleiste in „Kürbisnacht“)."""
    from PySide6.QtGui import QPixmap
    ratio = 2.0
    pix = QPixmap(int(size * ratio), int(size * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _pumpkin(p, size / 2, size * 0.95, size * 0.9, alpha=1.0)
    p.end()
    return pix


def paint(p: QPainter, kind: str, rect: QRectF, particles: list[Flake]) -> None:
    w, h = rect.width(), rect.height()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for f in particles:
        x = rect.x() + (f.x + math.sin(f.phase * 0.9) * f.sway) * w
        y = rect.y() + f.y * h
        size = theme.px(f.size)
        if kind == "halloween":
            _leaf(p, x, y, size, f.phase * f.spin, f.color)
        else:
            _flake(p, x, y, size, f.phase * f.spin)
    if kind == "halloween":                               # Kürbisse in den unteren Ecken
        base = rect.bottom() - theme.px(10)
        _pumpkin(p, rect.right() - theme.px(70), base, theme.px(64))
        _pumpkin(p, rect.right() - theme.px(128), base, theme.px(42))
        _pumpkin(p, rect.left() + theme.px(60), base, theme.px(48))
