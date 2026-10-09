"""Statistics card as an image (PNG, 1200×630) for sharing – drawn with Pillow, without Qt."""
from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import app_paths, messages
from .i18n import N_, dec, tr
from .stats import UNKNOWN, StatsStore, raid_label

W, H, S = 1200, 630, 2           # target size and supersampling (smooth edges)
BG_TOP, BG_BOTTOM = (13, 18, 24), (18, 26, 35)
CARD, CARD_LINE = (22, 30, 40), (36, 46, 58)
TEXT, MUTED, DIM = (236, 241, 247), (139, 151, 168), (84, 96, 112)
TEAL, AMBER = (61, 214, 181), (245, 165, 36)


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
        base = top.resize((W * S, H * S), Image.BILINEAR).convert("RGBA")     # gradient
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
            for ch in text:                                           # letter spacing
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


def _profile(c: _Canvas) -> int:
    """Own Roblox profile at the top right (avatar + name). Returns the right edge for further header texts."""
    from . import roblox_profile
    info = roblox_profile.load_info()
    path = roblox_profile.avatar_file()
    if not info or not path.is_file():
        return W - 48
    try:
        avatar = Image.open(path).convert("RGBA").resize((52 * S, 52 * S), Image.LANCZOS)
    except OSError:
        return W - 48
    mask = Image.new("L", avatar.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, avatar.size[0] - 1, avatar.size[1] - 1), fill=255)
    x, y = W - 48 - 52, 34
    c.d.ellipse((x * S - 3 * S, y * S - 3 * S, (x + 52) * S + 3 * S, (y + 52) * S + 3 * S), fill=CARD,
                outline=TEAL, width=2 * S)
    c.img.paste(avatar, (x * S, y * S), mask)
    c.text((x - 14, 40), info.get("display") or info.get("name", ""), 17, TEXT, bold=True, anchor="ra")
    c.text((x - 14, 64), "@" + info.get("name", ""), 13, DIM, anchor="ra")
    return x - 14 - 230                              # leave room for the name


