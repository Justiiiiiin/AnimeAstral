"""Funde des Erkundens bestätigen (ohne Qt, Wunsch des Eigentümers 08.10.2026): Jedes Fenster wird EINMAL gründlich
gescannt; danach fragt das Programm mit allem, was es gefunden hat (Art, Reiter, scrollbare Bereiche, Knöpfe, Text),
und der Nutzer bestätigt, korrigiert die Art oder setzt „nochmal prüfen“. Nur dann öffnet das Erkunden das Fenster
erneut. Gespeichert in explore/review.json im Datenordner; korrigierte Arten wirken über UiMap.load auf die Karte."""
from __future__ import annotations

import json
import re
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


KEEP = ("annotations", "description", "display")     # Eingaben des Nutzers – überdauern einen neuen Scan


def _alias(name: str) -> str:
    """„Sword 1 Fenster“ und „Sword 1“ sind dasselbe Fenster (frühere Läufe hängten „Fenster“ an)."""
    return re.sub(r"\s+Fenster$", "", name).strip().lower()


def add_finding(data_dir: Path, window: str, finding: dict) -> None:
    """Neuer Fund nach einem Scan: wartet auf Bestätigung (eine bestätigte Art und Markierungen/Beschreibung bleiben
    erhalten). Doppelte Einträge desselben Fensters unter anderem Namen werden zusammengelegt."""
    data = load(data_dir)
    old = data.get(window) or {}
    for name in [n for n in data if n != window and _alias(n) == _alias(window)]:
        twin = data.pop(name)
        if not old or (twin.get("status") == OK and old.get("status") != OK):
            old = twin
    entry = {**finding, "status": PENDING}
    if old.get("status") == OK and old.get("category"):
        entry["category"] = old["category"]
    entry.update({k: old[k] for k in KEEP if old.get(k)})
    data[window] = entry
    save(data_dir, data)


def dedupe(data_dir: Path) -> int:
    """Doppelte Funde zusammenlegen (gleiches Fenster, mit/ohne „Fenster“ im Namen): geprüfte gewinnen, Eingaben des
    Nutzers wandern mit. Rückgabe: Anzahl entfernter Einträge."""
    data = load(data_dir)
    groups: dict[str, list[str]] = {}
    for name in data:
        groups.setdefault(_alias(name), []).append(name)
    removed = 0
    for names in groups.values():
        if len(names) < 2:
            continue
        rank = {OK: 0, RECHECK: 1}
        names.sort(key=lambda n: (rank.get(data[n].get("status"), 2), n.endswith(" Fenster")))
        keep = data[names[0]]
        for name in names[1:]:
            for k in KEEP:
                if data[name].get(k) and not keep.get(k):
                    keep[k] = data[name][k]
            del data[name]
            removed += 1
    if removed:
        save(data_dir, data)
    return removed


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


NEVER_OPEN = ("nicht öffnen", "nie öffnen", "nicht oeffnen", "nie oeffnen", "never open", "do not open")


def never_open(data_dir: Path, window: str) -> bool:
    """Vom Nutzer in der Beschreibung als „Nicht öffnen“ markiert (z. B. Shops mit Echtgeld) – Erkunden lässt es aus."""
    text = (load(data_dir).get(window) or {}).get("description", "").lower()
    return any(k in text for k in NEVER_OPEN)


def category_overrides(data_dir: Path) -> dict[str, str]:
    """Vom Nutzer bestätigte/korrigierte Arten (Fenstername -> Kategorie)."""
    return {name: e["category"] for name, e in load(data_dir).items()
            if e.get("status") == OK and e.get("category")}


def summary(entry: dict) -> str:
    """Kurztext eines Funds für die Rückfrage."""
    parts = []
    if entry.get("tabs"):
        parts.append(tr("Tabs: {tabs}", tabs=", ".join(entry["tabs"])))
    if entry.get("scroll"):
        parts.append(tr("Scrollable areas: {n}", n=len(entry["scroll"])))
    if entry.get("actions"):
        parts.append(tr("Buttons: {buttons}", buttons=", ".join(entry["actions"][:12])))
    if entry.get("claims"):
        parts.append(tr("Claim buttons: {n}", n=entry["claims"]))
    if entry.get("tested"):
        parts.append(tr("Tested: {buttons}", buttons=", ".join(entry["tested"])))
    return "\n".join(parts)


# ---------------------------------------------------------------------- Markierungen des Nutzers
# Arten für Rahmen, die der Nutzer im Fensterbild zieht (Text frei): das Programm nutzt sie selbst –
# „nie drücken“ wird Sperrzone, „Liste“ wird gezielt gescrollt, Knöpfe/Schalter landen in der Karte.
from .i18n import N_  # noqa: E402

ANNOTATION_KINDS = [("button", N_("Button")), ("never", N_("Button – never press")), ("toggle", N_("Toggle")),
                    ("value", N_("Value / display")), ("progress", N_("Progress")), ("list", N_("List (scrollable)")),
                    ("tab", N_("Tab")), ("info", N_("Info / text"))]
CLICKABLE = ("button", "toggle", "tab")


def set_notes(data_dir: Path, window: str, annotations: list[dict], description: str, display: str = "") -> None:
    """Rahmen ({box: [x0,y0,x1,y1] im Fensterbild (Anteile), kind, text}), Beschreibung und Anzeigename speichern."""
    data = load(data_dir)
    entry = data.setdefault(window, {})
    entry["annotations"] = [{"box": [round(v, 4) for v in a["box"]], "kind": a.get("kind", "info"),
                             "text": a.get("text", "")} for a in annotations]
    entry["description"] = description
    if display:
        entry["display"] = display
    save(data_dir, data)


def annotation_elements(data_dir: Path) -> list[dict]:
    """Markierungen als Einträge der Oberflächen-Karte (Lage im Roblox-Fenster), damit Makro/Erkunden sie nutzen."""
    out = []
    for window, entry in load(data_dir).items():
        roi = entry.get("roi")
        if not roi:
            continue
        x0, y0, x1, y1 = roi
        for i, a in enumerate(entry.get("annotations") or []):
            bx0, by0, bx1, by1 = a["box"]
            kind = a.get("kind", "info")
            out.append({"name": f"{window} · {a.get('text') or kind}", "parent": window,
                        "kind": "Knopf" if kind in CLICKABLE else "Bereich",
                        "roi": [round(x0 + bx0 * (x1 - x0), 4), round(y0 + by0 * (y1 - y0), 4),
                                round(x0 + bx1 * (x1 - x0), 4), round(y0 + by1 * (y1 - y0), 4)],
                        "file": f"review:{window}:{i}", "note": "vom Nutzer markiert",
                        "extra": {"annotation": kind, "text": a.get("text", ""), "forbid": kind == "never",
                                  "scroll": kind == "list"}})
    return out
