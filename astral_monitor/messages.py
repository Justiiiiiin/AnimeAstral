"""Discord-Nachrichten (Embeds) bauen."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .settings import Settings

COLOR_OK = 0x3DD6B5
COLOR_WARN = 0xF5A524
COLOR_INFO = 0x5B8DEF
COLOR_ERROR = 0xFF6B6B
COLOR_GRAY = 0x8B97A8


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "–"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def quest_text(quests: list[dict], limit: int = 6) -> str:
    lines = []
    for q in quests[:limit]:
        cur = "?" if q["cur"] is None else fmt_int(q["cur"])
        tot = "?" if not q["total"] else fmt_int(q["total"])
        pct = f" ({q['percent']} %)" if q["percent"] is not None else ""
        lines.append(f"• {q['title']} — **{cur}/{tot}**{pct}")
    return "\n".join(lines) or "–"


def build_message(settings: Settings, kind: str, title: str, color: int,
                  fields: list[tuple[str, str, bool]] | None = None,
                  description: str | None = None,
                  image: tuple | None = None) -> tuple[dict, list]:
    """Gibt (payload, files) zurück. `fields`: (Name, Wert, inline)."""
    embed: dict = {
        "title": title,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": settings.username},
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
                     "allowed_mentions": {"parse": []}}
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
STATUS_TEXT = {"running": "🟢 Läuft", "paused": "🟡 Pausiert", "stopped": "⚫ Gestoppt"}


def build_status(settings: Settings, snap: dict) -> dict:
    """Embed der Live-Statusnachricht aus einem Zustandsabzug der Engine."""
    status = snap.get("status", "stopped")
    wave = f"Welle {snap['wave']}/{snap['total_waves']}" if snap.get("wave") is not None else "Kein Raid im Bild"
    profile = f" · {snap['profile']}" if snap.get("profile") else ""
    wph, avg_wave = snap.get("waves_per_hour"), snap.get("avg_wave")
    fields = [
        ("Versuche (Session)", str(snap.get("session_attempts", 0)), True),
        ("Wellen (Session)", fmt_int(snap.get("session_waves", 0)), True),
        ("Wellen pro Stunde", f"{wph:.0f}" if wph else "–", True),
        ("Ø Endwelle", f"{avg_wave:.1f}".replace(".", ",") if avg_wave else "–", True),
        ("Versuche gesamt", fmt_int(snap.get("total_attempts", 0)), True),
        ("Laufzeit", fmt_duration(snap.get("uptime")), True),
    ]
    if snap.get("best_wave"):
        label = f"Bestwelle ({snap['profile']})" if snap.get("profile") else "Bestwelle"
        fields.append((label, str(snap["best_wave"]), True))
    if snap.get("ram_mb"):
        fields.append(("Roblox", f"{snap['ram_mb'] / 1024:.1f} GB RAM".replace(".", ","), True))
    if snap.get("quests") and settings.attach_quests:
        fields.append(("Quests", quest_text(snap["quests"], limit=5), False))
    description = f"## {wave}{profile}"
    if snap.get("last_event"):
        description += f"\n-# Zuletzt: {snap['last_event']}"
    embed = {
        "title": f"{STATUS_TEXT.get(status, status)} · Live-Status",
        "description": description,
        "color": STATUS_COLORS.get(status, COLOR_GRAY),
        "fields": [{"name": n[:256], "value": (v or "–")[:1024], "inline": bool(i)} for n, v, i in fields[:25]],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": f"{settings.username} · aktualisiert"},
    }
    return {"username": settings.username, "embeds": [embed], "allowed_mentions": {"parse": []}}
