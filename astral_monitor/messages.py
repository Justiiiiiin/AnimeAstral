"""Discord-Nachrichten (Embeds) bauen."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .settings import Settings, is_hex_color
from .i18n import N_, dec, thousands, tr

COLOR_OK = 0x45E0BF            # Logo-Türkis
COLOR_WARN = 0xFFB547
COLOR_INFO = 0x7B8CFF          # Logo-Violett
COLOR_ERROR = 0xFF6B6B
COLOR_GRAY = 0x6C7891


def logo_url() -> str:
    """Programmlogo aus dem eigenen (öffentlichen) Repository – nur in GitHub-Builds bekannt, sonst leer."""
    from .updater import current_repo
    repo = current_repo()
    return f"https://raw.githubusercontent.com/{repo}/main/assets/app.png" if repo else ""


def _avatar() -> dict:
    """Logo als Profilbild des Webhooks (gilt je Nachricht; die Webhook-Einstellungen in Discord bleiben unberührt)."""
    return {"avatar_url": logo_url()} if logo_url() else {}


def brand(settings: Settings) -> dict:
    """Kleiner Absender mit Logo über jeder Nachricht (einheitlicher Auftritt)."""
    from .version import __version__
    author = {"name": f"{settings.username} · v{__version__}"}
    if logo_url():
        author["icon_url"] = logo_url()
    return author


def progress_bar(value: int, total: int, width: int = 16) -> str:
    """Fortschrittsbalken aus Zeichen, z. B. ▰▰▰▰▰▰▱▱ (Discord kann keine echten Balken)."""
    filled = 0 if not total else max(0, min(width, round(width * value / total)))
    return "▰" * filled + "▱" * (width - filled)


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "–"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def fmt_int(value: int) -> str:
    return thousands(f"{value:,}")


def fmt_k(value: int) -> str:
    """Mengen kurz mit k/M: 950 → „950“, 18 109 → „18,1k“, 843 231 → „843k“, 1 250 000 → „1,25M“.
    Zählstände (aktueller Wert bei Quests, Raid-Nummer) bleiben genau (fmt_int)."""
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
    """Gibt (payload, files) zurück. `fields`: (Name, Wert, inline). Eine eigene Farbe je Ereignis hat Vorrang."""
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
        embed["image"] = {"url": f"attachment://{name}"}
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
    """Wie fmt_duration, geschätzte Werte mit „~“."""
    text = fmt_duration(seconds)
    return f"~{text}" if estimated and seconds is not None else text


STATUS_COLORS = {"running": COLOR_OK, "paused": COLOR_WARN, "stopped": COLOR_GRAY}
STATUS_TEXT = {"running": ("🟢", N_("Läuft")), "paused": ("🟡", N_("Pausiert")), "stopped": ("⚫", N_("Gestoppt"))}


def build_status(settings: Settings, snap: dict) -> dict:
    """Live-Statusnachricht: Status und Raid als Titel, Welle als großer Fortschrittsbalken, Kennzahlen mit Symbolen
    in zwei Dreierreihen. „Gestartet vor …“ rechnet Discord selbst live weiter (<t:…:R>)."""
    status = snap.get("status", "stopped")
    emoji, word = STATUS_TEXT.get(status, ("", status))
    profile = snap.get("profile") or ""
    title = f"{emoji} {tr(word)}" + (f" · {profile}" if profile else "")

    wave, total = snap.get("wave"), snap.get("total_waves")
    if wave is not None and total:
        pct = round(100 * wave / total)
        lines = ["## 🌊 " + tr("Welle {wave}/{total}", wave=wave, total=total),
                 f"`{progress_bar(wave, total)}` **{pct} %**"]
    elif status == "stopped":
        lines = ["## 💤 " + tr("Überwachung gestoppt")]
    else:
        lines = ["## ⏳ " + tr("Wartet auf den nächsten Raid")]
    meta = []
    if snap.get("started_unix") and status != "stopped":
        meta.append(tr("Gestartet {when}", when=f"<t:{int(snap['started_unix'])}:R>"))
    if snap.get("last_event"):
        meta.append(tr("Zuletzt: {event}", event=snap["last_event"]))
    if meta:
        lines.append("-# " + "  ·  ".join(meta))

    wph, avg_wave = snap.get("waves_per_hour"), snap.get("avg_wave")
    fields = [
        ("🔁 " + tr("Versuche"), f"**{snap.get('session_attempts', 0)}**\n-# "
         + tr("gesamt {count}", count=fmt_k(snap.get("total_attempts", 0))), True),
        ("🌊 " + tr("Wellen"), f"**{fmt_k(snap.get('session_waves', 0))}**", True),
        ("⚡ " + tr("Wellen/Std"), f"**{fmt_k(round(wph))}**" if wph else "–", True),
        ("📈 " + tr("Ø Endwelle"), f"**{dec(f'{avg_wave:.1f}')}**" if avg_wave else "–", True),
        ("🏆 " + tr("Bestwelle"), f"**{snap['best_wave']}**" if snap.get("best_wave") else "–", True),
        ("⏱️ " + tr("Laufzeit"), f"**{fmt_duration(snap.get('uptime'))}**" if snap.get("uptime") else "–", True),
    ]
    extra = []
    if snap.get("wall"):
        extra.append(("🧱 " + tr("Wand"), tr("Welle {wave} · {streak}× in Folge", wave=snap["wall"].wave,
                                             streak=snap["wall"].streak), True))
    if snap.get("ram_mb"):
        extra.append(("🖥️ Roblox", dec(f"{snap['ram_mb'] / 1024:.1f} GB RAM"), True))
    if extra:
        while len(extra) < 3:                       # Reihe auffüllen, damit das Raster ruhig bleibt
            extra.append(("​", "​", True))
        fields += extra
    if snap.get("quests") and settings.attach_quests:
        fields.append(("📜 " + tr("Quests"), quest_text(snap["quests"], limit=5), False))

    embed = {
        "author": brand(settings),
        "title": title[:256],
        "description": "\n".join(lines),
        "color": STATUS_COLORS.get(status, COLOR_GRAY),
        "fields": [{"name": n[:256], "value": (v or "–")[:1024], "inline": bool(i)} for n, v, i in fields[:25]],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": tr("Live-Status · aktualisiert")},
    }
    if logo_url():
        embed["thumbnail"] = {"url": logo_url()}
    return {"username": settings.username, "embeds": [embed], "allowed_mentions": {"parse": []}, **_avatar()}
