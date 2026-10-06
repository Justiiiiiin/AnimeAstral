"""Statistik-Karte als Bild (PNG, 1200×630) zum Teilen – gezeichnet mit Pillow, ohne Qt."""
from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import app_paths, messages
from .i18n import dec, tr
from .stats import StatsStore

W, H, S = 1200, 630, 2           # Zielgröße und Supersampling (Kanten glätten)
BG_TOP, BG_BOTTOM = (13, 18, 24), (18, 26, 35)
CARD, CARD_LINE = (22, 30, 40), (36, 46, 58)
TEXT, MUTED, DIM = (236, 241, 247), (139, 151, 168), (84, 96, 112)
TEAL, AMBER, RED = (61, 214, 181), (245, 165, 36), (255, 122, 122)


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    names = (["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"])
    folders = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    candidates = [str(f / n) for f in folders for n in names]
    candidates += ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
                   else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size * S)
        except OSError:
            continue
    return ImageFont.load_default()


class _Canvas:
    def __init__(self) -> None:
        base = Image.new("RGB", (W * S, H * S), BG_TOP)
        top = Image.new("RGB", (1, 2), BG_TOP)
        top.putpixel((0, 1), BG_BOTTOM)
        base = top.resize((W * S, H * S), Image.BILINEAR).convert("RGBA")     # Verlauf
        glow = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((W * S * 0.70, -H * S * 0.30, W * S * 1.05, H * S * 0.28),
                                     fill=(61, 214, 181, 70))
        base = Image.alpha_composite(base, glow.filter(ImageFilter.GaussianBlur(70 * S)))
        self.img = base.convert("RGB")
        self.d = ImageDraw.Draw(self.img, "RGBA")

    def text(self, xy, text, size, fill=TEXT, bold=False, anchor="la", spacing: float = 0.0) -> None:
        font = _font(bold, size)
        x, y = xy[0] * S, xy[1] * S
        if spacing:
            for ch in text:                                           # Buchstabenabstand
                self.d.text((x, y), ch, font=font, fill=fill, anchor=anchor)
                x += self.d.textlength(ch, font=font) + spacing * S
            return
        self.d.text((x, y), text, font=font, fill=fill, anchor=anchor)

    def box(self, rect, radius=16, fill=CARD, line=CARD_LINE) -> None:
        x0, y0, x1, y1 = (v * S for v in rect)
        self.d.rounded_rectangle((x0, y0, x1, y1), radius=radius * S, fill=fill, outline=line, width=S)

    def bar(self, rect, fill, radius=4) -> None:
        x0, y0, x1, y1 = (v * S for v in rect)
        self.d.rounded_rectangle((x0, y0, x1, max(y1, y0 + 1)), radius=radius * S, fill=fill)

    def png(self) -> bytes:
        out = self.img.resize((W, H), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def _pct(v: Optional[float]) -> str:
    return "–" if v is None else f"{v * 100:.0f} %"


def render_card(stats: StatsStore, since: Optional[float], raid: Optional[str], title: str) -> bytes:
    summary = stats.summary(since, raid)
    recs = stats.last_runs(100000, since, raid)
    c = _Canvas()

    # ---- Kopf
    logo_path = app_paths.resource_path("assets/app.png")
    if logo_path.is_file():
        logo = Image.open(logo_path).convert("RGBA").resize((56 * S, 56 * S), Image.LANCZOS)
        c.img.paste(logo, (48 * S, 36 * S), logo)
    c.text((120, 38), "ANIME ASTRAL MONITOR", 14, TEAL, bold=True, spacing=2.2)
    c.text((120, 58), title + (f" · {raid}" if raid else ""), 32, TEXT, bold=True)
    if recs:
        first, last = datetime.fromtimestamp(recs[-1].ts_end), datetime.fromtimestamp(recs[0].ts_end)
        span = (last - first).total_seconds()
        c.text((W - 48, 44), f"{first:%d.%m.%Y} · {first:%H:%M}–{last:%H:%M}", 17, MUTED, anchor="ra")
        mins = int(span // 60)
        c.text((W - 48, 70), tr("{h} Std. {m} Min.", h=mins // 60, m=mins % 60) if mins >= 60 else tr("{minutes} Min.", minutes=mins), 15, DIM, anchor="ra")

    if not recs:
        c.box((48, 130, W - 48, 560))
        c.text((W // 2, 345), tr("Noch keine Versuche im gewählten Zeitraum"), 26, MUTED, anchor="mm")
        return c.png()

    # ---- Kennzahlen-Kacheln (3 × 2)
    tiles = [
        (tr("Versuche"), messages.fmt_int(summary.attempts), TEAL),
        (tr("Wellen gesamt"), messages.fmt_int(summary.waves_total), TEAL),
        (tr("Wellen pro Stunde"), f"{summary.waves_per_hour:.0f}" if summary.waves_per_hour else "–", TEXT),
        (tr("Bestwelle"), str(summary.best_wave), AMBER),
        (tr("Ø Endwelle"), dec(f"{summary.avg_wave_all:.1f}") if summary.avg_wave_all else "–", TEXT),
        (tr("Ø Dauer pro Versuch"), messages.fmt_duration(summary.avg_duration_all), TEXT),
    ]
    tw, th, gap, x0, y0 = 184, 108, 14, 48, 120
    for i, (label, value, color) in enumerate(tiles):
        x, y = x0 + (i % 3) * (tw + gap), y0 + (i // 3) * (th + gap)
        c.box((x, y, x + tw, y + th))
        c.text((x + 18, y + 16), label, 14, MUTED)
        c.text((x + 18, y + 40), value, 38, color, bold=True)

    # ---- Diagramm rechts: Endwellen-Verteilung (sonst Raids pro Stunde)
    px0, py0, px1, py1 = 640, 120, W - 48, 350
    c.box((px0, py0, px1, py1))
    hist = stats.wave_histogram(since, raid)
    if hist:
        c.text((px0 + 20, py0 + 16), tr("Wo enden die Versuche?"), 17, TEXT, bold=True)
        c.text((px0 + 20, py0 + 40), tr("Anzahl Versuche je Endwelle"), 13, MUTED)
        data = [(a, b) for a, b in hist]
    else:
        data = [(f"{h:02d}", n) for h, n in stats.hourly_waves(10, raid)]
        c.text((px0 + 20, py0 + 16), tr("Wellen pro Stunde"), 17, TEXT, bold=True)
        c.text((px0 + 20, py0 + 40), tr("Geschaffte Wellen, letzte 10 Stunden"), 13, MUTED)
    cx0, cx1, cy0, cy1 = px0 + 24, px1 - 24, py0 + 78, py1 - 34
    n = max(1, len(data))
    slot = (cx1 - cx0) / n
    top = max((v for _l, v in data), default=1) or 1
    peak = max(range(len(data)), key=lambda i: data[i][1]) if data else 0
    for i, (label, value) in enumerate(data):
        bx = cx0 + i * slot + slot * 0.16
        bw = slot * 0.68
        bh = (cy1 - cy0) * value / top
        c.bar((bx, cy1 - bh, bx + bw, cy1), TEAL if i == peak else (44, 112, 100))
        if n <= 14 or i % 2 == 0:
            c.text((bx + bw / 2, cy1 + 8), label, 12, MUTED, anchor="ma")
        if value and n <= 16:
            c.text((bx + bw / 2, cy1 - bh - 18), str(value), 12, TEXT if i == peak else MUTED, anchor="ma")

    # ---- Profile unten
    per = stats.per_raid(since) if raid is None else [p for p in stats.per_raid(since) if p["raid"] == raid]
    rows = max(1, min(3, len(per)))
    c.box((48, 366, W - 48, 366 + 64 + rows * 52 + 4))
    c.text((70, 382), tr("Profile") if raid is None else tr("Profil"), 17, TEXT, bold=True)
    total = max((r.total_waves for r in recs), default=100) or 100
    for i, p in enumerate(per[:3]):
        y = 420 + i * 52
        c.text((70, y), p["raid"], 18, TEXT, bold=True)
        sub = tr("{attempts} Versuche · {waves} Wellen · Ø Welle {avg}", attempts=p["attempts"],
                 waves=messages.fmt_int(p["waves_total"]), avg=dec(f"{p['avg_wave']:.1f}"))
        c.text((70, y + 24), sub, 13, MUTED)
        bx0, bx1 = 560, W - 230
        c.bar((bx0, y + 12, bx1, y + 24), (30, 40, 52), radius=6)
        c.bar((bx0, y + 12, bx0 + (bx1 - bx0) * min(1.0, p["best_wave"] / total), y + 24), TEAL, radius=6)
        c.text((W - 70, y + 4), tr("Bestwelle {wave}", wave=p["best_wave"]), 15, TEAL, bold=True, anchor="ra")
    if not per:
        c.text((70, 430), tr("Noch keine Profile erkannt – lege unter „Raids“ Referenzbilder an."), 15, MUTED)
    c.text((W // 2, H - 22), tr("Erstellt mit Anime Astral Monitor"), 12, DIM, anchor="mm")
    return c.png()
