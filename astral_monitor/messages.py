"""Discord-Nachrichten (Embeds) bauen."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .settings import Settings, is_hex_color
from .i18n import N_, dec, thousands, tr

COLOR_OK = 0x45E0BF            # logo turquoise
COLOR_WARN = 0xFFB547
COLOR_INFO = 0x7B8CFF          # Logo-Violett
COLOR_ERROR = 0xFF6B6B
COLOR_GRAY = 0x6C7891


def logo_url() -> str:
    """Program logo from the own (public) repository – only known in GitHub builds, otherwise empty."""
    from .updater import current_repo
    repo = current_repo()
    return f"https://raw.githubusercontent.com/{repo}/main/assets/app.png" if repo else ""


def _avatar() -> dict:
    """Logo as the webhook's avatar (applies per message; the webhook settings in Discord stay untouched)."""
    return {"avatar_url": logo_url()} if logo_url() else {}


def brand(settings: Settings) -> dict:
    """Small author line with the logo above every message (consistent look)."""
    from .version import __version__
    author = {"name": f"{settings.username} · v{__version__}"}
    if logo_url():
        author["icon_url"] = logo_url()
    return author


def progress_bar(value: int, total: int, width: int = 16) -> str:
    """Progress bar made of characters, e.g. ▰▰▰▰▰▰▱▱ (Discord can't do real bars)."""
    filled = 0 if not total else max(0, min(width, round(width * value / total)))
    return "▰" * filled + "▱" * (width - filled)


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "–"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def fmt_wave(wave, total) -> str:
    """“50/100” – or only “542” in modes without a total (total 0/None)."""
    return f"{wave}/{total}" if total else f"{wave}"


def fmt_int(value: int) -> str:
    return thousands(f"{value:,}")


def fmt_k(value: int) -> str:
    """Short amounts with k/M: 950 → “950”, 18 109 → “18.1k”, 843 231 → “843k”, 1 250 000 → “1.25M”.
    Stay exact (fmt_int): waves (rise slowly, you want to see them exactly), raid number and the current value
    for quests."""
    v = abs(value)
    if v < 1000:
        return str(value)
    if v < 1_000_000:
        n, unit = value / 1000, "k"
    else:
        n, unit = value / 1_000_000, "M"
    digits = 0 if abs(n) >= 100 else 1 if abs(n) >= 10 or unit == "k" else 2
    text = f"{n:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{n:.0f}"
    return dec(text) + unit


def quest_text(quests: list[dict], limit: int = 6) -> str:
    lines = []
    for q in quests[:limit]:
        cur = "?" if q["cur"] is None else fmt_int(q["cur"])
        tot = "?" if not q["total"] else fmt_k(q["total"])
        pct = f" ({q['percent']} %)" if q["percent"] is not None else ""
        lines.append(f"• {q['title']} — **{cur}/{tot}**{pct}")
    return "\n".join(lines) or "–"


def build_message(settings: Settings, kind: str, title: str, color: int,
                  fields: list[tuple[str, str, bool]] | None = None,
                  description: str | None = None,
                  image: tuple | None = None) -> tuple[dict, list]:
    """Returns (payload, files). `fields`: (name, value, inline). An event's own color takes precedence.
    Style “compact”: the first values as one calm line (an image, e.g. for an alert, small on the right)."""
    compact = settings.message_style == "compact"
    if compact and fields:
        values = [f"{n} {' '.join(str(v).split())}" for n, v, inline in fields if inline and v][:3]   # „Dauer 2:51“
        line = "-# " + "  ·  ".join(values) if values else ""
        description = "\n".join(x for x in (description, line) if x) or None
        fields = None
    custom = settings.events.get(kind, {}).get("color")
    if is_hex_color(custom):
        color = int(custom[1:], 16)
    embed: dict = {
        "title": title,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "author": brand(settings),
    }
    if description:
        embed["description"] = description[:4000]
    if fields:
        embed["fields"] = [{"name": n[:256], "value": (v or "–")[:1024], "inline": bool(i)}
                           for n, v, i in fields[:25]]

    files: list = []
    if image:
        name, data, *ctype = image                       # (Name, Daten[, Content-Type])
        embed["thumbnail" if compact else "image"] = {"url": f"attachment://{name}"}
        files.append((name, data, ctype[0] if ctype else "image/jpeg"))

    payload: dict = {"username": settings.username, "embeds": [embed],
                     "allowed_mentions": {"parse": []}, **_avatar()}
    entry = settings.events.get(kind, {})
    uid = settings.ping_user_id.strip()
    if entry.get("ping") and uid.isdigit():
        payload["content"] = f"<@{uid}>"
        payload["allowed_mentions"] = {"users": [uid]}
    return payload, files


def fmt_duration_est(seconds: Optional[float], estimated: bool = False) -> str:
    """Like fmt_duration, estimated values with “~”."""
    text = fmt_duration(seconds)
    return f"~{text}" if estimated and seconds is not None else text


