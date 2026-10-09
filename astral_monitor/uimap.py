"""UI map of the game (bundled in uimap/, created with the developer tool): named windows, world rows in the
teleporter, buttons and who opens which window. Basis of the automation (automation.py).

Entries: name, kind, parent (name of the window/row), roi (fractions of the Roblox window), rel (fractions within
the row), extra (template, layout_of, closes_to, marker, close), opened_by_id (ID of the opening button),
file (ID), img (bundled image, only where needed)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

MAP_DIR = Path(__file__).with_name("uimap")
CONTAINER_KINDS = ("Fenster / Bereich", "Liste (scrollbar)", "Zeile (Vorlage)")
ROW = "Zeile (Vorlage)"


def natural(text: str) -> tuple:
    """Sort key “W2” before “W10”."""
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"(\d+)", text.lower()) if p)


class UiMap:
    def __init__(self, entries: list[dict], base: Path = MAP_DIR) -> None:
        self.entries = entries
        self.base = base
        self._by_id = {e.get("file"): e for e in entries}

    @classmethod
    def load(cls, base: Path = MAP_DIR, local: Optional[Path] = None) -> "UiMap":
        """Bundled map + local additions (from exploring, in the data folder). Bundled entries take precedence."""
        try:
            data = json.loads((base / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = []
        entries = [e for e in data if isinstance(e, dict) and e.get("name")]
        if local is None:
            try:
                from .app_paths import data_dir
                local = data_dir() / LOCAL_FILE
            except Exception:  # noqa: BLE001
                local = None
        if local is not None:
            have = {e.get("file") for e in entries}
            entries += [e for e in load_local(local) if e.get("file") not in have]
            try:                                          # kinds confirmed/corrected by the user + marks
                from .review import annotation_elements, category_overrides
                overrides = category_overrides(local.parent)
                have = {e.get("file") for e in entries}
                entries += [e for e in annotation_elements(local.parent) if e["file"] not in have]
            except Exception:  # noqa: BLE001
                overrides = {}
            for e in entries:
                if e.get("name") in overrides:
                    e["extra"] = {**(e.get("extra") or {}), "category": overrides[e["name"]]}
        return cls(entries, base)

    def add(self, entry: dict) -> None:
        """Add an entry at runtime (exploring)."""
        self.entries.append(entry)
        self._by_id[entry.get("file")] = entry

    def windows_for(self, button: dict) -> list[dict]:
        """All windows this button opens (bundled + explored can be duplicates)."""
        return [e for e in self.entries if e.get("kind") in CONTAINER_KINDS and e.get("kind") != ROW and (
            e.get("opened_by_id") == button.get("file") if e.get("opened_by_id")
            else e.get("opened_by") and e.get("opened_by") == button.get("name"))]

    def window_for(self, button: dict) -> Optional[dict]:
        """Window this button opens (or None)."""
        for e in self.entries:
            if e.get("kind") in CONTAINER_KINDS and e.get("kind") != ROW:
                if e.get("opened_by_id"):
                    if e["opened_by_id"] == button.get("file"):
                        return e
                elif e.get("opened_by") and e.get("opened_by") == button.get("name"):
                    return e
        return None

    def hud(self) -> list[dict]:
        """Buttons at the screen edge (Shop, Guild, Equip Best …) – always at the same place."""
        return [e for e in self.entries if (e.get("extra") or {}).get("hud") and e.get("kind") == "Knopf"]

    # -- lookup
    def find(self, name: str, kinds: Optional[tuple] = None) -> Optional[dict]:
        return next((e for e in self.entries if e.get("name") == name and (kinds is None or e.get("kind") in kinds)),
                    None)

    def by_id(self, entry_id: str) -> Optional[dict]:
        return self._by_id.get(entry_id)

    def container(self, name: str) -> Optional[dict]:
        return self.find(name, CONTAINER_KINDS)

    def children(self, entry: dict) -> list[dict]:
        return [e for e in self.entries if e.get("parent") == entry.get("name")]

    def parent(self, entry: dict) -> Optional[dict]:
        return self.container(entry.get("parent", "")) if entry.get("parent") else None

    def opener_of(self, window: dict) -> Optional[dict]:
        if window.get("opened_by_id"):
            return self.by_id(window["opened_by_id"])
        return self.find(window["opened_by"], ("Knopf",)) if window.get("opened_by") else None

    def template_of(self, window: dict) -> Optional[dict]:
        """Template this window is built after (e.g. “W4 Pets-Roll” -> “Pets-Roll (Vorlage)”)."""
        name = (window.get("extra") or {}).get("layout_of")
        return self.container(name) if name else None

    def element(self, window: dict, name: str) -> Optional[dict]:
        """Element of a window – for windows built after a template, from the template."""
        for owner in (window, self.template_of(window)):
            if owner is not None:
                hit = next((e for e in self.children(owner) if e.get("name") == name), None)
                if hit is not None:
                    return hit
        return None

    def close_element(self, window: dict) -> Optional[dict]:
        for owner in (window, self.template_of(window)):
            if owner is not None:
                hit = next((e for e in self.children(owner) if (e.get("extra") or {}).get("close")), None)
                if hit is not None:
                    return hit
        return None

    def rows(self, window: dict) -> list[dict]:
        return sorted((e for e in self.children(window) if e.get("kind") == ROW), key=lambda r: natural(r["name"]))

    def list_windows(self) -> list[dict]:
        """Windows with world rows (teleporter)."""
        return [e for e in self.entries if e.get("kind") in CONTAINER_KINDS and e.get("kind") != ROW
                and any(c.get("kind") == ROW for c in self.children(e))]

    def targets(self) -> list[dict]:
        """Targets: windows with a known opener (no templates)."""
        return sorted((e for e in self.entries if e.get("kind") in CONTAINER_KINDS and e.get("kind") != ROW
                       and self.opener_of(e) is not None and not (e.get("extra") or {}).get("template")),
                      key=lambda e: natural(e["name"]))

    def world_of(self, window: dict) -> Optional[int]:
        """World number of a window (via the row of its button; lobby = 0), None = button at the edge or similar."""
        button = self.opener_of(window)
        holder = self.parent(button) if button is not None else None
        if holder is None or holder.get("kind") != ROW:
            return None
        if holder["name"].lower().startswith("lobby"):
            return 0
        return world_number(holder["name"])

    def sorted_targets(self) -> list[tuple[str, str]]:
        """Targets for macro and routine, sorted by world (“Lobby · …”, “W1 · …” …, then the buttons at the edge).
        Progressions only once (the first): it has “Auto All” for all (owner 08.10.2026).
        Returns (display, window name)."""
        rows = []
        progression_seen = False
        for w in self.targets():
            if w["name"] == "Teleporter Fenster":
                continue
            world = self.world_of(w)
            cat = (w.get("extra") or {}).get("category", "")
            is_prog = cat == "progression" or "progression" in w["name"].lower()
            rows.append((999 if world is None else world, natural(w["name"]), w, is_prog))
        rows.sort(key=lambda r: (r[0], r[1]))
        out = []
        for world, _key, w, is_prog in rows:
            if is_prog:
                if progression_seen:
                    continue
                progression_seen = True
            name = w["name"]
            if world == 999:
                label = name
            elif world == 0:
                label = name if name.lower().startswith("lobby") else f"Lobby · {name}"
            else:
                label = name if re.match(rf"W{world}\b", name) else f"W{world} · {name}"
            out.append((label, name))
        return out

    def first_progression(self) -> Optional[dict]:
        """First progression window (lowest world) – “Auto All” there applies to all progressions."""
        for _label, name in self.sorted_targets():
            w = self.container(name)
            if w is not None and ((w.get("extra") or {}).get("category") == "progression"
                                  or "progression" in name.lower()):
                return w
        return None

    def templates(self) -> list[tuple[dict, dict]]:
        """(template, marker) – special menus with a fixed layout."""
        out = []
        for w in self.entries:
            if (w.get("extra") or {}).get("template"):
                marker = next((e for e in self.children(w) if (e.get("extra") or {}).get("marker") and e.get("img")),
                              None)
                if marker is not None:
                    out.append((w, marker))
        return out

    def image(self, entry: dict) -> Optional[np.ndarray]:
        if not entry.get("img"):
            return None
        return _read_image(str(self.base / entry["img"]))


@lru_cache(maxsize=16)
def _read_image(path: str) -> Optional[np.ndarray]:
    try:
        return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, ValueError):
        return None


LOCAL_FILE = "uimap_local.json"     # additions from “Explore” (data folder, per user)


def load_local(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict) and e.get("name") and e.get("file")]


def save_local(path: Path, entries: list[dict]) -> None:
    """Write the local additions (same ID = replace)."""
    merged: dict[str, dict] = {e["file"]: e for e in load_local(path)}
    for e in entries:
        merged[e["file"]] = e
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(list(merged.values()), indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def world_number(name: str) -> Optional[int]:
    """“W5 Solo City” -> 5, “Lobby” -> 0, otherwise None."""
    m = re.match(r"W(\d+)\b", name)
    if m:
        return int(m.group(1))
    return 0 if name.lower().startswith("lobby") else None


def match_row(read: str, rows: list[dict]) -> Optional[dict]:
    """Match a read world name (“Ninja Village”, “Lobby Arena”) to the stored row (“W1 Ninja Village”)."""
    words = {_ocr_fold(w) for w in re.findall(r"[a-z0-9]+", read.lower())}
    if not words:
        return None
    for r in rows:
        have = {_ocr_fold(w) for w in re.findall(r"[a-z0-9]+", r["name"].lower()) if not re.fullmatch(r"w\d+", w)}
        if have and (have <= words or words <= have):
            return r
    return None


_FOLD = str.maketrans("0125869", "olzsbgg")


def _ocr_fold(word: str) -> str:
    """Treat easily confused characters as equal (“2 City” read, “Z City” stored; 0/O, 1/l, 5/S …)."""
    return word.translate(_FOLD)
