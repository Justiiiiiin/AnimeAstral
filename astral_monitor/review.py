"""Funde des Erkundens bestätigen (ohne Qt, Wunsch des Eigentümers 08.10.2026): Jedes Fenster wird EINMAL gründlich
gescannt; danach fragt das Programm mit allem, was es gefunden hat (Art, Reiter, scrollbare Bereiche, Knöpfe, Text),
und der Nutzer bestätigt, korrigiert die Art oder setzt „nochmal prüfen“. Nur dann öffnet das Erkunden das Fenster
erneut. Gespeichert in explore/review.json im Datenordner; korrigierte Arten wirken über UiMap.load auf die Karte."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .i18n import tr

PENDING, OK, RECHECK = "pending", "ok", "recheck"


def review_file(data_dir: Path) -> Path:
    return data_dir / "explore" / "review.json"


def load(data_dir: Path) -> dict:
    try:
        data = json.loads(review_file(data_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data_dir: Path, data: dict) -> None:
    path = review_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def add_finding(data_dir: Path, window: str, finding: dict) -> None:
    """Neuer Fund nach einem Scan: wartet auf Bestätigung (eine bestätigte Art bleibt erhalten)."""
    data = load(data_dir)
    old = data.get(window) or {}
    entry = {**finding, "status": PENDING}
    if old.get("status") == OK and old.get("category"):
        entry["category"] = old["category"]
    data[window] = entry
    save(data_dir, data)


def set_status(data_dir: Path, window: str, status: str, category: Optional[str] = None) -> None:
    data = load(data_dir)
    entry = data.setdefault(window, {})
    entry["status"] = status
    if category:
        entry["category"] = category
    save(data_dir, data)


def pending(data_dir: Path) -> list[tuple[str, dict]]:
    return [(name, e) for name, e in load(data_dir).items() if e.get("status") == PENDING]


def status_of(data_dir: Path, window: str) -> str:
    return (load(data_dir).get(window) or {}).get("status", "")


def category_overrides(data_dir: Path) -> dict[str, str]:
    """Vom Nutzer bestätigte/korrigierte Arten (Fenstername -> Kategorie)."""
    return {name: e["category"] for name, e in load(data_dir).items()
            if e.get("status") == OK and e.get("category")}


def summary(entry: dict) -> str:
    """Kurztext eines Funds für die Rückfrage."""
    parts = []
    if entry.get("tabs"):
        parts.append(tr("Reiter: {tabs}", tabs=", ".join(entry["tabs"])))
    if entry.get("scroll"):
        parts.append(tr("Scrollbare Bereiche: {n}", n=len(entry["scroll"])))
    if entry.get("actions"):
        parts.append(tr("Knöpfe: {buttons}", buttons=", ".join(entry["actions"][:12])))
    if entry.get("claims"):
        parts.append(tr("Claim-Knöpfe: {n}", n=entry["claims"]))
    if entry.get("tested"):
        parts.append(tr("Getestet: {buttons}", buttons=", ".join(entry["tested"])))
    return "\n".join(parts)