def render_card(stats: StatsStore, since: Optional[float], raid: Optional[str], title: str) -> bytes:
    summary = stats.summary(since, raid)
    recs = stats.last_runs(100000, since, raid)
    c = _Canvas()

    # ---- header
    logo_path = app_paths.resource_path("assets/app.png")
    if logo_path.is_file():
        logo = Image.open(logo_path).convert("RGBA").resize((56 * S, 56 * S), Image.LANCZOS)
        c.img.paste(logo, (48 * S, 36 * S), logo)
    c.text((120, 38), "ANIME ASTRAL MONITOR", 14, TEAL, bold=True, spacing=2.2)
    c.text((120, 58), title + (f" · {raid}" if raid else ""), 32, TEXT, bold=True)
    right = _profile(c)
    if recs:
        first, last = datetime.fromtimestamp(recs[-1].ts_end), datetime.fromtimestamp(recs[0].ts_end)
        span = (last - first).total_seconds()
        c.text((right, 44), f"{first:%d.%m.%Y} · {first:%H:%M}–{last:%H:%M}", 17, MUTED, anchor="ra")
        mins = int(span // 60)
        c.text((right, 70), tr("{h} h {m} min", h=mins // 60, m=mins % 60) if mins >= 60 else tr("{minutes} min.", minutes=mins), 15, DIM, anchor="ra")

    if not recs:
        c.box((48, 130, W - 48, 560))
        c.text((W // 2, 345), tr("No attempts in the selected period yet"), 26, MUTED, anchor="mm")
        return c.png()

    # ---- metric tiles (3 × 2)
    tiles = [
        (tr("Attempts"), messages.fmt_k(summary.attempts), TEAL),
        (tr("Waves total"), messages.fmt_int(summary.waves_total), TEAL),
        (tr("Waves per hour"), messages.fmt_int(round(summary.waves_per_hour)) if summary.waves_per_hour else "–", TEXT),
        (tr("Best wave"), str(summary.best_wave), AMBER),
        (tr("Attempts per hour"), dec(f"{summary.attempts_per_hour:.1f}") if summary.attempts_per_hour else "–", TEXT),
        (tr("Avg. duration per attempt"), messages.fmt_duration(summary.avg_duration_all), TEXT),
    ]
    tw, th, gap, x0, y0 = 184, 108, 14, 48, 120
    for i, (label, value, color) in enumerate(tiles):
        x, y = x0 + (i % 3) * (tw + gap), y0 + (i // 3) * (th + gap)
        c.box((x, y, x + tw, y + th))
        c.text((x + 18, y + 16), label, 14, MUTED)
        c.text((x + 18, y + 40), value, 38, color, bold=True)

    # ---- chart on the right: raids per day (how far a raid gets doesn't matter – owner)
    px0, py0, px1, py1 = 640, 120, W - 48, 350
    c.box((px0, py0, px1, py1))
    days = stats.daily(14, raid)
    if any(d["attempts"] for d in days):
        c.text((px0 + 20, py0 + 16), tr("Raids per day"), 17, TEXT, bold=True)
        c.text((px0 + 20, py0 + 40), tr("Last 14 days"), 13, MUTED)
        data = [(f"{d['day'].day}.", d["attempts"]) for d in days]
    else:
        data = [(f"{h:02d}", n) for h, n in stats.hourly_waves(10, raid)]
        c.text((px0 + 20, py0 + 16), tr("Waves per hour"), 17, TEXT, bold=True)
        c.text((px0 + 20, py0 + 40), tr("Waves cleared, last 10 hours"), 13, MUTED)
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

    # ---- profiles at the bottom
    per = stats.per_raid(since) if raid is None else [p for p in stats.per_raid(since) if p["raid"] == raid]
    rows = max(1, min(3, len(per)))
    c.box((48, 366, W - 48, 366 + 64 + rows * 52 + 4))
    c.text((70, 382), tr("Profiles") if raid is None else tr("Profile"), 17, TEXT, bold=True)
    total = max((r.total_waves for r in recs), default=100) or 100
    for i, p in enumerate(per[:3]):
        y = 420 + i * 52
        c.text((70, y), raid_label(p["raid"]), 18, TEXT, bold=True)
        sub = tr("{attempts} attempts · {waves} waves · {time} per raid", attempts=p["attempts"],
                 waves=messages.fmt_int(p["waves_total"]), time=messages.fmt_duration(p["avg_duration_all"]))
        c.text((70, y + 24), sub, 13, MUTED)
        bx0, bx1 = 560, W - 230
        c.bar((bx0, y + 12, bx1, y + 24), (30, 40, 52), radius=6)
        c.bar((bx0, y + 12, bx0 + (bx1 - bx0) * min(1.0, p["best_wave"] / total), y + 24), TEAL, radius=6)
        c.text((W - 70, y + 4), tr("Best wave {wave}", wave=p["best_wave"]), 15, TEAL, bold=True, anchor="ra")
    if not per:
        c.text((70, 430), tr("No raids assigned yet – choose the current raid on the start page."), 15, MUTED)
    c.text((W // 2, H - 22), tr("Created with Anime Astral Monitor"), 12, DIM, anchor="mm")
    return c.png()


MONTHS = (N_("January"), N_("February"), N_("March"), N_("April"), N_("May"), N_("June"), N_("July"), N_("August"),
          N_("September"), N_("October"), N_("November"), N_("December"))
VIOLET = (123, 140, 255)


def month_title(year: int, month: int) -> str:
    return f"{tr(MONTHS[month - 1])} {year}"


def render_month_card(stats: StatsStore, year: int, month: int) -> bytes:
    """Monthly recap (“Wrapped”): totals, comparison with the previous month, raids per day and the month's highlights."""
    m = stats.month(year, month)
    c = _Canvas()
    logo_path = app_paths.resource_path("assets/app.png")
    if logo_path.is_file():
        logo = Image.open(logo_path).convert("RGBA").resize((56 * S, 56 * S), Image.LANCZOS)
        c.img.paste(logo, (48 * S, 36 * S), logo)
    c.text((120, 38), tr("MONTHLY RECAP"), 14, TEAL, bold=True, spacing=2.2)
    c.text((120, 58), month_title(year, month), 32, TEXT, bold=True)
    if not m["attempts"]:
        c.box((48, 130, W - 48, 560))
        c.text((W // 2, 345), tr("No raids this month yet"), 26, MUTED, anchor="mm")
        return c.png()
    right = _profile(c)
    if m["prev_attempts"]:
        change = round(100 * (m["attempts"] - m["prev_attempts"]) / m["prev_attempts"])
        c.text((right, 48), tr("{change} % raids vs. last month", change=f"{change:+d}"), 17,
               TEAL if change >= 0 else AMBER, bold=True, anchor="ra")

    tiles = [
        (tr("Raids"), messages.fmt_k(m["attempts"]), TEAL),
        (tr("Waves"), messages.fmt_int(m["waves"]), TEAL),
        (tr("Farming time"), tr("{hours} hrs", hours=dec(f"{m['farm_s'] / 3600:.0f}")), VIOLET),
        (tr("Best wave"), str(m["best_wave"]), AMBER),
        (tr("Raids per active day"), dec(f"{m['attempts'] / m['active_days']:.0f}") if m["active_days"] else "–",
         TEXT),
        (tr("Active days"), f"{m['active_days']}/{len(m['per_day'])}", TEXT),
    ]
    tw, th, gap, x0, y0 = 184, 108, 14, 48, 120
    for i, (label, value, color) in enumerate(tiles):
        x, y = x0 + (i % 3) * (tw + gap), y0 + (i // 3) * (th + gap)
        c.box((x, y, x + tw, y + th))
        c.text((x + 18, y + 16), label, 14, MUTED)
        c.text((x + 18, y + 40), value, 38, color, bold=True)

    px0, py0, px1, py1 = 640, 120, W - 48, 350               # raids per day
    c.box((px0, py0, px1, py1))
    c.text((px0 + 20, py0 + 16), tr("Raids per day"), 17, TEXT, bold=True)
    days = m["per_day"]
    cx0, cx1, cy0, cy1 = px0 + 20, px1 - 20, py0 + 56, py1 - 32
    slot = (cx1 - cx0) / len(days)
    top = max(days) or 1
    for i, n in enumerate(days):
        bx, bw = cx0 + i * slot + slot * 0.15, slot * 0.7
        bh = (cy1 - cy0) * n / top
        c.bar((bx, cy1 - max(bh, 2), bx + bw, cy1), TEAL if i + 1 == m["best_day"] else
              ((44, 112, 100) if n else (30, 40, 52)), radius=3)
        if i % 5 == 0 or i == len(days) - 1:
            c.text((bx + bw / 2, cy1 + 8), str(i + 1), 12, MUTED, anchor="ma")

    c.box((48, 366, W - 48, 506))                             # highlights
    c.text((70, 382), tr("Highlights"), 17, TEXT, bold=True)
    highlights = [(tr("Best day"), tr("{month} {day} · {count} raids", day=m["best_day"],
                                         month=tr(MONTHS[month - 1]), count=m["best_day_attempts"]), TEAL)]
    if m["favorite_raid"] and m["favorite_raid"] != UNKNOWN:
        highlights.append((tr("Favorite raid"), tr("{raid} · {count}×", raid=m["favorite_raid"],
                                                   count=m["favorite_count"]), VIOLET))
    if m["peak_hour"] is not None:
        highlights.append((tr("Busiest hour"), tr("{hour}:00", hour=m["peak_hour"]), AMBER))
    col = (W - 96 - 40) / max(1, len(highlights))
    for i, (title, value, color) in enumerate(highlights):
        x = 70 + i * col
        c.text((x, 430), title, 14, MUTED)
        c.text((x, 454), value, 26, color, bold=True)
    c.text((W // 2, H - 22), tr("Created with Anime Astral Monitor"), 12, DIM, anchor="mm")
    return c.png()
