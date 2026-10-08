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
from .automation import Stop
from .uimap import LOCAL_FILE, ROW, match_row, save_local, world_number

AVOID_HIT = 0.9          # so ähnlich wie ein „nicht drücken“-Symbol = auslassen (gleiche Symbole ~0,99)
OBSERVE_WAIT = 4.0        # so lange darf ein Fenster nach dem Klick zum Aufgehen brauchen
HUD_ORDER = ("Equip Best", "Guild", "Boosts", "G. Quests", "Promotion", "Shop", "Items", "Achiev", "Index", "Pets")
FULL = [0.0, 0.0, 1.0, 1.0]
# Fenster, die man gründlich ansieht (Reiter durchklicken, scrollen) – einmal, danach in explore/deep_done.json
DEEP_CATS = ("upgrades", "shop", "quests", "achievements", "guild", "promotion", "inventory", "index", "battlepass",
             "passive", "gigs", "equip_best", "unknown")
SCROLL_POINTS = ((0.62, 0.6), (0.3, 0.55), (0.22, 0.74), (0.5, 0.45))   # rechts groß, links, links unten, Mitte
SCROLL_MAX = 5


class TimeUp(Exception):
    pass


class Explorer:
    def __init__(self, nav, minutes: float, data_dir: Path, full: bool = True) -> None:
        self.nav = nav
        self.full = full                                  # Problem-Fenster erneut öffnen (Standard seit 0.9.9)
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
        # „nicht drücken“ (Gates, Totenkopf in W21: zeitbasierte Modi, Klick schließt den Teleporter)
        self.avoid = [img for e in nav.map.entries if (e.get("extra") or {}).get("avoid")
                      for img in [nav.map.image(e)] if img is not None]

    # ------------------------------------------------------------------ Ablauf
    def run(self) -> None:
        nav = self.nav
        try:
            for name in HUD_ORDER:                         # zuerst die Knöpfe am Rand (wenige, u. a. Pets-Inventar,
                self._hud(name)                            # Gilde) – sonst reicht die Zeit oft nicht bis dorthin
            self._teleporter()
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
        (self.data_dir / "explore" / "deep_done.json").write_text(json.dumps(sorted(self.deep_done)),
                                                                   encoding="utf-8")
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
        reopened, last_read = 0, ""
        while True:
            self._left()
            frame = nav._frame()
            rows = self._rows(frame, lw)
            if not rows and reopened < 3:                  # Teleporter zu (Fenster/Teleport dazwischen): wieder auf,
                reopened += 1                              # zur letzten Welt zurück, weiter
                nav._close_any()
                nav._open_list(lw)
                if last_read:
                    self._find_row(lw, last_read)
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
                    nav.log(tr("Neue Welt: {world}", world=world))
                    self._add_row(world, lw, roi)
                for index, rel in todo:
                    self._left()
                    self._explore_slot(lw, world, name, index, rel, entry)
                done.add(name)
                last_read = name
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
        """Belegte Plätze ohne bekanntes Fenster (bei neuen Welten: alle) – ohne „nicht drücken“-Symbole."""
        found = slots.slots(img)
        done = set()                                      # Bekannte Fenster nur erneut, wenn es Probleme gab (unbekannt)
        # oder sie noch nicht gründlich angesehen wurden (Reiter/Scrollen) – Wunsch des Eigentümers 08.10.2026
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
            if i in done:
                continue
            crop = img[int(rel[1] * h):int(rel[3] * h), int(rel[0] * w):int(rel[2] * w)]
            if any(vision.same_icon(crop, a) >= AVOID_HIT for a in self.avoid):
                self.report["skipped"].append(f"{world} · Platz {i + 1}: zeitbasierter Modus – nicht gedrückt")
                continue
            out.append((i, rel))
        return out

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
            self._snap(f"nichts_{world}_{index + 1}", before, nav._frame())
            button = self._button_for(world, index, rel, box)
            if button.get("file", "").startswith("local:"):  # merken: beim nächsten Erkunden nicht erneut klicken
                button.setdefault("extra", {})["no_window"] = True
            return
        kind, roi, title, frame, template = seen
        analysis = self._analyse(frame, roi, title, template)
        button = self._button_for(world, index, rel, box)
        name = self._window_name(world, analysis, index, button)
        nav.log(tr("{world} · Platz {n}: {title} ({kind})", world=world, n=index + 1,
                   title=analysis.title or "?", kind=analysis.label))
        self._scan_tabs(name, roi, analysis)
        frame = nav._frame()
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
        if button is None or (nav.map_opened(button) and not self._needs_visit(button, hud=True)):
            return
        nav._focus()
        nav._close_any()
        frame = nav._frame()
        roi = nav.hud_roi(button)                         # über die Beschriftung gefunden (jede GUI-Größe)
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
            analysis.category, analysis.label = "guild", tr("Gilde")
        window = analysis.title if analysis.title and analysis.title != name else f"{name} Fenster"
        nav.log(tr("{button}: {title} ({kind})", button=name, title=analysis.title or "?", kind=analysis.label))
        found = analysis.words
        claims = knowledge.claimables(found)
        if claims:
            nav.log(tr("{button}: {count}× „Claim“ gefunden (nicht geklickt)", button=name, count=len(claims)))
        self._scan_tabs(window, roi, analysis)
        frame = nav._frame()                              # nach den Reitern: aktuelles Bild zum Schließen
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
        # Prüfbild stammt aus einer verkleinerten Aufnahme – im scharfen Live-Bild auch die Beschriftung zulassen
        area = [max(0.0, x0 - 0.01), max(0.0, y0 - 0.01), min(1.0, x1 + 0.01), min(1.0, y1 + 0.02)]
        want = re.sub(r"[^a-z]", "", button["name"].lower())[:5]
        return any(want and want in re.sub(r"[^a-z]", "", w.lower())
                   for w, _b in vision.words_in(frame, area, self.nav._ocr))

    # ------------------------------------------------------------------ Beobachten, einordnen, schließen
    def _observe(self, before: np.ndarray):
        """Nach einem Klick: Was ist aufgegangen? (art, lage, titel, bild, vorlage) oder None (nichts)."""
        nav = self.nav
        end = time.monotonic() + OBSERVE_WAIT
        time.sleep(0.5)                                    # danach wartet die Schleife auf einen stabilen Titel
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
                    title = "?"                            # Menü offen, Titel nicht lesbar (Teleporter-Zeilen weg)
                if title and not nav._menu.is_base(title):
                    if last == title:
                        return "menu", roi, "" if title == "?" else title, frame, None
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
        analysis = knowledge.classify(title, words, template.window["name"] if template else "")
        analysis.words = words                              # für Claim-Suche wiederverwenden (OCR ~150 ms)
        if analysis.category in ("raid", "defense"):
            analysis.drops = knowledge.raid_drops(words)  # Grundlage für die Raid-Erkennung über Drops
            fh, fw = frame.shape[:2]
            crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
            name = vision.read_name_below_banner(crop, self.nav._ocr) if crop.size else ""
            if name:                                       # „Raid“/„Boss Rush“ -> „Holy Grail War“
                analysis.mode, analysis.title = analysis.title, name
        return analysis

    def _needs_visit(self, button: dict, hud: bool = False) -> bool:
        """Bekanntes Fenster erneut öffnen? Nur bei Problemen (unbekannt, kein Titel) oder wenn es gründlich angesehen
        werden soll (Reiter, Scrollen) und das noch nicht geschehen ist."""
        if not self.full:
            return False
        window = self.nav.map.window_for(button)
        if window is None:
            return True
        cat = (window.get("extra") or {}).get("category", "")
        if cat == "unknown":
            return True
        return (hud or cat in DEEP_CATS) and window["name"] not in self.deep_done

    def _scan_tabs(self, window: str, roi: list[float], analysis: knowledge.Analysis) -> None:
        """Gründlich ansehen (unbeaufsichtigt sicher):
        1. Sperrzonen setzen (Leave, Kick, Delete …; Gilde: Ecke unten links) – dort wird nie geklickt, gescrollt
           oder gehovert (Navigator._guard).
        2. Hauptseite lesen und scrollbare Bereiche finden (Mausrad an mehreren Stellen, nur wo sich etwas bewegt).
        3. Reiter (links untereinander / unten nebeneinander) einzeln öffnen, lesen, scrollen.
        4. Reine Ansichts-Knöpfe (knowledge.NAV_WORDS: Info, Members, Personal, Weekly …) testweise drücken und
           festhalten, was passiert; geht ein Unterfenster auf, wird es wieder geschlossen.
        Nie Aktions-Knöpfe (Claim, Buy, Roll, Max …). Ganze Bildschirme (Upgrade Tree …): nur lesen/scrollen."""
        nav = self.nav
        title = analysis.title or window
        nav.forbidden = knowledge.forbidden_zones(analysis.words, roi, title)
        try:
            full = roi == FULL
            tabs = [] if full else knowledge.side_tabs(analysis.words, roi)
            lines, areas = self._scroll_read(roi, analysis.words)
            analysis.tabs.append({"tab": "", "lines": lines, "scroll": areas})
            for label, box in tabs[:9]:
                self._left()
                nav.log(tr("{window}: Reiter „{tab}“", window=window, tab=label))
                try:
                    nav._click_roi(box)
                except Stop as exc:                        # gesperrt: überspringen, nie erzwingen
                    nav.log(str(exc))
                    continue
                time.sleep(1.0)
                frame = nav._frame()
                words = vision.words_in(frame, roi, nav._ocr)
                nav.forbidden += knowledge.forbidden_zones(words, roi, title)
                sub = knowledge.classify(label, words)
                tab_lines, tab_areas = self._scroll_read(roi, words)
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
        """Ansichts-Knöpfe testweise drücken; geht ein Unterfenster auf: lesen, schließen, prüfen, dass das
        ursprüngliche Fenster wieder da ist – sonst aufhören (nichts erzwingen)."""
        nav = self.nav
        frame = nav._frame()
        words = vision.words_in(frame, roi, nav._ocr)
        for label, box in knowledge.nav_buttons(words, tabs):
            self._left()
            nav.log(tr("{window}: teste „{button}“", window=window, button=label))
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
                analysis.tabs.append({**result, "note": "Fenster zu"})
                break                                      # Fenster weg: nicht weiter testen
            if now_title and title and not vision.same_title(now_title, title):
                result["opened"] = now_title               # Unterfenster: schließen und zurück
                nav._click(state[2])
                time.sleep(0.8)
                back = nav._menu.state(nav._frame(), nav._ocr)
                analysis.tabs.append(result)
                if back is None or not vision.same_title(back[1], title):
                    break
                continue
            analysis.tabs.append(result)

    def _scroll_read(self, roi: list[float], words: list) -> tuple[list[str], list[list[float]]]:
        """Inhalt lesen und scrollbare Bereiche finden: an mehreren Stellen das Mausrad drehen; wo sich etwas bewegt,
        weiter nach unten lesen, bis nichts mehr kommt, dann wieder nach oben. Gesperrte Stellen werden ausgelassen.
        Rückgabe: (Textzeilen ohne Doppelte, Stellen, an denen gescrollt werden kann)."""
        nav = self.nav
        lines = knowledge.lines_of(words)
        areas: list[list[float]] = []
        x0, y0, x1, y1 = roi
        for fx, fy in SCROLL_POINTS:
            point = (x0 + fx * (x1 - x0), y0 + fy * (y1 - y0))
            if knowledge.inside(point, nav.forbidden):
                continue
            moved = 0
            last = self._content(roi)
            for _ in range(SCROLL_MAX):
                self._left()
                nav._wheel(point, -3)
                time.sleep(0.5)
                now = self._content(roi)
                if float(cv2.absdiff(now, last).mean()) < 3.0:
                    break                                  # nichts bewegt: nicht scrollbar oder unten angekommen
                moved += 1
                last = now
                for line in knowledge.lines_of(vision.words_in(nav._frame(), roi, nav._ocr)):
                    if line not in lines:
                        lines.append(line)
            if moved:
                areas.append([round(point[0], 4), round(point[1], 4)])
                nav.log(tr("Gescrollt: {n}×", n=moved))
                nav._wheel(point, 3 * moved)               # zurück nach oben (Reiter/Knöpfe wieder an ihrem Platz)
                time.sleep(0.4)
        return lines[:150], areas

    def _content(self, roi: list[float]) -> np.ndarray:
        frame = self.nav._frame()
        fh, fw = frame.shape[:2]
        crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
        return cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (160, 90), interpolation=cv2.INTER_AREA)

    def _window_name(self, world: str, analysis: knowledge.Analysis, index: int, button: dict) -> str:
        named = button.get("name", "")
        if named and not named.startswith("?") and "Platz" not in named:
            name = named                                   # vom Eigentümer benannt („Ninja Raid“) – eindeutiger
            if self.nav.map.container(name) is not None:   # als ein Titel wie „Raid“ oder „Crafting“
                name = f"{name} Fenster"
            return name
        base = analysis.title or analysis.label or f"Platz {index + 1}"
        if analysis.category in ("raid", "defense") and analysis.mode:
            base = analysis.title                          # Raid-Name statt „Raid“
        if analysis.category == "pets":
            base = "Pets-Roll"
        prefix = re.match(r"(W\d+|W\?)\s", world + " ")
        name = f"{prefix.group(1)} {base}" if prefix and not world.lower().startswith("lobby") else base
        if self.nav.map.container(name) is not None:
            name = f"{name} ({index + 1})"
        return name

    def _snap(self, tag: str, before: np.ndarray, after: np.ndarray) -> None:
        """Bilder vorher/nachher speichern (halbe Größe) – damit sich unklare Fälle später klären lassen."""
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
        if analysis.drops and analysis.mode:              # Raid-Fenster mit gelesenem Namen: Drops je Raid
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
        time.sleep(0.6)


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


