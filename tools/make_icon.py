"""Programmsymbol erzeugen: assets/app.ico (16–256 px) und assets/app.png.

Logo „Monogramm A“ (seit 0.6.6): Verlaufs-„A“ (Türkis → Violett, Design „Astral“) mit Umlaufbahn und Stern auf dunkler
Kachel. Jede Größe wird einzeln gezeichnet – kleine Größen ohne Schein und Stern, mit dickeren Linien, damit das „A“
in Taskleiste und Tray scharf bleibt.

    python tools/make_icon.py
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath,  # noqa: E402
                           QPen, QRadialGradient)

ROOT = Path(__file__).resolve().parent.parent
TEAL, VIOLET = QColor("#45E0BF"), QColor("#7B8CFF")
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _star(cx: float, cy: float, r_out: float, r_in: float) -> QPainterPath:
    path = QPainterPath()
    for i in range(8):
        r = r_out if i % 2 == 0 else r_in
        a = -math.pi / 2 + i * math.pi / 4
        pt = QPointF(cx + r * math.cos(a), cy + r * math.sin(a))
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


def render(size: int) -> QImage:
    """Logo in genau dieser Größe (gezeichnet im 256er-Raster, skaliert)."""
    small = size <= 32
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 256, size / 256)
    # Kachel
    bg = QLinearGradient(0, 0, 256, 256)
    bg.setColorAt(0, QColor("#161D2C"))
    bg.setColorAt(1, QColor("#0A0D13"))
    p.setPen(QPen(QColor("#2A3448"), 0 if small else 3))
    p.setBrush(bg)
    inset = 2 if small else 6
    p.drawRoundedRect(QRectF(inset, inset, 256 - 2 * inset, 256 - 2 * inset), 58, 58)
    if not small:                                           # weicher Schein hinter dem A
        glow = QRadialGradient(128, 144, 104)
        c0, c1 = QColor(VIOLET), QColor(VIOLET)
        c0.setAlpha(80)
        c1.setAlpha(0)
        glow.setColorAt(0, c0)
        glow.setColorAt(1, c1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(128, 144), 104, 104)
    # „A“
    grad = QLinearGradient(60, 40, 200, 220)
    grad.setColorAt(0, TEAL)
    grad.setColorAt(1, VIOLET)
    width = 38 if small else 26
    pen = QPen(grad, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    a = QPainterPath(QPointF(64, 208))
    a.lineTo(QPointF(128, 50 if not small else 56))
    a.lineTo(QPointF(192, 208))
    p.drawPath(a)
    # Umlaufbahn (bildet den Querstrich)
    p.setPen(QPen(QColor("#FFFFFF"), 16 if small else 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.save()
    p.translate(128, 156)
    p.rotate(-12)
    p.drawArc(QRectF(-104, -26, 208, 52), 200 * 16, 300 * 16)
    p.restore()
    if not small:                                           # Stern an der Spitze
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawPath(_star(128, 50, 20, 5))
    p.end()
    return img


def _to_pil(img: QImage):
    from PIL import Image
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    import io
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def main() -> int:
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    images = {size: _to_pil(render(size)) for size in SIZES}
    assets = ROOT / "assets"
    images[256].save(assets / "app.png")
    images[256].save(assets / "app.ico", sizes=[(s, s) for s in SIZES],
                     append_images=[images[s] for s in SIZES if s != 256])
    print("assets/app.ico und assets/app.png geschrieben:", ", ".join(f"{s}px" for s in SIZES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
