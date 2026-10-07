"""Erkunden (Beta, seit 0.9.7): Das Makro übernimmt Roblox für ein paar Minuten und lernt das Spiel selbst kennen.

1. Teleporter: nach oben scrollen, dann Welt für Welt. In neuen Welten und bei Symbolen ohne bekanntes Fenster wird
   jedes Symbol einmal geöffnet, gelesen (knowledge.classify) und wieder geschlossen.
2. Knöpfe am Bildschirmrand (Equip Best, Guild, Boosts, Quests, Shop …): je einmal öffnen, lesen, schließen.
3. Ergebnis: lokale Ergänzung der Karte (uimap_local.json im Datenordner) – danach kann das Makro dorthin
   navigieren – plus Bericht (explore/report.json) und Bilder je Fenster.

Es wird NUR geöffnet und geschlossen: nie Roll, Craft, Buy, Claim, Equip … (knowledge.ACTION_WORDS). Not-Aus wie beim
Makro (Maus bewegen, Esc, „Stopp“). Ohne Qt."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import knowledge, vision
from .i18n import tr
from .uimap import LOCAL_FILE, ROW, match_row, save_local, world_number

OBSERVE_WAIT = 4.0        # so lange darf ein Fenster nach dem Klick zum Aufgehen brauchen
HUD_ORDER = ("Equip Best", "Guild", "Boosts", "G. Quests", "Promotion", "Shop", "Items", "Achiev", "Index", "Pets")
FULL = [0.0, 0.0, 1.0, 1.0]


class TimeUp(Exception):
    pass


class Explorer:
    def __init__(self, nav, minutes: float, data_dir: Path) -> None:
        self.nav = nav
        self.deadline = time.monotonic() + max(0.5, minutes) * 60
        self.data_dir = data_dir
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.out = data_dir / "explore" / stamp
        self.report: dict = {"started": stamp, "worlds": [], "hud": [], "skipped": []}
        self.local: list[dict] = []
        self.count = 0

    # ------------------------------------------------------------------ Ablauf
    def run(self) -> None:
        nav = self.nav
        try:
            self._teleporter()
            for name in HUD_ORDER:
                self._hud(name)
        except TimeUp:
            nav.log(tr("Zeit abgelaufen – Erkunden beendet."))
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
        worlds = sum(1 for w in self.report["worlds"] if w.get("new"))
        self.nav.log(tr("Erkundet: {count} Fenster, {worlds} neue Welten – Bericht: {path}", count=self.count,
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
            nav.log(tr("Der Karte fehlen Erkennungsbilder."))
            return
        nav._open_list(lw)
        over = ((lw["roi"][0] + lw["roi"][2]) / 2, (lw["roi"][1] + lw["roi"][3]) / 2)
        self._scroll_top(lw, over)
        done: set[str] = set()
        stuck, last = 0, None
        while True:
            self._left()
            frame = nav._frame()
            rows = self._rows(frame, lw)
            layout = tuple((name, round(roi[1], 3)) for name, roi, _img, _m in rows)
            for i, (name, roi, img, known) in enumerate(rows):
                if name in done:
                    continue
                world = self._world_name(name, known, rows[:i])
                todo = self._unknown_slots(known, img, slots, world)
                entry = {"name": world, "read": name, "new": known is None, "windows": []}
                self.report["worlds"].append(entry)
                if known is None:
                    nav.log(tr("Neue Welt: {world}", world=world))
                    self._add_row(world, lw, roi)
                for index, rel in todo:
                    self._left()
                    self._explore_slot(lw, world, name, index, rel, entry)
                done.add(name)
                frame = nav._frame()                       # Lage kann sich nach dem Schließen geändert haben
            if layout == last:
                stuck += 1
                if stuck >= 2:
                    return                                 # Ende der Liste
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
        """Sichtbare Zeilen: (gelesener Name, Lage, Bild, Eintrag der Karte oder None)."""
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
        """Belegte Plätze ohne bekanntes Fenster (bei neuen Welten: alle)."""
        found = slots.slots(img)
        if known is None:
            return found
        done = set()
        for e in self.nav.map.children(known):
            if e.get("kind") in ("Knopf", "Symbol") and e.get("rel") and self.nav.map_opened(e):
                i = slots.index_of(e["rel"])
                if i is not None:
                    done.add(i)
        return [(i, rel) for i, rel in found if i not in done]

    def _find_row(self, lw: dict, read: str) -> Optional[list[float]]:
        """Zeile wiederfinden (nach dem Schließen ist der Teleporter evtl. zu oder verschoben)."""
        nav = self.nav
        nav._open_list(lw)
        over = ((lw["roi"][0] + lw["roi"][2]) / 2, (lw["roi"][1] + lw["roi"][3]) / 2)
        last = None
        for _ in range(30):
            rows = self._rows(nav._frame(), lw)
            for name, roi, _img, _m in rows:
                if name == read:
                    return roi
            layout = tuple((n, round(r[1], 3)) for n, r, _i, _m in rows)
            if layout == last:
                return None
            last = layout
            nav._wheel(over, -vision_scroll())
            time.sleep(0.4)
        return None

    def _explore_slot(self, lw: dict, world: str, read: str, index: int, rel: list[float], entry: dict) -> None:
        nav = self.nav
        box = self._find_row(lw, read)
        if box is None:
            self.report["skipped"].append(f"{world} · {index + 1}: Zeile nicht wiedergefunden")
            return
        before = nav._frame()
        nav._click_rel(box, rel)
        seen = self._observe(before)
        if seen is None:
            self.report["skipped"].append(f"{world} · Platz {index + 1}: nichts geöffnet")
            return
        kind, roi, title, frame, template = seen
        analysis = self._analyse(frame, roi, title, template)
        name = self._window_name(world, analysis, index)
        nav.log(tr("{world} · Platz {n}: {title} ({kind})", world=world, n=index + 1,
                   title=analysis.title or "?", kind=analysis.label))
        button = self._button_for(world, index, rel, box)
        self._record_window(name, roi, button, analysis, template, frame)
        entry["windows"].append({"slot": index + 1, "window": name, **analysis.as_dict()})
        self._close(kind, roi, template, frame)

    def _button_for(self, world: str, index: int, rel: list[float], box: list[float]) -> dict:
        """Knopf des Platzes: vorhandener aus der Karte, sonst neu (lokal)."""
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

    # ------------------------------------------------------------------ Knöpfe am Bildschirmrand
    def _hud(self, name: str) -> None:
        self._left()
        nav = self.nav
        button = next((e for e in nav.map.hud() if e["name"] == name), None)
        if button is None or nav.map_opened(button):
            return
        nav._focus()
        nav._close_any()
        frame = nav._frame()
        if not self._hud_visible(button, frame):
            self.report["skipped"].append(f"{name}: Knopf nicht gefunden")
            return
        nav._click_roi(button["roi"])
        seen = self._observe(frame)
        if seen is None:
            self.report["skipped"].append(f"{name}: nichts geöffnet")
            return
        kind, roi, title, frame, template = seen
        analysis = self._analyse(frame, roi, title or name, template)
        if name == "Equip Best":
            analysis.category, analysis.label = "equip_best", tr("Equip Best")
        elif name == "Guild":
            analysis.category, analysis.label = "guild", tr("Gilde")
        window = analysis.title if analysis.title and analysis.title != name else f"{name} Fenster"
        nav.log(tr("{button}: {title} ({kind})", button=name, title=analysis.title or "?", kind=analysis.label))
        words = [w for w, _r in vision.words_in(frame, roi, nav._ocr)]
        self.report["hud"].append({"button": name, "window": window, "words": words[:80], **analysis.as_dict()})
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
        return float(cv2.minMaxLoc(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED))[1]) >= 0.55

    # ------------------------------------------------------------------ Beobachten, einordnen, schließen
    def _observe(self, before: np.ndarray):
        """Nach einem Klick: Was ist aufgegangen? (art, lage, titel, bild, vorlage) oder None (nichts)."""
        nav = self.nav
        end = time.monotonic() + OBSERVE_WAIT
        time.sleep(0.8)
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
                if title and not nav._menu.is_base(title):
                    if last == title:
                        return "menu", roi, title, frame, None
                    last = title
                    continue
            elif calm and vision_changed(before, frame):
                # ganzer Bildschirm (Upgrade Tree, Artefakt …) – nur mit „Close“/„Exit“, sonst nicht erkundbar
                if knowledge.close_word(vision.words_in(frame, FULL, nav._ocr)) is not None:
                    return "full", FULL, "", frame, None
                return None
            time.sleep(0.25)
        return None

    def _analyse(self, frame: np.ndarray, roi: list[float], title: str, template) -> knowledge.Analysis:
        words = vision.words_in(frame, roi, self.nav._ocr)
        return knowledge.classify(title, words, template.window["name"] if template else "")

    def _window_name(self, world: str, analysis: knowledge.Analysis, index: int) -> str:
        base = analysis.title or analysis.label or f"Platz {index + 1}"
        if analysis.category == "pets":
            base = "Pets-Roll"
        prefix = re.match(r"(W\d+|W\?)\s", world + " ")
        name = f"{prefix.group(1)} {base}" if prefix and not world.lower().startswith("lobby") else base
        if self.nav.map.container(name) is not None:
            name = f"{name} ({index + 1})"
        return name

    def _record_window(self, name: str, roi: list[float], button: dict, analysis: knowledge.Analysis, template,
                       frame: np.ndarray) -> None:
        self.count += 1
        extra = {"category": analysis.category, "explored": True, "buttons": analysis.as_dict()["buttons"]}
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
        cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tofile(str(self.out / f"{self.count:03d}_{safe}.jpg"))

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
        time.sleep(0.8)


def vision_scroll() -> int:
    from .automation import SCROLL_NOTCHES
    return SCROLL_NOTCHES


def vision_changed(before: np.ndarray, after: np.ndarray) -> bool:
    """Deutliche Änderung (ganzer Bildschirm wechselt, z. B. Upgrade Tree)."""
    if before.shape != after.shape:
        return True
    a = cv2.resize(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY), (160, 90), interpolation=cv2.INTER_AREA)
    b = cv2.resize(cv2.cvtColor(after, cv2.COLOR_BGR2GRAY), (160, 90), interpolation=cv2.INTER_AREA)
    return float(np.count_nonzero(cv2.absdiff(a, b) > 40)) / a.size > 0.25


def latest_report(data_dir: Path) -> Optional[dict]:
    try:
        return json.loads((data_dir / "explore" / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def forget_local(data_dir: Path) -> None:
    """Erkundete Einträge vergessen (lokale Ergänzung der Karte löschen)."""
    (data_dir / LOCAL_FILE).unlink(missing_ok=True)


