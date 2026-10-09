"""Explore (beta, since 0.9.7): the macro takes over Roblox for a few minutes and learns the game by itself.

1. Teleporter: scroll to the top, then world by world. In new worlds and for icons without a known window every
   icon is opened once, read (knowledge.classify) and closed again.
2. Buttons at the screen edge (Equip Best, Guild, Boosts, Quests, Shop …): open, read, close each once.
3. Result: local additions to the map (uimap_local.json in the data folder) – afterwards the macro can navigate
   there – plus a report (explore/report.json) and images per window.

It ONLY opens and closes: never Roll, Craft, Buy, Claim, Equip … (knowledge.ACTION_WORDS). Emergency stop like the
macro (move the mouse, Esc, “Stop”). Without Qt."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import knowledge, review, vision
from .i18n import tr
from .automation import Stop
from .uimap import LOCAL_FILE, ROW, match_row, save_local, world_number

AVOID_HIT = 0.9          # this similar to a “don't press” icon = skip (same icons ~0.99)
OBSERVE_WAIT = 6.5        # a window may take this long to open after the click (heavy game load)
HUD_ORDER = ("Equip Best", "Guild", "Boosts", "G. Quests", "Promotion", "Shop", "Items", "Achiev", "Index", "Pets")
FULL = [0.0, 0.0, 1.0, 1.0]
# Windows that are looked at thoroughly (click through tabs, scroll) – once, afterwards in explore/deep_done.json
DEEP_CATS = ("upgrades", "shop", "quests", "achievements", "guild", "promotion", "inventory", "index", "battlepass",
             "passive", "gigs", "equip_best", "unknown")
# Probe grid: the mouse wheel is turned ONCE at each of these spots; scrolling continues only where something
# shifts (area = scrolled_box). The top (title) stays free.
SCROLL_POINTS = tuple((fx, fy) for fy in (0.38, 0.6, 0.82) for fx in (0.2, 0.5, 0.8))
SCROLL_MAX = 5
PROBE_NOTCHES = 2         # wheel notches per probe; without effect turn back right away (otherwise the camera zooms in
                          # to first person – Roblox then holds the cursor and windows won't close anymore)
PROBE_MAX = 4             # at most this many probe spots per page (formerly 9 – too slow, brought little)
NO_SCROLL_CATS = ("raid", "defense", "artefact", "info", "later", "shrine", "pets", "titans", "equip_best")
SCROLL_STOP = ("completed",)   # owner: quests with the large purple “Completed” and everything below are unimportant
EMPTY_SLOTS = {3: (8,), 9: (8,)}   # owner 08.10.2026: W3 and W9 have no slot 8 (edge of the TELEPORT! button)


class TimeUp(Exception):
    pass


class Explorer:
    def __init__(self, nav, minutes: float, data_dir: Path, full: bool = True) -> None:
        self.nav = nav
        self.full = full                                  # reopen problem windows (default since 0.9.9)
        self._current: Optional[str] = None               # window that is being looked at thoroughly right now
        try:
            self.deep_done = set(json.loads((data_dir / "explore" / "deep_done.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            self.deep_done = set()
        self.deadline = time.monotonic() + max(0.5, minutes) * 60
        self.data_dir = data_dir
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.out = data_dir / "explore" / stamp
        self.report: dict = {"started": stamp, "worlds": [], "hud": [], "skipped": []}
        self.local: list[dict] = []
        self.count = 0
        # “don't press” (gates, skull in W21: time-based modes, a click closes the teleporter)
        self.avoid = [img for e in nav.map.entries if (e.get("extra") or {}).get("avoid")
                      for img in [nav.map.image(e)] if img is not None]

    # ------------------------------------------------------------------ Flow
    def run(self) -> None:
        nav = self.nav
        try:
            # first the worlds (pets, crafting, raids, gachas – highest priority, owner 08.10.2026), then
            # the buttons at the edge (shop, guild, quests …)
            self._teleporter()
            for name in HUD_ORDER:
                self._hud(name)
        except TimeUp:
            nav.log(tr("Time is up – exploring finished."))
        finally:
            self._save()

    def _left(self) -> None:
        if time.monotonic() > self.deadline:
            raise TimeUp()

    def _save(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "report.json").write_text(json.dumps(self.report, indent=1, ensure_ascii=False), encoding="utf-8")
        latest = self.data_dir / "explore" / "report.json"
        latest.write_text(json.dumps(self.report, indent=1, ensure_ascii=False), encoding="utf-8")
        if self.local:
            save_local(self.data_dir / LOCAL_FILE, self.local)
        (self.data_dir / "explore" / "deep_done.json").write_text(json.dumps(sorted(self.deep_done)),
                                                                   encoding="utf-8")
        worlds = sum(1 for w in self.report["worlds"] if w.get("new"))
        self.nav.log(tr("Explored: {count} windows, {worlds} new worlds – report: {path}", count=self.count,
                        worlds=worlds, path=str(self.out)))

    # ------------------------------------------------------------------ Teleporter
    def _teleporter(self) -> None:
        nav = self.nav
        lists = nav.map.list_windows()
        if not lists:
            return
        lw = lists[0]
        try:
            slots = vision.SlotLayout(nav.map, lw)
        except ValueError:
            nav.log(tr("The map is missing recognition images."))
            return
        nav._open_list(lw)
        over = ((lw["roi"][0] + lw["roi"][2]) / 2, (lw["roi"][1] + lw["roi"][3]) / 2)
        self._scroll_top(lw, over)
        done: set[str] = set()
        stuck, last = 0, None
        reopened, last_read, last_world = 0, "", ""
        while True:
            self._left()
            frame = nav._frame()
            rows = self._rows(frame, lw)
            if not rows and reopened < 3:                  # teleporter closed (window/teleport in between): open again,
                reopened += 1                              # back to the last world, continue
                nav._close_any()
                nav._open_list(lw)
                if last_read:
                    self._find_row(lw, last_read, last_world)
                continue
            layout = tuple((name, round(roi[1], 3)) for name, roi, _img, _m in rows)
            for i, (name, roi, img, known) in enumerate(rows):
                if name in done:
                    continue
                world = self._world_name(name, known, rows[:i])
                todo = self._unknown_slots(known, img, slots, world)
                entry = {"name": world, "read": name, "new": known is None, "windows": []}
                self.report["worlds"].append(entry)
                if known is None:
                    nav.log(tr("New world: {world}", world=world))
                    self._add_row(world, lw, roi)
                for index, rel in todo:
                    self._left()
                    self._explore_slot(lw, world, name, index, rel, entry)
                done.add(name)
                last_read, last_world = name, world
                frame = nav._frame()                       # the position may have changed after closing
            if last_read:
                self._find_row(lw, last_read, last_world)   # continue at the world handled last (don't jump)
            if layout == last:
                stuck += 1
                if stuck >= 2:
                    return                                 # end of the list
            else:
                stuck = 0
            last = layout
            nav._wheel(over, -vision_scroll())
            time.sleep(0.45)

    def _scroll_top(self, lw: dict, over: tuple[float, float]) -> None:
        last = None
        for _ in range(12):
            names = tuple(n for n, _r, _i, _m in self._rows(self.nav._frame(), lw))
            if any(world_number(n) == 0 or n.lower().startswith("lobby") for n in names) or names == last:
                return
            last = names
            self.nav._wheel(over, 2 * vision_scroll())
            time.sleep(0.4)

    def _rows(self, frame: np.ndarray, lw: dict) -> list[tuple[str, list[float], np.ndarray, Optional[dict]]]:
        """Visible rows: (name read, position, image, map entry or None)."""
        nav = self.nav
        out = []
        for r in nav._rows.find(frame, lw["roi"]):
            key = (cv2.resize(cv2.cvtColor(r.image, cv2.COLOR_BGR2GRAY), (96, 12)) // 16).tobytes()
            name = nav._names.get(key)
            if name is None:
                name = nav._names[key] = vision.read_row_name(r.image, nav._ocr)
            if len(re.sub(r"[^A-Za-z]", "", name)) < 3:
                continue
            out.append((name, r.roi, r.image, match_row(name, nav.map.rows(lw))))
        return out

    def _world_name(self, read: str, known: Optional[dict], above: list) -> str:
        if known is not None:
            return known["name"]
        prev = next((world_number(m["name"]) for _n, _r, _i, m in reversed(above)
                     if m is not None and world_number(m["name"]) is not None), None)
        if prev is None:
            prev = max((world_number(w["name"]) or 0 for w in self.report["worlds"]), default=None)
        return f"W{prev + 1} {read}" if prev is not None else f"W? {read}"

    def _unknown_slots(self, known: Optional[dict], img: np.ndarray, slots: vision.SlotLayout, world: str):
        empty = EMPTY_SLOTS.get(world_number(world) or -1, ())
        "Occupied slots without a known window (in new worlds: all) – without “don't press” icons."
        found = slots.slots(img)
        done = set()                                      # known windows only again if there were problems (unknown)
        # or they weren't looked at thoroughly yet (tabs/scrolling) – owner's wish 08.10.2026
        if known is not None:
            for e in self.nav.map.children(known):
                if e.get("kind") not in ("Knopf", "Symbol") or not e.get("rel"):
                    continue
                i = slots.index_of(e["rel"])
                extra = e.get("extra") or {}
                if i is not None and (extra.get("avoid") or extra.get("no_window")
                                      or (self.nav.map_opened(e) and not self._needs_visit(e))):
                    done.add(i)
        out = []
        h, w = img.shape[:2]
        for i, rel in found:
            if i in done or i + 1 in empty:
                continue
            crop = img[int(rel[1] * h):int(rel[3] * h), int(rel[0] * w):int(rel[2] * w)]
            if any(vision.same_icon(crop, a) >= AVOID_HIT for a in self.avoid):
                self.report["skipped"].append(f"{world} · Platz {i + 1}: zeitbasierter Modus – nicht gedrückt")
                continue
            out.append((i, rel))
        return out

    def _find_row(self, lw: dict, read: str, world: str = "") -> Optional[list[float]]:
        """Find a row again (after closing, the teleporter may be closed or shifted). A row counts as the same if it
        has
                the same name read or the same world in the map (readings vary: “2 City”/“Z City”).
                Direction via the world numbers: target further up -> scroll up, otherwise down (formerly only down – a row
                not found again pushed the list to the end and W14–W18 were skipped)."""
        nav = self.nav
        nav._open_list(lw)
        over = ((lw["roi"][0] + lw["roi"][2]) / 2, (lw["roi"][1] + lw["roi"][3]) / 2)
        target = world_number(world) if world else None
        last = None
        for _ in range(30):
            rows = self._rows(nav._frame(), lw)
            for name, roi, _img, m in rows:
                if name == read or (world and m is not None and m["name"] == world):
                    return roi
            layout = tuple((n, round(r[1], 3)) for n, r, _i, _m in rows)
            if layout == last:
                return None
            last = layout
            seen = [world_number(m["name"]) for _n, _r, _i, m in rows if m is not None
                    and world_number(m["name"]) is not None]
            up = target is not None and seen and min(seen) > target
            nav._wheel(over, vision_scroll() if up else -vision_scroll())
            time.sleep(0.4)
        return None

    def _explore_slot(self, lw: dict, world: str, read: str, index: int, rel: list[float], entry: dict) -> None:
        nav = self.nav
        box = self._find_row(lw, read, world)
        if box is None:
            self.report["skipped"].append(f"{world} · {index + 1}: Zeile nicht wiedergefunden")
            return
        before = nav._frame()
        nav._click_rel(box, rel)
        seen = self._observe(before)
        if seen is None:                                   # second look: smaller windows (Mana Contract) are
            time.sleep(1.0)                                # sometimes narrowly missed during animations/messages
            frame = nav._frame()
            state = nav._menu.state(frame, nav._ocr)
            if state is not None and state[1] and not nav._menu.is_base(state[1]):
                seen = ("menu", state[0], state[1], frame, None)
        if seen is None:
            self.report["skipped"].append(f"{world} · Platz {index + 1}: nichts geöffnet")
            self._snap(f"nichts_{world}_{index + 1}", before, nav._frame())
            button = self._button_for(world, index, rel, box)
            if button.get("file", "").startswith("local:"):  # remember: don't click again on the next explore run
                button.setdefault("extra", {})["no_window"] = True
            return
        kind, roi, title, frame, template = seen
        analysis = self._analyse(frame, roi, title, template)
        if _is_teleporter(analysis.words):                 # still the teleporter in the image (raid windows open
            time.sleep(1.5)                                # slowly) – look once more, otherwise don't record
            frame = nav._frame()
            analysis = self._analyse(frame, roi, title, template)
            if _is_teleporter(analysis.words):
                self.report["skipped"].append(f"{world} · Platz {index + 1}: Teleporter statt Fenster im Bild")
                self._close(kind, roi, template, frame)
                return
        button = self._button_for(world, index, rel, box)
        name = self._known_name(button) or self._window_name(world, analysis, index, button)
        nav.log(tr("{world} · slot {n}: {title} ({kind})", world=world, n=index + 1,
                   title=analysis.title or "?", kind=analysis.label))
        self._scan_tabs(name, roi, analysis)
        frame = nav._frame()
        self._record_window(name, roi, button, analysis, template, frame)
        entry["windows"].append({"slot": index + 1, "window": name, **analysis.as_dict()})
        self._close(kind, roi, template, frame)

    def _button_for(self, world: str, index: int, rel: list[float], box: list[float]) -> dict:
        """Button of the slot: the existing one from the map, otherwise a new (local) one."""
        nav = self.nav
        row = nav.map.container(world)
        layout = vision.SlotLayout(nav.map, nav.map.list_windows()[0])
        if row is not None:
            for e in nav.map.children(row):
                if e.get("rel") and layout.index_of(e["rel"]) == index:
                    return e
        x0, y0, x1, y1 = box
        roi = [x0 + rel[0] * (x1 - x0), y0 + rel[1] * (y1 - y0), x0 + rel[2] * (x1 - x0), y0 + rel[3] * (y1 - y0)]
        btn = {"name": f"{world} · Platz {index + 1}", "kind": "Knopf", "parent": world, "rel": rel,
               "roi": [round(v, 4) for v in roi], "file": f"local:btn:{world}:{index}", "note": "erkundet"}
        self.local.append(btn)
        nav.map.add(btn)
        return btn

    def _add_row(self, world: str, lw: dict, roi: list[float]) -> None:
        if self.nav.map.container(world) is not None:
            return
        row = {"name": world, "kind": ROW, "parent": lw["name"], "roi": [round(v, 4) for v in roi],
               "file": f"local:row:{world}", "note": "erkundet"}
        self.local.append(row)
        self.nav.map.add(row)

    # ------------------------------------------------------------------ Buttons at the screen edge
    def _hud(self, name: str) -> None:
        self._left()
        nav = self.nav
        button = next((e for e in nav.map.hud() if e["name"] == name), None)
        if button is None or (nav.map_opened(button) and not self._needs_visit(button, hud=True)):
            return
        nav._focus()
        nav._close_any()
        frame = nav._frame()
        roi = nav.hud_roi(button)                         # found via the label (any GUI size)
        if roi is button["roi"] and not self._hud_visible(button, frame):
            self.report["skipped"].append(f"{name}: Knopf nicht gefunden")
            self._snap(f"knopf_fehlt_{name}", frame, frame)
            return
        nav._click_roi(roi)
        seen = self._observe(frame)
        if seen is None:
            self.report["skipped"].append(f"{name}: nichts geöffnet")
            self._snap(f"nichts_{name}", frame, nav._frame())
            return
        kind, roi, title, frame, template = seen
        analysis = self._analyse(frame, roi, title or name, template)
        if name == "Equip Best":
            analysis.category, analysis.label = "equip_best", tr("Equip Best")
        elif name == "Guild":
            analysis.category, analysis.label = "guild", tr("Guild")
        window = self._known_name(button) or (analysis.title if analysis.title and analysis.title != name
                                              else f"{name} Fenster")
        nav.log(tr("{button}: {title} ({kind})", button=name, title=analysis.title or "?", kind=analysis.label))
        found = analysis.words
        claims = knowledge.claimables(found)
        if claims:
            nav.log(tr("{button}: found {count}× “Claim” (not clicked)", button=name, count=len(claims)))
        self._scan_tabs(window, roi, analysis)
        frame = nav._frame()                              # after the tabs: current image for closing
        self.report["hud"].append({"button": name, "window": window, "lines": knowledge.lines_of(found)[:80],
                                   "claim": [[round(v, 4) for v in r] for r in claims], **analysis.as_dict()})
        self._record_window(window, roi, button, analysis, template, frame)
        self._close(kind, roi, template, frame)

    def _hud_visible(self, button: dict, frame: np.ndarray) -> bool:
        img = self.nav.map.image(button)
        if img is None:
            return True
        fh, fw = frame.shape[:2]
        f = fw / ((button.get("window") or [img.shape[1]])[0] or fw)
        tpl = img if abs(f - 1) < 0.01 else cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        x0, y0, x1, y1 = button["roi"]
        mx, my = int(0.02 * fw), int(0.02 * fh)
        region = frame[max(0, int(y0 * fh) - my):int(y1 * fh) + my, max(0, int(x0 * fw) - mx):int(x1 * fw) + mx]
        if region.shape[0] < tpl.shape[0] or region.shape[1] < tpl.shape[1]:
            return False
        if float(cv2.minMaxLoc(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED))[1]) >= 0.4:
            return True
        # The check image comes from a scaled-down capture – also allow the label in the sharp live image
        area = [max(0.0, x0 - 0.01), max(0.0, y0 - 0.01), min(1.0, x1 + 0.01), min(1.0, y1 + 0.02)]
        want = re.sub(r"[^a-z]", "", button["name"].lower())[:5]
        return any(want and want in re.sub(r"[^a-z]", "", w.lower())
                   for w, _b in vision.words_in(frame, area, self.nav._ocr))

    # ------------------------------------------------------------------ Observe, classify, close
    def _observe(self, before: np.ndarray):
        """After a click: what opened? (kind, position, title, image, template) or None (nothing)."""
        nav = self.nav
        end = time.monotonic() + OBSERVE_WAIT
        time.sleep(0.5)                                    # afterwards the loop waits for a stable title
        prev_small, last = None, None
        while time.monotonic() < end:
            frame = nav._frame()
            small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90), interpolation=cv2.INTER_AREA)
            calm = prev_small is not None and float(cv2.absdiff(prev_small, small).mean()) < 6.0
            prev_small = small
            for t in nav._templates:
                if t.seen(frame) and not t.seen(before):
                    return "template", t.window["roi"], t.window["name"].replace(" (Vorlage)", ""), frame, t
            state = nav._menu.state(frame, nav._ocr)
            if state is not None:
                roi, title, _x = state
                if not title and calm and not nav._rows.find(frame, nav.map.list_windows()[0]["roi"]):
                    title = "?"                            # menu open, title unreadable (teleporter rows gone)
                if title and not nav._menu.is_base(title):
                    if last == title:
                        return "menu", roi, "" if title == "?" else title, frame, None
                    last = title
                    continue
            elif calm and vision_changed(before, frame):
                # full screen (upgrade tree, artifact …) – only with “Close”/“Exit”, otherwise not explorable
                if knowledge.close_word(vision.words_in(frame, FULL, nav._ocr)) is not None:
                    return "full", FULL, "", frame, None
                return None
            time.sleep(0.25)
        return None

    def _titles(self) -> list[str]:
        """Known window names (map, earlier reports, own names from check findings) – the model for fix_title."""
        if getattr(self, "_title_cache", None) is None:
            names = [e["name"] for e in self.nav.map.entries if e.get("kind") != "Knopf"]
            seen: dict[str, int] = {}                     # titles from reports only if read the same several times
            for report in (self.data_dir / "explore").glob("2*/report.json"):
                try:
                    data = json.loads(report.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for title in {w.get("title") or "" for world in data.get("worlds", []) for w in world.get("windows", [])}:
                    seen[title] = seen.get(title, 0) + 1
            names += [n for n, c in seen.items() if c >= 2]
            names += [e.get("display") or "" for e in review.load(self.data_dir).values()]
            self._title_cache = [n for n in names if n]
        return self._title_cache

    def _analyse(self, frame: np.ndarray, roi: list[float], title: str, template) -> knowledge.Analysis:
        title = knowledge.fix_title(title, self._titles())   # “Cratt Genos” -> “Craft Genos”
        words = vision.words_in(frame, roi, self.nav._ocr)
        analysis = knowledge.classify(title, words, template.window["name"] if template else "")
        analysis.words = words                              # reuse for the claim search (OCR ~150 ms)
        if analysis.category in ("raid", "defense"):
            analysis.drops = knowledge.raid_drops(words)  # basis for raid detection via drops
            fh, fw = frame.shape[:2]
            crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
            name = vision.read_name_below_banner(crop, self.nav._ocr) if crop.size else ""
            if name:                                       # “Raid”/“Boss Rush” -> “Holy Grail War”
                analysis.mode, analysis.title = analysis.title, knowledge.fix_title(name, self._titles())
        return analysis

    def _needs_visit(self, button: dict, hud: bool = False) -> bool:
        """Open the window (again)? Every window is scanned thoroughly only ONCE; afterwards the user decides in the
                confirmation (review.py). Again only if they set “check again”."""
        if not self.full:
            return False
        windows = self.nav.map.windows_for(button)       # bundled + explored: any one checked is enough
        if not windows:
            return True
        names = [w["name"] for w in windows]
        names += [f"{n} Fenster" for n in names]         # earlier runs appended “Fenster” on name clashes
        if any(review.never_open(self.data_dir, n) for n in names):
            return False                                  # “Don't open” (description in check findings)
        states = [review.status_of(self.data_dir, n) for n in names]
        if review.RECHECK in states:
            for n in names:
                self.deep_done.discard(n)
            return True
        return not any(states)                            # open every window once until it is in “Check findings”

    def _marked(self, window: Optional[str], kind: str) -> list[list[float]]:
        """Areas of this window marked by the user (check findings): “never” = no-go zone, “list” = scrollable."""
        if not window:
            return []
        return [e["roi"] for e in self.nav.map.entries if e.get("parent") == window
                and (e.get("extra") or {}).get("annotation") == kind]

    def _scan_tabs(self, window: str, roi: list[float], analysis: knowledge.Analysis) -> None:
        """Look thoroughly (safe unattended):
                1. Set no-go zones (Leave, Kick, Delete …; guild: bottom left corner) – nothing is ever clicked, scrolled
                   or hovered there (Navigator._guard).
                2. Read the main page and find scrollable areas (mouse wheel at several spots, only where something moves).
                3. Open, read and scroll tabs (left one below the other / bottom side by side) one by one.
                4. Press pure view buttons (knowledge.NAV_WORDS: Info, Members, Personal, Weekly …) as a test and record
                   what happens; if a sub-window opens, it is closed again.
                Never action buttons (Claim, Buy, Roll, Max …). Full screens (upgrade tree …): read/scroll only."""
        nav = self.nav
        self._current = window
        title = analysis.title or window
        nav.forbidden = knowledge.forbidden_zones(analysis.words, roi, title) + self._marked(window, "never")
        try:
            full = roi == FULL
            tabs = [] if full else knowledge.side_tabs(analysis.words, roi)
            lines, areas = self._scroll_read(roi, analysis.words, analysis.category)
            analysis.tabs.append({"tab": "", "lines": lines, "scroll": areas})
            for label, box in tabs[:9]:
                self._left()
                nav.log(tr("{window}: tab “{tab}”", window=window, tab=label))
                try:
                    nav._click_roi(box)
                except Stop as exc:                        # blocked: skip, never force
                    nav.log(str(exc))
                    continue
                time.sleep(1.0)
                frame = nav._frame()
                words = vision.words_in(frame, roi, nav._ocr)
                nav.forbidden += knowledge.forbidden_zones(words, roi, title)
                sub = knowledge.classify(label, words)
                tab_lines, tab_areas = self._scroll_read(roi, words, sub.category)
                analysis.tabs.append({"tab": label, "category": sub.category, "label": sub.label,
                                      "claim": len(knowledge.claimables(words)), "lines": tab_lines,
                                      "scroll": tab_areas})
                self._snap(f"reiter_{window}_{label}", frame, frame)
                entry = {"name": f"{window} · {label}", "kind": "Knopf", "parent": window,
                         "roi": [round(v, 4) for v in box], "file": f"local:tab:{window}:{label}", "note": "erkundet",
                         "extra": {"tab": True, "category": sub.category}}
                if nav.map.container(entry["name"]) is None:
                    self.local.append(entry)
                    nav.map.add(entry)
            if not full:
                self._test_buttons(window, roi, title, tabs, analysis)
        finally:
            nav.forbidden = []
        self.deep_done.add(window)

    def _test_buttons(self, window: str, roi: list[float], title: str, tabs: list, analysis) -> None:
        """Press view buttons as a test; if a sub-window opens: read, close, check that the original window is back –
                otherwise stop (force nothing)."""
        nav = self.nav
        if analysis.category in ("raid", "defense"):
            return                                        # raid window: never touch Create/Join & co.
        frame = nav._frame()
        x0, y0, x1, y1 = roi
        banner = [x0, y0, x0 + vision.BAND[1] * (x1 - x0), y0 + vision.BAND[2] * (y1 - y0)]
        words = [(w, b) for w, b in vision.words_in(frame, roi, nav._ocr)
                 if not knowledge.inside(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), [banner])]   # the title isn't a button
        for label, box in knowledge.nav_buttons(words, tabs):
            self._left()
            nav.log(tr("{window}: testing “{button}”", window=window, button=label))
            try:
                nav._click_roi(box)
            except Stop as exc:
                nav.log(str(exc))
                continue
            time.sleep(1.0)
            frame = nav._frame()
            state = nav._menu.state(frame, nav._ocr)
            now_title = state[1] if state else ""
            result = {"button": label, "opened": "", "lines": knowledge.lines_of(
                vision.words_in(frame, state[0] if state else roi, nav._ocr))[:40]}
            if state is None:
                analysis.tabs.append({**result, "note": "window closed"})
                break                                      # window gone: stop testing
            if now_title and title and not vision.same_title(now_title, title):
                result["opened"] = now_title               # sub-window: close and go back
                nav._click(state[2])
                time.sleep(0.8)
                back = nav._menu.state(nav._frame(), nav._ocr)
                analysis.tabs.append(result)
                if back is None or not vision.same_title(back[1], title):
                    break
                continue
            analysis.tabs.append(result)

    def _scroll_read(self, roi: list[float], words: list, category: str = "") -> tuple[list[str], list[list[float]]]:
        """Read the content and find scrollable areas. It only scrolled if the content under the mouse really SHIFTED
                (phase correlation) – timers/animations don't count.
                Faster and safer than the old 3×3 grid (owner 08.10.2026: “takes too long, brings little”):
                - checked windows: only the marked lists (none = don't scroll), raids/artifacts/infos never;
                - probe spots only where there is content (words/edges), not in the title banner, at most PROBE_MAX;
                - PROBE_NOTCHES notches per probe; if nothing moves, turn back right away (undo the camera zoom).
                Returns (text lines without duplicates, spots where scrolling works)."""
        nav = self.nav
        lines = knowledge.lines_of(words)
        areas: list[list[float]] = []
        covered: list[list[float]] = []                   # areas that already scrolled along
        x0, y0, x1, y1 = roi
        marked = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in self._marked(self._current, "list")]
        if marked:
            points = marked                               # lists marked by the user take precedence
        elif category in NO_SCROLL_CATS or (self._current and review.status_of(self.data_dir, self._current)
                                            == review.OK):
            return lines[:150], []                        # nothing to scroll, or confirmed by the user without a list
        else:
            points = probe_points(self._content(roi), words, roi)
        for point in points:
            if knowledge.inside(point, nav.forbidden) or knowledge.inside(point, covered):
                continue
            moved = 0
            last = self._content(roi)
            for _ in range(SCROLL_MAX):
                self._left()
                nav._wheel(point, -PROBE_NOTCHES)
                time.sleep(0.3)
                now = self._content(roi)
                box = scrolled_box(last, now)
                if box is None:
                    nav._wheel(point, PROBE_NOTCHES)      # nothing shifted: notches back (camera!)
                    time.sleep(0.15)
                    break                                  # not scrollable or arrived at the bottom
                moved += 1
                last = now
                covered.append([x0 + box[0] * (x1 - x0), y0 + box[1] * (y1 - y0),
                                x0 + box[2] * (x1 - x0), y0 + box[3] * (y1 - y0)])
                new = knowledge.lines_of(vision.words_in(nav._frame(), roi, nav._ocr))
                for line in new:
                    if line not in lines:
                        lines.append(line)
                if any(stop in line.lower() for line in new for stop in SCROLL_STOP):
                    break                                  # from here only finished ones (Global Quests: “Completed”)
            if moved:
                areas.append([round(point[0], 4), round(point[1], 4)])
                nav.log(tr("Scrolled: {n}×", n=moved))
                # back to the top, step by step only while the list moves: too many notches at the top
                # end go to the camera (zoom to first person, cursor held)
                last = self._content(roi)
                for _ in range(moved + 1):
                    nav._wheel(point, PROBE_NOTCHES)
                    time.sleep(0.25)
                    now = self._content(roi)
                    if scrolled_box(last, now) is None:
                        break
                    last = now
        return lines[:150], areas

    def _content(self, roi: list[float]) -> np.ndarray:
        frame = self.nav._frame()
        fh, fw = frame.shape[:2]
        crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
        return cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (480, 270), interpolation=cv2.INTER_AREA)

    def _known_name(self, button: dict) -> str:
        """Name of the window this button already opens – otherwise duplicates like “Sword 1” and “Sword 1 Fenster”
                appear (checked ones first, then explored, then bundled)."""
        windows = self.nav.map.windows_for(button)
        if not windows:
            return ""
        reviewed = [w for w in windows if review.status_of(self.data_dir, w["name"])]
        local = [w for w in windows if str(w.get("file", "")).startswith("local:")]
        return (reviewed or local or windows)[0]["name"]

    def _window_name(self, world: str, analysis: knowledge.Analysis, index: int, button: dict) -> str:
        named = button.get("name", "")
        if named and not named.startswith("?") and "Platz" not in named:
            name = named                                   # named by the owner (“Ninja Raid”) – more unique
            if self.nav.map.container(name) is not None:   # than a title like “Raid” or “Crafting”
                name = f"{name} Fenster"
            return name
        base = analysis.title or analysis.label or f"Platz {index + 1}"
        if analysis.category in ("raid", "defense") and analysis.mode:
            base = analysis.title                          # raid name instead of “Raid”
        if analysis.category == "pets":
            base = "Pets-Roll"
        prefix = re.match(r"(W\d+|W\?)\s", world + " ")
        name = f"{prefix.group(1)} {base}" if prefix and not world.lower().startswith("lobby") else base
        if self.nav.map.container(name) is not None:
            name = f"{name} ({index + 1})"
        return name

    def _snap(self, tag: str, before: np.ndarray, after: np.ndarray) -> None:
        """Save before/after images (half size) – so unclear cases can be cleared up later."""
        self.out.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w-]+", "_", tag)[:60]
        for suffix, img in (("vorher", before), ("nachher", after)):
            small = cv2.resize(img, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(
                str(self.out / f"{safe}_{suffix}.jpg"))

    def _record_window(self, name: str, roi: list[float], button: dict, analysis: knowledge.Analysis, template,
                       frame: np.ndarray) -> None:
        self.count += 1
        extra = {"category": analysis.category, "explored": True, "buttons": analysis.as_dict()["buttons"]}
        if analysis.drops and analysis.mode:              # raid window with a name read: drops per raid
            extra["drops"] = analysis.drops
            extra["raid_name"] = analysis.title
        if template is not None:
            extra["layout_of"] = template.window["name"]
            extra["closes_to"] = (template.window.get("extra") or {}).get("closes_to", "")
        window = {"name": name, "kind": "Fenster / Bereich", "roi": [round(v, 4) for v in roi],
                  "opened_by_id": button["file"], "opened_by": button["name"],
                  "file": f"local:win:{button['file']}", "note": "erkundet", "extra": extra}
        if self.nav.map.container(name) is None or self.nav.map.container(name).get("file", "").startswith("local:"):
            self.local.append(window)
            self.nav.map.add(window)
        self.out.mkdir(parents=True, exist_ok=True)
        fh, fw = frame.shape[:2]
        crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
        small = cv2.resize(crop, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA) if crop.size else frame
        safe = re.sub(r"[^\w-]+", "_", name)[:60]
        cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tofile(
            str(self.out / f"{self.count:03d}_{safe}.jpg"))
        image = self.out / f"voll_{self.count:03d}_{safe}.jpg"   # full resolution for marking (check findings)
        if crop.size:
            cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tofile(str(image))
        # every window: let the user confirm/mark it (check findings)
        base = analysis.tabs[0] if analysis.tabs else {"lines": knowledge.lines_of(analysis.words)}
        review.add_finding(self.data_dir, name, {
            "title": analysis.title, "category": analysis.category, "label": analysis.label,
            "tabs": [t["tab"] for t in analysis.tabs if t.get("tab")],
            "tested": [t["button"] for t in analysis.tabs if t.get("button")],
            "scroll": [a for t in analysis.tabs for a in t.get("scroll", [])],
            "actions": sorted({b for b, _r in analysis.buttons}),
            "claims": len(knowledge.claimables(analysis.words)),
            "lines": base.get("lines", [])[:20], "image": str(image), "roi": [round(v, 4) for v in roi]})

    def _close(self, kind: str, roi: list[float], template, frame: np.ndarray) -> None:
        nav = self.nav
        if kind == "template":
            close = nav.map.close_element(template.window)
            if close is not None:
                nav._click_roi(close["roi"])
        elif kind == "menu":
            state = nav._menu.state(frame, nav._ocr)
            if state is not None:
                nav._click(state[2])
        else:
            box = knowledge.close_word(vision.words_in(frame, FULL, nav._ocr))
            if box is not None:
                nav._click_roi(box)
        time.sleep(0.6)


def scrolled_box(before: np.ndarray, after: np.ndarray) -> Optional[list[float]]:
    """Has part of the window shifted vertically or horizontally (list scrolled)? Grid of 8 × 6 cells: in every cell
        with enough content the shift is measured (phase correlation). Scrolled = at least two cells with the same shift
        ≥ 3 px along one axis and hardly any along the other – also small lists (Promotions at the bottom left).
        Animations/timers don't shift uniformly and don't count. Returns the area of the shifted cells (fractions of the
        window) or None."""
    h, w = before.shape[:2]
    cols, rows = 8, 6
    hits = []
    for r in range(rows):
        for c in range(cols):
            ys, ye = r * h // rows, (r + 1) * h // rows
            xs, xe = c * w // cols, (c + 1) * w // cols
            a = before[ys:ye, xs:xe].astype(np.float32)
            b = after[ys:ye, xs:xe].astype(np.float32)
            if a.std() < 8 or float(cv2.absdiff(a, b).mean()) < 2.0:
                continue
            (dx, dy), resp = cv2.phaseCorrelate(a, b)
            if resp > 0.15 and abs(dy) >= 3 and abs(dx) <= 1.5:
                hits.append((c, r, "y", dy))
            elif resp > 0.15 and abs(dx) >= 3 and abs(dy) <= 1.5:   # sideways lists (Swords, Professions)
                hits.append((c, r, "x", dx))
    best: list = []
    for _c, _r, axis, d in hits:                          # largest group with (almost) the same shift
        group = [hit for hit in hits if hit[2] == axis and abs(hit[3] - d) <= 2.5]
        if len(group) > len(best):
            best = group
    if len(best) < 2:
        return None
    cs = [hit[0] for hit in best]
    rs = [hit[1] for hit in best]
    return [min(cs) / cols, min(rs) / rows, (max(cs) + 1) / cols, (max(rs) + 1) / rows]


def vision_scroll() -> int:
    from .automation import SCROLL_NOTCHES
    return SCROLL_NOTCHES


def vision_changed(before: np.ndarray, after: np.ndarray) -> bool:
    """Clear change (the whole screen changes, e.g. upgrade tree)."""
    if before.shape != after.shape:
        return True
    a = cv2.resize(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY), (160, 90), interpolation=cv2.INTER_AREA)
    b = cv2.resize(cv2.cvtColor(after, cv2.COLOR_BGR2GRAY), (160, 90), interpolation=cv2.INTER_AREA)
    return float(np.count_nonzero(cv2.absdiff(a, b) > 40)) / a.size > 0.25


def _is_teleporter(words: list) -> bool:
    """Is the teleporter (several “TELEPORT!”/“RESPAWN!” buttons) still in the image instead of the opened window?"""
    return sum(1 for w, _b in words if re.sub(r"[^a-z]", "", w.lower()) in ("teleport", "respawn")) >= 2


def probe_points(content: np.ndarray, words: list, roi: list[float]) -> list[tuple[float, float]]:
    """Where is a scroll probe worth it? From the 3×3 grid only spots with content: edge density around them (tiles,
        rows) or words nearby – empty areas and the title banner are dropped; the densest first, at most PROBE_MAX.
        content: window image grey 480×270 (Explorer._content)."""
    x0, y0, x1, y1 = roi
    h, w = content.shape[:2]
    edges = cv2.Canny(content, 60, 160)
    centers = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for _t, b in words]
    scored = []
    for fx, fy in SCROLL_POINTS:
        px, py = int(fx * w), int(fy * h)
        patch = edges[max(0, py - h // 10):py + h // 10, max(0, px - w // 10):px + w // 10]
        density = float(patch.mean()) / 255 if patch.size else 0.0
        point = (x0 + fx * (x1 - x0), y0 + fy * (y1 - y0))
        near = sum(1 for cx, cy in centers if abs(cx - point[0]) < 0.12 * (x1 - x0)
                   and abs(cy - point[1]) < 0.12 * (y1 - y0))
        if density < 0.04 and near == 0:
            continue                                      # empty area: there is no list there
        scored.append((density + 0.02 * near, point))
    scored.sort(key=lambda s: -s[0])
    return [p for _s, p in scored[:PROBE_MAX]]


def latest_report(data_dir: Path) -> Optional[dict]:
    try:
        return json.loads((data_dir / "explore" / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def forget_local(data_dir: Path) -> None:
    """Forget explored entries (delete the local additions to the map). Older reports are not restored afterwards
        (restore_from_reports)."""
    (data_dir / LOCAL_FILE).unlink(missing_ok=True)
    folder = data_dir / "explore"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "forgot_at").write_text(time.strftime("%Y%m%d_%H%M%S"), encoding="utf-8")




# Window names that exist in every world: when restoring “W8 Crafting” instead of “Crafting Unit Fenster”
_GENERIC = {"crafting": "Crafting", "progression": "Progression", "pets": "Pets-Roll", "battlepass": "Battlepass"}


def _restored_name(world: str, rec: dict, taken: set[str]) -> str:
    prefix = re.match(r"(W\d+)\b", world)
    title = (rec.get("title") or "").strip()
    cat = rec.get("category") or ""
    if "progression" in title.lower() or "progression" in (rec.get("window") or "").lower():
        cat = "progression"
    base = re.sub(r"\s*\(\d+\)$", "", rec.get("window") or title or "?")
    base = re.sub(r"\s+Fenster$", "", base)
    if prefix:
        base = re.sub(rf"^{prefix.group(1)}\s+", "", base)
    if cat in _GENERIC:
        base = _GENERIC[cat]
    elif cat in ("upgrades", "shop") and title.lower() in ("upgrades", "merchant"):
        base = title.title()
    name = f"{prefix.group(1)} {base}" if prefix else base     # always with the world: unique and easy to sort
    n, plain = 2, name
    while name in taken:
        name, n = f"{plain} ({n})", n + 1
    return name


def restore_from_reports(data_dir: Path, uimap) -> int:
    """Bring learned world windows from the reports of earlier explore runs back into the local map (e.g. after
        “Forget what was learned” or an aborted run) – only slots the map doesn't know yet. Reports before the last
        “Forget” (explore/forgot_at) don't count. Returns the number of new windows."""
    folder = data_dir / "explore"
    try:
        forgot = (folder / "forgot_at").read_text(encoding="utf-8").strip()
    except OSError:
        forgot = ""
    latest: dict[tuple[str, int], dict] = {}
    for report in sorted(folder.glob("2*/report.json")):
        if forgot and report.parent.name <= forgot:
            continue
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for world in data.get("worlds", []):
            for rec in world.get("windows", []):
                if rec.get("slot") and rec.get("category") not in (None, "unknown"):
                    latest[(world["name"], int(rec["slot"]))] = rec
    lists = uimap.list_windows()
    if not latest or not lists:
        return 0
    try:
        layout = vision.SlotLayout(uimap, lists[0])
    except ValueError:
        return 0
    rois = [w["roi"] for w in uimap.entries if w.get("kind") == "Fenster / Bereich" and w.get("roi")
            and uimap.world_of(w) is not None and not (w.get("extra") or {}).get("layout_of")]
    if not rois:
        return 0
    roi = sorted(rois)[len(rois) // 2]                    # menus in the teleporter frame are the same size
    taken = {e["name"] for e in uimap.entries}
    added: list[dict] = []
    for (world, slot), rec in sorted(latest.items(), key=lambda kv: (world_number(kv[0][0]) or 0, kv[0][1])):
        row = uimap.container(world)
        if row is None or row.get("kind") != ROW:             # read “W13 2 City”, map: “W13 Z City”
            row = next((r for r in uimap.rows(lists[0]) if world_number(r["name"]) is not None
                        and world_number(r["name"]) == world_number(world)), None)
            if row is None:
                continue
            world = row["name"]
        index = slot - 1
        button = next((e for e in uimap.children(row) if e.get("rel") and layout.index_of(e["rel"]) == index), None)
        if button is not None and uimap.window_for(button) is not None:
            continue                                      # slot already known
        if button is None:
            x0 = layout.x0 + index * layout.pitch
            rel = [round(v, 4) for v in (x0, layout.y[0], x0 + layout.w, layout.y[1])]
            r = row["roi"]
            button = {"name": f"{world} · Platz {slot}", "kind": "Knopf", "parent": world, "rel": rel,
                      "roi": [round(r[0] + rel[0] * (r[2] - r[0]), 4), round(r[1] + rel[1] * (r[3] - r[1]), 4),
                              round(r[0] + rel[2] * (r[2] - r[0]), 4), round(r[1] + rel[3] * (r[3] - r[1]), 4)],
                      "file": f"local:btn:{world}:{index}", "note": "erkundet"}
            added.append(button)
            uimap.add(button)
        name = _restored_name(world, rec, taken)
        taken.add(name)
        cat = rec.get("category")
        if "progression" in (rec.get("title") or "").lower():
            cat = "progression"
        extra = {"category": cat, "explored": True, "buttons": rec.get("buttons", [])}
        if rec.get("drops") and rec.get("mode"):
            extra.update(drops=rec["drops"], raid_name=rec.get("title", ""))
        window = {"name": name, "kind": "Fenster / Bereich", "roi": list(roi), "opened_by_id": button["file"],
                  "opened_by": button["name"], "file": f"local:win:{button['file']}", "note": "erkundet (Bericht)",
                  "extra": extra}
        added.append(window)
        uimap.add(window)
    if added:
        save_local(data_dir / LOCAL_FILE, added)
    return sum(1 for e in added if e["kind"] == "Fenster / Bereich")
