"""Confirm the findings of exploring (without Qt, owner's wish 08.10.2026): every window is scanned thoroughly ONCE;
afterwards the program asks with everything it found (kind, tabs, scrollable areas, buttons, text), and the user
confirms, corrects the kind or sets “check again”. Only then does exploring open the window again. Stored in
explore/review.json in the data folder; corrected kinds apply to the map via UiMap.load."""
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


KEEP = ("annotations", "description", "display")     # user input – survives a new scan


def _alias(name: str) -> str:
    """“Sword 1 Fenster” and “Sword 1” are the same window (earlier runs appended “Fenster”)."""
    return re.sub(r"\s+Fenster$", "", name).strip().lower()


def add_finding(data_dir: Path, window: str, finding: dict) -> None:
    """New finding after a scan: waits for confirmation (a confirmed kind and marks/description are kept).
        Duplicate entries of the same window under another name are merged."""
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
    """Merge duplicate findings (same window, with/without “Fenster” in the name): checked ones win, the user's
        input moves along. Returns the number of removed entries."""
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
    """Marked by the user in the description as “don't open” (e.g. shops with real money) – exploring skips it."""
    text = (load(data_dir).get(window) or {}).get("description", "").lower()
    return any(k in text for k in NEVER_OPEN)


def category_overrides(data_dir: Path) -> dict[str, str]:
    """Kinds confirmed/corrected by the user (window name -> category)."""
    return {name: e["category"] for name, e in load(data_dir).items()
            if e.get("status") == OK and e.get("category")}


def summary(entry: dict) -> str:
    """Short text of a finding for the confirmation."""
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


# ---------------------------------------------------------------------- User marks
# Kinds for frames the user draws in the window image (free text): the program uses them itself –
# “never press” becomes a no-go zone, “list” is scrolled on purpose, buttons/toggles go into the map.
from .i18n import N_  # noqa: E402

ANNOTATION_KINDS = [("button", N_("Button")), ("never", N_("Button – never press")), ("toggle", N_("Toggle")),
                    ("value", N_("Value / display")), ("progress", N_("Progress")), ("list", N_("List (scrollable)")),
                    ("tab", N_("Tab")), ("info", N_("Info / text"))]
CLICKABLE = ("button", "toggle", "tab")


def set_notes(data_dir: Path, window: str, annotations: list[dict], description: str, display: str = "") -> None:
    """Save frames ({box: [x0,y0,x1,y1] in the window image (fractions), kind, text}), description and display name."""
    data = load(data_dir)
    entry = data.setdefault(window, {})
    entry["annotations"] = [{"box": [round(v, 4) for v in a["box"]], "kind": a.get("kind", "info"),
                             "text": a.get("text", "")} for a in annotations]
    entry["description"] = description
    if display:
        entry["display"] = display
    save(data_dir, data)


def annotation_elements(data_dir: Path) -> list[dict]:
    """Marks as entries of the UI map (position in the Roblox window) so macro/explore can use them."""
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