STATUS_COLORS = {"running": COLOR_OK, "paused": COLOR_WARN, "stopped": COLOR_GRAY}
STATUS_TEXT = {"running": ("🟢", N_("Running")), "paused": ("🟡", N_("Paused")), "stopped": ("⚫", N_("Stopped"))}


def build_status(settings: Settings, snap: dict) -> dict:
    """Live status message: status and raid as the title, the wave as a large progress bar, key figures with icons
    in two rows of three. Discord keeps counting “Started … ago” live by itself (<t:…:R>)."""
    status = snap.get("status", "stopped")
    emoji, word = STATUS_TEXT.get(status, ("", status))
    profile = snap.get("profile") or ""
    title = f"{emoji} {tr(word)}" + (f" · {profile}" if profile else "")

    wave, total = snap.get("wave"), snap.get("total_waves")
    if wave is not None and not total:                  # mode without a total: only the wave, no bar
        lines = ["## 🌊 " + tr("Wave {wave}", wave=fmt_wave(wave, total))]
    elif wave is not None and total:
        pct = round(100 * wave / total)
        lines = ["## 🌊 " + tr("Wave {wave}", wave=fmt_wave(wave, total)),
                 f"`{progress_bar(wave, total)}` **{pct} %**"]
    elif status == "stopped":
        lines = ["## 💤 " + tr("Monitoring stopped")]
    else:
        lines = ["## ⏳ " + tr("Waiting for the next raid")]
    meta = []
    if snap.get("started_unix") and status != "stopped":
        meta.append(tr("Started {when}", when=f"<t:{int(snap['started_unix'])}:R>"))
    if snap.get("last_event"):
        meta.append(tr("Last: {event}", event=snap["last_event"]))
    if meta:
        lines.append("-# " + "  ·  ".join(meta))

    wph, avg_dur = snap.get("waves_per_hour"), snap.get("avg_duration")
    fields = [
        ("🔁 " + tr("Attempts"), f"**{snap.get('session_attempts', 0)}**\n-# "
         + tr("total {count}", count=fmt_k(snap.get("total_attempts", 0))), True),
        ("🌊 " + tr("Waves"), f"**{fmt_int(snap.get('session_waves', 0))}**", True),
        ("⚡ " + tr("Waves/h"), f"**{fmt_int(round(wph))}**" if wph else "–", True),
        ("⏳ " + tr("Time per raid"), f"**{fmt_duration(avg_dur)}**" if avg_dur else "–", True),
        ("🏆 " + tr("Best wave"), f"**{snap['best_wave']}**" if snap.get("best_wave") else "–", True),
        ("⏱️ " + tr("Running time"), f"**{fmt_duration(snap.get('uptime'))}**" if snap.get("uptime") else "–", True),
    ]
    extra = []
    if snap.get("wall"):
        extra.append(("🧱 " + tr("Wall"), tr("Wave {wave} · {streak}× in a row", wave=snap["wall"].wave,
                                             streak=snap["wall"].streak), True))
    if snap.get("ram_mb"):
        extra.append(("🖥️ Roblox", dec(f"{snap['ram_mb'] / 1024:.1f} GB RAM"), True))
    if extra:
        while len(extra) < 3:                       # fill up the row so the grid stays calm
            extra.append(("​", "​", True))
        fields += extra
    if snap.get("quests") and settings.attach_quests:
        fields.append(("📜 " + tr("Quests"), quest_text(snap["quests"], limit=5), False))
    if settings.message_style == "compact":          # compact: key figures as one line, quests stay
        parts = [tr("{count} raids", count=snap.get("session_attempts", 0)),
                 tr("{waves} waves", waves=fmt_int(snap.get("session_waves", 0)))]
        if wph:
            parts.append(tr("{waves} waves/h", waves=fmt_int(round(wph))))
        if snap.get("best_wave"):
            parts.append(tr("Best wave {wave}", wave=snap["best_wave"]))
        if snap.get("uptime"):
            parts.append(tr("Running {time}", time=fmt_duration(snap.get("uptime"))))
        lines.insert(len(lines) - 1 if meta else len(lines), "-# " + "  ·  ".join(parts))   # before “Started …”
        fields = [f for f in fields if not f[2]]

    embed = {
        "author": brand(settings),
        "title": title[:256],
        "description": "\n".join(lines),
        "color": STATUS_COLORS.get(status, COLOR_GRAY),
        "fields": [{"name": n[:256], "value": (v or "–")[:1024], "inline": bool(i)} for n, v, i in fields[:25]],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": tr("Live status · updated")},
    }
    if logo_url():
        embed["thumbnail"] = {"url": logo_url()}
    return {"username": settings.username, "embeds": [embed], "allowed_mentions": {"parse": []}, **_avatar()}
