"""Automation (beta, off by default, owner's wish 07.10.2026): walk paths in the game using the UI map (uimap) –
open the teleporter, scroll to the world, click the icon, check that the right menu is open; press “Auto!” in the
pets roll. Input via SendInput (like Anti-AFK, AutoHotkey and autoclickers), only with Roblox in the foreground.
Emergency stop: move the mouse or Esc – every action checks that first.

Runs in its own thread; messages via log(text). Without Qt."""
from __future__ import annotations

import ctypes
import difflib
import json
import re
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from . import vision, winapi
from .macro_base import (_ACTIVE, AUTO_SETTLE, BAR_STEP, CLAIM_GAP, CLAIM_LIMIT, CLAIM_SETTLE, EXTRA_RETRY,
                         MAX_SCROLLS, OPEN_TIMEOUT, SCROLL_NOTCHES, STEP_WAIT, USER_MOVE_PX, Stop, UserStop, _log,
                         fmt_wait, macro_running, parse_timer, task_label)
from .macro_gigs import GigsMixin
from .macro_guild import GUILD_RETRY, GuildMixin
from .macro_raid import RaidMixin
from .i18n import tr
from .uimap import ROW, UiMap, match_row, world_number

# The macro is split into parts (macro_raid / macro_gigs / macro_guild, shared pieces in macro_base); these names
# stay importable from here as before (UI, explorer, tests).
from .macro_gigs import (GIG_NAMES, GIG_SLOT_BOXES, gig_cards, gig_next_due, gig_pill,
                         gig_refresh_box, gig_refresh_read, gig_slot_states, gig_timer_vote, pet_tiles)
from .macro_guild import guild_next_time
from .macro_raid import (IN_RAID_KINDS, RAID_KINDS, complete_raid_labels, leave_before,
                         raid_side_steps)

__all__ = ["Navigator", "Stop", "UserStop", "macro_running", "task_label", "fmt_wait", "parse_timer", "SCROLL_NOTCHES",
           "TASK_KINDS", "migrate_tasks", "next_task", "hud_locate", "user_moved", "GIG_NAMES", "GIG_SLOT_BOXES",
           "gig_cards", "gig_next_due", "gig_pill", "gig_refresh_box", "gig_refresh_read", "gig_slot_states",
           "gig_timer_vote", "pet_tiles", "guild_next_time", "IN_RAID_KINDS", "RAID_KINDS", "complete_raid_labels",
           "leave_before", "raid_side_steps"]

TASK_KINDS = ("raid", "autoroll", "progression", "wait")   # older kinds are converted on load (migrate_tasks)








def migrate_tasks(tasks: list) -> list[dict]:
    """Saved routines from older versions: “Farm raid” (raid_farm) becomes the raid step, start/join a raid becomes
    a raid step that ends after one raid; steps that are switches now (gigs, guild) or were only for testing
    (navigate, pets, close, leave) are dropped. Current steps stay as they are."""
    out = []
    for t in tasks if isinstance(tasks, list) else []:
        if not isinstance(t, dict):
            continue
        kind = t.get("kind")
        if kind in TASK_KINDS:
            out.append(dict(t))
        elif kind == "raid_farm":
            out.append({"kind": "raid", "target": t.get("target", ""), "join": bool(t.get("join")), "until": "runs",
                        "runs": int(t.get("runs", 1) or 1), "leave_wave": int(t.get("leave_wave", 0) or 0)})
        elif kind in ("raid_create", "raid_join"):
            out.append({"kind": "raid", "target": t.get("target", ""), "join": kind == "raid_join", "until": "runs",
                        "runs": 1, "leave_wave": 0})
    return out


def next_task(tasks: list[dict], index: int, loop: bool) -> Optional[dict]:
    """Task after tasks[index] (with loop the first one again), otherwise None."""
    if index + 1 < len(tasks):
        return tasks[index + 1]
    return tasks[0] if loop and len(tasks) > 1 else None










# Find the buttons at the edge via their labels – the game's GUI size (50 %, 100 % …) moves and enlarges them;
# fixed positions from the map only fit at the GUI size of the capture (owner 08.10.2026). Windows stay the same.
HUD_LABELS = {"Teleporter": ("teleport",), "Shop": ("shop",), "Pets": ("pets",), "Items": ("items",),
              "Achiev": ("achiev",), "Index": ("index",), "Guild": ("guild",), "Boosts": ("boosts",),
              "G. Quests": ("quests",), "Promotion": ("promotion",), "Equip Best": ("equip", "best")}
HUD_AREAS = ([0.0, 0.25, 0.3, 0.8], [0.0, 0.78, 0.3, 1.0], [0.3, 0.72, 0.7, 1.0])   # bar on the left, bottom left, middle


def _label_like(word: str, key: str) -> bool:
    """Label matches (start, small misreads like “OUESTS” for “QUESTS” allowed)."""
    if word.startswith(key):
        return True
    head = word[:len(key)]
    return len(key) >= 5 and len(head) == len(key) and difflib.SequenceMatcher(None, head, key).ratio() >= 0.8


def hud_locate(words: list[tuple[str, list[float]]]) -> dict[str, list[float]]:
    """Position of the edge buttons from read labels: the icon sits right above its name.
    Returns name -> area of the icon (fractions of the window)."""
    norm = [(re.sub(r"[^a-z]", "", w.lower()), b) for w, b in words]
    out: dict[str, list[float]] = {}
    for name, parts in HUD_LABELS.items():
        for w, b in norm:
            if not _label_like(w, parts[0]):
                continue
            box = list(b)
            if len(parts) > 1:                            # “Equip Best”: second word to the right
                nxt = next((b2 for w2, b2 in norm if _label_like(w2, parts[1]) and 0 <= b2[0] - box[2] < 0.03
                            and abs(b2[1] - box[1]) < 0.015), None)
                if nxt is None:
                    continue
                box = [box[0], min(box[1], nxt[1]), nxt[2], max(box[3], nxt[3])]
            lh = box[3] - box[1]
            cx = (box[0] + box[2]) / 2
            half = max(box[2] - box[0], 2.4 * lh) / 2
            out[name] = [round(v, 4) for v in (cx - half, max(0.0, box[1] - 3.0 * lh), cx + half, box[1])]
            break
    return out


def _words_sharp(frame: np.ndarray, area: list[float], ocr) -> list[tuple[str, list[float]]]:
    """Words in an area, small areas read at twice the size (tiny labels at GUI 50 %)."""
    fh, fw = frame.shape[:2]
    x0, y0, x1, y1 = area
    crop = frame[int(y0 * fh):int(y1 * fh), int(x0 * fw):int(x1 * fw)]
    if crop.size == 0:
        return []
    f = 2.0 if crop.shape[0] < 400 else 1.0
    big = crop if f == 1.0 else cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return [(w, [x0 + b[0] * (x1 - x0), y0 + b[1] * (y1 - y0), x0 + b[2] * (x1 - x0), y0 + b[3] * (y1 - y0)])
            for w, b in vision.words_in(big, [0.0, 0.0, 1.0, 1.0], ocr)]




def user_moved(cursor: tuple[int, int], pt: tuple[int, int], rect: Optional[tuple[int, int, int, int]]
               ) -> Optional[bool]:
    """Did the user move the mouse? False = the cursor is still where the macro put it; None = Roblox put it in the
    middle of the window by itself (happens when opening/closing some windows, e.g. after raid windows and the pets
    inventory – exploring aborted there without anyone touching anything, owner 08.10.2026); True = real movement."""
    if abs(pt[0] - cursor[0]) <= USER_MOVE_PX and abs(pt[1] - cursor[1]) <= USER_MOVE_PX:
        return False
    if rect is not None:
        left, top, right, bottom = rect
        cx, cy = (left + right) / 2, (top + bottom) / 2
        if abs(pt[0] - cx) <= max(12, 0.03 * (right - left)) and abs(pt[1] - cy) <= max(12, 0.03 * (bottom - top)):
            return None
    return True


























class Navigator(RaidMixin, GigsMixin, GuildMixin):
    def __init__(self, source_factory: Callable, window_title: str, ocr_factory: Callable,
                 log: Callable[[str], None], uimap: Optional[UiMap] = None) -> None:
        self.source_factory = source_factory              # () -> image source (grab(rois, full, timeout))
        self.window_title = window_title
        self.ocr_factory = ocr_factory
        self._ui_log = log
        self.map = uimap or UiMap.load()
        self._halt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._source = None
        self._ocr = None
        self._hwnd = None
        self._cursor: Optional[tuple[int, int]] = None
        self._names: dict[bytes, str] = {}
        self._menu: Optional[vision.MenuFrame] = None
        self._rows: Optional[vision.RowFinder] = None
        self._templates: list = []
        self.raid_count: Optional[Callable[[], int]] = None     # number of counted raid ends (monitoring)
        self.monitoring: Optional[Callable[[], bool]] = None    # is monitoring running?
        self.start_monitoring: Optional[Callable[[], None]] = None   # start monitoring (via the UI)
        self.set_raid: Optional[Callable[[str], None]] = None        # set the raid name for the statistics
        self.wave_visible: Optional[Callable[[], bool]] = None       # is the monitoring reading a wave right now?
        self._in_raid: Optional[str] = None               # target of the raid the macro is farming right now
        self.gigs_next = 0.0                              # Fixer Gigs: check again at this time at the earliest (time.time)
        self._side_steps: list = []                      # routine: steps to run inside the current raid
        self.gig_slots: list[dict] = []                  # last reading per slot (gig_slot_states) – pills on the start page
        self.guild_day = ""                              # guild missions: PC date (YYYY-MM-DD) of the last claim
        self.guild_retry = 0.0                            # … and not before this time today (time.time)
        self.state_path: Optional[Path] = None            # times of the collections (survive restarts)
        self.queue_pos: Optional[int] = None              # routine: the task running right now (for the display)
        self.auto_gigs: Callable[[], bool] = lambda: False     # switch “Auto collect” (settings)
        self._hud: dict[str, list[float]] = {}           # found edge buttons (per image size)
        self.forbidden: list[list[float]] = []            # no-go zones (Leave, Kick …): never click, never hover
        self._hud_shape: Optional[tuple] = None
        self.auto_guild: Callable[[], bool] = lambda: False

    def log(self, text: str) -> None:
        _log.info("Macro: %s", text)
        self._ui_log(text)

    # ------------------------------------------------------------------ Control
    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._halt.set()

    def start(self, label: str, job: Callable[[], None]) -> bool:
        if self.busy:
            return False
        self._halt.clear()
        self._thread = threading.Thread(target=self._run, args=(label, job), daemon=True, name="Automatik")
        self._thread.start()
        return True

    def close_menu(self) -> bool:
        return self.start(tr("Close menu"), self._close_any)

    def explore(self, minutes: float, data_dir, revisit: bool = True) -> bool:
        """Explore: open, classify and close new worlds/windows by itself (explorer.py)."""
        from .explorer import Explorer
        return self.start(tr("Explore ({minutes} min)", minutes=minutes),
                          lambda: Explorer(self, minutes, data_dir, full=revisit).run())

    def progression(self) -> bool:
        return self.start(tr("Progressions: Auto All"), self._progression)

    def _progression(self) -> None:
        """Open the first progression window, press “Auto All”, close – applies to all progressions."""
        window = self.map.first_progression()
        if window is None:
            raise Stop(tr("No progression known yet – run “Explore” once."))
        self._open(window)
        try:
            self._press(window, ("auto", "all"), ("autoall",))
        except Stop:
            self._snap("progression")                     # image for troubleshooting (debug/makro_progression_*.jpg)
            raise
        time.sleep(AUTO_SETTLE)
        self._close_any()

    def map_opened(self, button: dict) -> bool:
        return self.map.window_for(button) is not None

    def run_queue(self, tasks: list[dict], loop: bool = False) -> bool:
        """Routine: tasks one after another; with loop from the start again, until “Stop”/Esc/mouse. Tasks see
        task_label."""
        tasks = [dict(t) for t in tasks if t.get("kind") in TASK_KINDS]
        if not tasks:
            return False
        return self.start(tr("Farm routine ({count} steps)", count=len(tasks)), lambda: self._queue(tasks, loop))

    def _queue(self, tasks: list[dict], loop: bool) -> None:
        try:
            self._queue_rounds(tasks, loop)
        finally:
            self.queue_pos = None

    def _queue_rounds(self, tasks: list[dict], loop: bool) -> None:
        rounds = 0
        while True:
            rounds += 1
            if loop:
                self.log(tr("Round {n} starts.", n=rounds))
            done_in_raid: set[int] = set()
            for i, task in enumerate(tasks):
                if i in done_in_raid:                     # already ran inside the raid before
                    continue
                self.queue_pos = i
                self.log(tr("Step {n}/{count}: {task}", n=i + 1, count=len(tasks), task=task_label(task)))
                side = raid_side_steps(tasks, i)
                following = next_task(tasks, side[-1] if side else i, loop)
                self._side_steps = [(j, tasks[j], len(tasks)) for j in side]   # run by _raid_task inside the raid
                done_in_raid.update(side)
                self._run_extras()                        # due gigs/guild first
                for attempt in (1, 2):                    # retry once, then skip
                    try:
                        self._task(task, following)
                        break
                    except UserStop:
                        raise
                    except Stop as exc:
                        if attempt == 2:
                            self.log("⚠ " + tr("Skipped: {reason}", reason=exc))
                        else:
                            self.log("⚠ " + tr("{reason} – trying once more.", reason=exc))
                            self._close_any_quiet()
                if self._side_steps:                      # the raid failed before its side steps: run them normally
                    done_in_raid.difference_update(j for j, _t, _c in self._side_steps)
                    self._side_steps = []
                time.sleep(0.6)                           # give the game a moment
            if not loop:
                return

    def _task(self, task: dict, following: Optional[dict] = None) -> None:
        kind = task.get("kind")
        if kind == "wait":
            self._idle_wait(float(task.get("seconds", 60)))
            return
        self._focus()                                     # after waiting/Anti-AFK bring Roblox to the front again
        if kind == "raid":
            self._raid_task(task, following)
        elif kind == "progression":
            self._progression()
        elif kind == "autoroll":
            self._autoroll(self._window(task.get("target", "")),
                           keep_teleporter=bool(following) and following.get("kind") == "autoroll")

    # ------------------------------------------------------------------ Tasks in the window
    def _window_area(self, window: dict) -> tuple[list[float], np.ndarray]:
        """Position of the open window (standard frame, template or full screen) and the current image."""
        frame = self._frame()
        kind, st = self._screen(frame)
        if kind == "template":
            return st.window["roi"], frame
        if kind == "menu":
            return st[0], frame
        return [0.0, 0.0, 1.0, 1.0], frame

    def _press(self, window: dict, *labels: tuple[str, ...]) -> str:
        """Find a button in the open window by its label and press it (e.g. (“auto", “roll”), (“join",)).
        Multi-part labels: words side by side in one row. Returns the label pressed."""
        roi, frame = self._window_area(window)
        words = vision.words_in(frame, roi, self._ocr)
        from .knowledge import is_forbidden
        words = [(w, b) for w, b in words if not is_forbidden(w)]       # never “Leave” & co. as a hit
        norm = [(re.sub(r"[^a-z0-9]", "", w.lower()), b) for w, b in words]
        for label in labels:
            for i, (w, box) in enumerate(norm):
                if w != label[0] and not (len(label[0]) >= 5 and len(label) == 1 and
                                          difflib.SequenceMatcher(None, w, label[0]).ratio() >= 0.85):
                    continue                              # small misreads allowed (“Persona1” for “Personal”)
                boxes = [box]
                for part in label[1:]:                    # next word to the right, same row
                    nxt = next((b for v, b in norm if v == part and 0 <= b[0] - boxes[-1][2] < 0.03
                                and abs((b[1] + b[3]) / 2 - (boxes[-1][1] + boxes[-1][3]) / 2) < 0.015), None)
                    if nxt is None:
                        boxes = []
                        break
                    boxes.append(nxt)
                if boxes:
                    area = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                            max(b[3] for b in boxes)]
                    text = " ".join(label)
                    self.log(tr("Clicking “{button}”.", button=text))
                    self._click_roi(area)
                    return text
        raise Stop(tr("Button “{button}” not found in “{name}”.", button=" / ".join(" ".join(x) for x in labels),
                      name=window["name"]))

    def _autoroll(self, window: dict, keep_teleporter: bool = False) -> None:
        """Open the window, press “Auto Roll” (gacha, titans) or “Auto!” (pets), close right away – the game keeps
        rolling in the background. keep_teleporter: another Auto Roll follows – only close the roll window, the
        teleporter stays open for it (owner 09.10.2026: it was closed and reopened in between)."""
        self._open(window)
        auto = self.map.element(window, "Auto!")
        if auto is not None:
            self.log(tr("Clicking “Auto!”."))
            self._click_roi(auto["roi"])
        else:
            self._press(window, ("auto", "roll"), ("autoroll",), ("auto",))
        time.sleep(AUTO_SETTLE)
        self.log(tr("Auto-roll keeps running in the background – closing the menu."))
        self._close_any(keep_teleporter)


    # ------------------------------------------------------------------ Raid: gear, Auto Retry, Auto Leave








    # ------------------------------------------------------------------ Auto collect (own switches)

    def due_extras(self) -> list[str]:
        """Due extra tasks: Fixer Gigs (by their times) and guild missions (once per PC day) – not tasks of the
        routine but switches of their own; they run between the tasks and while a raid is farming."""
        now = time.time()
        due = []
        if self.auto_gigs() and (now >= self.gigs_next or len(self.gig_slots) < len(GIG_SLOT_BOXES)) \
                and self._gigs_window() is not None:
            due.append("gigs")
        if self.auto_guild() and now >= self.guild_next:
            due.append("guild")
        return due

    def run_extras(self) -> bool:
        """From the UI when nothing else is running."""
        return self.start(tr("Auto collect"), self._run_extras)

    def hud_roi(self, button: dict) -> list[float]:
        """Where is this edge button right now? Searched once per window size via the labels (two areas, ~0.2 s),
        remembered afterwards; not found = position from the map."""
        frame = self._frame()
        if self._hud_shape != frame.shape or button["name"] not in self._hud:
            words = [w for area in HUD_AREAS for w in _words_sharp(frame, area, self._ocr)]
            found = hud_locate(words)
            if self._hud_shape != frame.shape:
                self._hud = {}
            self._hud.update(found)
            self._hud_shape = frame.shape
            if found:
                _log.info("Edge buttons found: %s", ", ".join(sorted(found)))
        return self._hud.get(button["name"], button["roi"])

    def _run_extras(self) -> None:
        for kind in self.due_extras():
            self._focus()
            try:
                if kind == "gigs":
                    self._gigs()
                else:
                    claimed = self._guild_claim()
                    if claimed:                           # done for today (PC date) – again on the next day
                        self.guild_day, self.guild_retry = time.strftime("%Y-%m-%d"), 0.0
                        self.log(tr("Guild: done for today – next visit tomorrow."))
                    else:                                 # missions not finished yet: look again later today
                        self.guild_retry = time.time() + GUILD_RETRY
                        self.log(tr("Guild: nothing to claim yet – next try in {time}.", time=fmt_wait(GUILD_RETRY)))
                    self._save_state()
            except UserStop:
                raise
            except Stop as exc:
                self.log("⚠ " + tr("{task}: {reason} – next try in 15 min",
                                   task=tr("Fixer Gigs") if kind == "gigs" else tr("Guild"), reason=exc))
                if kind == "gigs":
                    self.gigs_next = time.time() + EXTRA_RETRY
                else:
                    self.guild_retry = time.time() + EXTRA_RETRY
                self._save_state()
                self._close_any_quiet()

    def _extras_while_waiting(self) -> None:
        """While waiting (raid farming, “Pause”): slot in due extra tasks, then keep waiting."""
        if not self.due_extras():
            return
        _ACTIVE.set()
        try:
            self._run_extras()
        finally:
            _ACTIVE.clear()

    # ------------------------------------------------------------------ Raid (one task instead of four)



    # ------------------------------------------------------------------ Claim helpers
    def _words(self) -> tuple[list[tuple[str, list[float]]], list[float]]:
        roi, frame = self._window_area({"name": "?"})
        return vision.words_in(frame, roi, self._ocr), roi

    def _find(self, words, *wanted: str) -> Optional[list[float]]:
        want = {w.lower() for w in wanted}
        return next((b for w, b in words if re.sub(r"[^a-z]", "", w.lower()) in want), None)

    def _claim_all(self, where: str, words: Optional[list] = None) -> int:
        """Press all visible “Claim” buttons: all of one reading in one go, from the bottom up (a claimed entry that
        moves or disappears only shifts the ones below it – those are done already), then read once more for
        newly visible ones. words: a reading of this page that is still fresh (saves one text recognition)."""
        count = 0
        while count < CLAIM_LIMIT:
            if words is None:
                words, _roi = self._words()
            norm = [(re.sub(r"[^a-z]", "", w.lower()), b) for w, b in words]
            boxes = sorted((b for w, b in norm if w == "claim"), key=lambda b: (-b[1], -b[0]))
            if not boxes:
                break
            for box in boxes[:CLAIM_LIMIT - count]:
                self.log(tr("Clicking “{button}”.", button="Claim"))
                self._click_roi(box)
                count += 1
                time.sleep(CLAIM_GAP)
            time.sleep(CLAIM_SETTLE)
            words = None
        self.log(tr("{where}: claimed {count}×.", where=where, count=count))
        return count

    def _close_any_quiet(self) -> None:
        try:
            self._close_any()
        except Stop:
            pass

    def _snap(self, tag: str) -> None:
        """Image for troubleshooting (debug/makro_<tag>_<time>.jpg) – for unknown steps."""
        try:
            from .app_paths import debug_dir
            frame = self._frame()
            small = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            path = debug_dir() / f"makro_{tag}_{time.strftime('%H%M%S')}.jpg"
            cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(str(path))
        except Exception:  # noqa: BLE001 – only a debugging aid
            pass

    # ------------------------------------------------------------------ Guild: missions



    # ------------------------------------------------------------------ Fixer Gigs (W21)




    # ------------------------------------------------------------------ Collection times (survive restarts)
    def _load_state(self) -> None:
        if self.state_path is None:
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.gigs_next = float(data.get("gigs_next", 0) or 0)
        slots = data.get("gig_slots")
        self.gig_slots = [x for x in slots if isinstance(x, dict)] if isinstance(slots, list) else []
        self.guild_day = str(data.get("guild_day", "") or "")          # older files (“guild_next”): due right away
        self.guild_retry = float(data.get("guild_retry", 0) or 0)

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        try:
            self.state_path.write_text(json.dumps({"gigs_next": self.gigs_next, "gig_slots": self.gig_slots,
                                                   "guild_day": self.guild_day,
                                                   "guild_retry": self.guild_retry}),
                                       encoding="utf-8")
        except OSError:
            pass





    def _idle_wait(self, seconds: float) -> None:
        """Wait without input: mouse/window free, Anti-AFK may run meanwhile; Esc/“Stop” abort."""
        _ACTIVE.clear()
        try:
            end = time.monotonic() + max(0.0, seconds)
            next_check = time.monotonic() + 5
            while time.monotonic() < end:
                if time.monotonic() >= next_check:
                    next_check = time.monotonic() + 5
                    self._extras_while_waiting()
                if self._halt.wait(0.25):
                    raise UserStop(tr("Stopped."))
                if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                    raise UserStop(tr("Cancelled (Esc)."))
        finally:
            _ACTIVE.set()

    def _focus(self) -> None:
        from .antiafk import _bring_to_front
        u32 = ctypes.windll.user32
        u32.GetForegroundWindow.restype = wintypes.HWND
        if u32.GetForegroundWindow() != self._hwnd:
            if not _bring_to_front(self._hwnd):
                raise Stop(tr("Could not bring Roblox to the front."))
            time.sleep(0.25)
        self._cursor = None                               # the mouse may have moved between the tasks

    def _run(self, label: str, job: Callable[[], None]) -> None:
        self.log("▶ " + label)
        _ACTIVE.set()
        try:
            self._prepare()
            job()
            self.log("✔ " + tr("Done."))
        except Stop as exc:
            self.log("■ " + str(exc))
        except Exception as exc:  # noqa: BLE001 – never let the thread die hard
            _log.exception("Macro: unexpected error in “%s”", label)   # with the code location for the log
            self.log("✖ " + tr("Error: {error}", error=exc))
        finally:
            _ACTIVE.clear()
            if self._source is not None:
                try:
                    self._source.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._source = None
            winapi.trim_memory()                          # frames/crops of the run: give the memory back right away

    def _prepare(self) -> None:
        if not self.map.entries:
            raise Stop(tr("The UI map is missing."))
        self._hwnd = winapi.find_window(self.window_title)
        if self._hwnd is None:
            raise Stop(tr("Roblox window not found"))
        if winapi.is_minimized(self._hwnd):
            raise Stop(tr("Roblox is minimized"))
        if self._ocr is None:
            self._ocr = self.ocr_factory()                # the monitoring's (shared, thread-safe – saves a model)
        if self._menu is None:
            lists = self.map.list_windows()
            if not lists:
                raise Stop(tr("The map has no teleporter with worlds."))
            lw = lists[0]
            img = self.map.image(lw)
            row = next((r for r in self.map.rows(lw) if self.map.image(r) is not None), None)
            if img is None or row is None:
                raise Stop(tr("The map is missing recognition images."))
            self._menu = vision.MenuFrame(lw, img, self._ocr)
            self._rows = vision.RowFinder(row, self.map.image(row))
            self._templates = vision.template_menus(self.map)
        self._source = self.source_factory()
        from .antiafk import _bring_to_front
        if not _bring_to_front(self._hwnd):
            raise Stop(tr("Could not bring Roblox to the front."))
        time.sleep(0.25)
        self._cursor = None

    # ------------------------------------------------------------------ Image + state
    def _frame(self) -> np.ndarray:
        self._check()
        for timeout in (1.5, 3.0):                       # under heavy game load an image sometimes comes too late
            res = self._source.grab([], full=True, timeout=timeout)
            if res is not None and res.full is not None:
                self._frame_size = (res.full.shape[1], res.full.shape[0])   # clicks use the matching area (_point)
                return res.full
        raise Stop(tr("No image from the Roblox window."))

    def _screen(self, frame: np.ndarray) -> tuple[str, object]:
        """("template", template) | ("menu", (position, title, x)) | ("none", None)."""
        for t in self._templates:
            if t.seen(frame):
                return "template", t
        st = self._menu.state(frame, self._ocr)
        return ("menu", st) if st is not None else ("none", None)

    # ------------------------------------------------------------------ Paths
    def _window(self, name: str) -> dict:
        w = self.map.container(name)
        if w is None:
            raise Stop(tr("“{name}” is unknown yet.", name=name))
        return w

    def _open(self, window: dict) -> None:
        """Open a window: via its button – if it is in a world row, open the teleporter and scroll to the world first;
        if it is in another window, open that one first."""
        if self._is_open(window, self._frame()):
            self.log(tr("“{name}” is already open.", name=window["name"]))
            return
        button = self.map.opener_of(window)
        if button is None:
            raise Stop(tr("No button known for “{name}”.", name=window["name"]))
        holder = self.map.parent(button)
        if holder is not None and holder.get("name") == window.get("name"):
            holder = None                                 # button accidentally registered “inside” its own window
        if holder is not None and holder.get("kind") == ROW:
            row_list = self.map.parent(holder)
            self._open_list(row_list)
            box = self._scroll_to(row_list, holder)
            self.log(tr("Found world “{world}” – clicking “{button}”.", world=holder["name"], button=button["name"]))
            self._click_rel(box, button["rel"])
        else:
            if holder is not None and not self._is_open(holder, self._frame()):
                self._open(holder)
            elif holder is None:
                self._close_any()
            self.log(tr("Clicking “{button}”.", button=button["name"]))
            is_hud = (button.get("extra") or {}).get("hud")
            self._click_roi(self.hud_roi(button) if is_hud else button["roi"])
        self._wait_open(window)

    def _open_list(self, row_list: dict) -> None:
        kind, st = self._screen(self._frame())
        if kind == "menu" and self._menu.is_base(st[1]):
            return                                        # the teleporter is already open
        if kind != "none":
            self._close_any()
        opener = self.map.opener_of(row_list)
        if opener is None:
            raise Stop(tr("No button known for “{name}”.", name=row_list["name"]))
        self.log(tr("Opening “{name}”.", name=row_list["name"]))
        self._click_roi(opener["roi"])
        end = time.monotonic() + OPEN_TIMEOUT
        while time.monotonic() < end:
            time.sleep(STEP_WAIT)
            kind, st = self._screen(self._frame())
            if kind == "menu" and self._menu.is_base(st[1]):
                return
        raise Stop(tr("“{name}” did not open.", name=row_list["name"]))

    def _visible_rows(self, frame: np.ndarray, row_list: dict) -> list[tuple[dict, list[float]]]:
        rows = self.map.rows(row_list)
        out = []
        for r in self._rows.find(frame, row_list["roi"]):
            key = (cv2.resize(cv2.cvtColor(r.image, cv2.COLOR_BGR2GRAY), (96, 12)) // 16).tobytes()
            name = self._names.get(key)
            if name is None:
                name = self._names[key] = vision.read_row_name(r.image, self._ocr)
            hit = match_row(name, rows)
            if hit is not None:
                out.append((hit, r.roi))
        return out

    def _scroll_to(self, row_list: dict, target: dict) -> list[float]:
        """Scroll to the world row and return its current position. First the mouse wheel over the list (move the mouse
        before, otherwise Roblox ignores the wheel); if the list doesn't move with it, drag the scroll bar."""
        want = world_number(target["name"])
        x0, y0, x1, y1 = row_list["roi"]
        over = ((x0 + x1) / 2, (y0 + y1) / 2)
        last = None
        stuck = 0
        use_bar = False
        for step in range(MAX_SCROLLS):
            frame = self._frame()
            visible = self._visible_rows(frame, row_list)
            for row, roi in visible:
                if row["name"] == target["name"]:
                    return roi
            numbers = [n for n in (world_number(r["name"]) for r, _ in visible) if n is not None]
            if want is None or not numbers:
                direction = -1                            # nothing readable: search downwards
            else:
                direction = -1 if want > max(numbers) else 1
            # compare the position of the visible rows (not only names: small steps show the same worlds)
            layout = tuple((r["name"], round(roi[1], 3)) for r, roi in visible)
            moved = last is None or layout != last
            last = layout
            _log.info("Makro: Schritt %d, sichtbar %s, Ziel %s (%s), Richtung %s, bewegt %s", step,
                      [f"{n}@{y}" for n, y in layout], target["name"], want, "runter" if direction < 0 else "hoch",
                      moved)
            if not moved:
                stuck += 1
                if not use_bar and stuck >= 2:            # the mouse wheel has no effect: try the scroll bar
                    use_bar = self._scrollbar(row_list) is not None
                    if use_bar:
                        self.log(tr("The mouse wheel does not move the list – dragging the scrollbar."))
                        stuck = 0
                if stuck >= 3:
                    raise Stop(tr("World “{world}” not found (list does not move).",
                                  world=target["name"]))
            else:
                stuck = 0
            if use_bar:
                self._drag_scrollbar(row_list, frame, direction)
            else:
                self._wheel(over, direction * SCROLL_NOTCHES)
            time.sleep(0.45)                              # the list glides on
        raise Stop(tr("World “{world}” not found.", world=target["name"]))

    def _scrollbar(self, row_list: dict) -> Optional[dict]:
        return next((e for e in self.map.children(row_list) if e.get("kind") == "Scrollbalken" and e.get("roi")), None)

    def _drag_scrollbar(self, row_list: dict, frame: np.ndarray, direction: int) -> None:
        """Find the handle of the scroll bar (brightest part of the track) and drag it up/down a bit."""
        bar = self._scrollbar(row_list)
        if bar is None:
            raise Stop(tr("No scrollbar in the map."))
        fh, fw = frame.shape[:2]
        x0, y0, x1, y1 = bar["roi"]
        strip = frame[int(y0 * fh):int(y1 * fh), max(0, int(x0 * fw) - 2):int(x1 * fw) + 2]
        if strip.size == 0:
            raise Stop(tr("No scrollbar in the map."))
        rows = strip.mean(axis=(1, 2))                    # brightness per image row
        bright = rows > (np.median(rows) + 25)
        ys = np.flatnonzero(bright)
        if ys.size:
            grip = (ys[0] + ys[-1]) / 2 / len(rows)       # center of the handle (share of the track)
        else:
            grip = 0.0 if direction < 0 else 1.0          # handle not recognizable: grab it at the end
        start = (x0 + x1) / 2, y0 + grip * (y1 - y0)
        delta = (y1 - y0) * BAR_STEP * (1 if direction < 0 else -1)
        end = start[0], min(y1, max(y0, start[1] + delta))
        _log.info("Makro: Scrollbalken ziehen %.3f -> %.3f (Griff %s)", start[1], end[1], bool(ys.size))
        self._drag(start, end)

    def _drag(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        self._check()
        sx, sy = self._point(*start)
        ex, ey = self._point(*end)
        u32 = ctypes.windll.user32
        u32.SetCursorPos(sx - 2, sy - 2)
        for _ in range(3):
            _mouse(0x0001, 1, 1)
            time.sleep(0.025)
        u32.SetCursorPos(sx, sy)
        time.sleep(0.06)
        _mouse(0x0002)                                    # press
        steps = 12
        for k in range(1, steps + 1):                     # drag evenly (Roblox needs intermediate steps)
            u32.SetCursorPos(sx, int(sy + (ey - sy) * k / steps))
            _mouse(0x0001, 0, 0)
            time.sleep(0.02)
        time.sleep(0.05)
        _mouse(0x0004)                                    # release
        self._cursor = (ex, ey)

    def _is_open(self, window: dict, frame: np.ndarray) -> bool:
        kind, st = self._screen(frame)
        template = self.map.template_of(window)
        if kind == "template":
            return template is not None and st.window["name"] == template["name"]
        if kind == "menu" and template is None:
            if (window.get("extra") or {}).get("template"):
                return False
            if self.map.list_windows() and window["name"] == self.map.list_windows()[0]["name"]:
                return self._menu.is_base(st[1])
            alias = self._title_alias.get(window["name"]) if hasattr(self, "_title_alias") else None
            return vision.similar_title(st[1], window["name"]) or bool(alias and vision.similar_title(st[1], alias))
        return False

    def _wait_open(self, window: dict) -> None:
        end = time.monotonic() + OPEN_TIMEOUT
        seen, last = "", ""
        while time.monotonic() < end:
            time.sleep(STEP_WAIT)
            frame = self._frame()
            if self._is_open(window, frame):
                self.log(tr("“{name}” is open.", name=window["name"]))
                return
            kind, st = self._screen(frame)
            if kind == "menu" and st[1] and not self._menu.is_base(st[1]):
                seen = st[1]
                if seen == last:                          # the same other title twice: that's the window
                    break                                 # (raids: “Defense Mode” for “… Defense”) – don't wait 5 s
                last = seen
        if seen:
            if not hasattr(self, "_title_alias"):
                self._title_alias = {}
            self._title_alias[window["name"]] = seen      # next time it counts as open right away                                          # a menu is open, but the title doesn't match exactly
            self.log(tr("“{title}” is open – I was looking for “{name}”.", title=seen, name=window["name"]))
            return
        raise Stop(tr("“{name}” did not open.", name=window["name"]))

    def _unlock_camera(self) -> None:
        """Leave first person: if Roblox holds the cursor in the middle (camera fully zoomed in), windows can't be
        clicked anymore. Mouse wheel back = zoom the camera out."""
        self.log(tr("The camera is stuck in first person – zooming out."))
        for _ in range(4):
            self._wheel((0.5, 0.5), -5)
            time.sleep(0.15)
        self._warped = 0.0
        self._cursor = None

    def _close_any(self, keep_teleporter: bool = False) -> None:
        """Close everything that is open – with keep_teleporter=True stop as soon as only the teleporter is left."""
        for attempt in range(4):
            if attempt == 2 and time.monotonic() - getattr(self, "_warped", 0.0) < 10:
                self._unlock_camera()                     # not closed twice and the cursor is held
            kind, st = self._screen(self._frame())
            if kind == "none":
                return
            if keep_teleporter and kind == "menu" and self._menu.is_base(st[1]):
                return
            if kind == "template":
                close = self.map.close_element(st.window)
                if close is None:
                    raise Stop(tr("No close button in “{name}”.", name=st.window["name"]))
                self.log(tr("Closing “{name}”.", name=st.window["name"]))
                self._click_roi(close["roi"])
            else:
                self.log(tr("Closing “{name}”.", name=st[1] or "?"))
                self._click(st[2])
            time.sleep(0.6)
        raise Stop(tr("The menu won't close."))

    def _close_after_auto(self, window: dict) -> None:
        """Close right after “Auto!”: the game keeps rolling in the background (until the yen run out). Waiting would
        take unnecessarily long (owner's wish 07.10.2026)."""
        close = self.map.close_element(window)
        if close is None:
            return                                        # map incomplete: leave it open
        time.sleep(AUTO_SETTLE)                           # let the game process the click on “Auto!”
        self.log(tr("Auto-roll keeps running in the background – closing the menu."))
        self._click_roi(close["roi"])

    # ------------------------------------------------------------------ Input (only with Roblox in front)
    def _check(self) -> None:
        if self._halt.is_set():
            raise UserStop(tr("Stopped."))
        u32 = ctypes.windll.user32
        if u32.GetAsyncKeyState(0x1B) & 0x8000:           # Esc
            raise UserStop(tr("Cancelled (Esc)."))
        if self._cursor is not None:
            pt = wintypes.POINT()
            u32.GetCursorPos(ctypes.byref(pt))
            rect = winapi.capture_rect(self._hwnd, getattr(self, "_frame_size", None)) if self._hwnd else None
            moved = user_moved(self._cursor, (pt.x, pt.y), rect)
            if moved is None:                             # Roblox put the cursor in the middle by itself
                _log.info("Macro: the game moved the cursor to the middle of the window – no abort.")
                self._cursor = (pt.x, pt.y)
                self._warped = time.monotonic()
            elif moved:
                raise UserStop(tr("Cancelled – the mouse was moved."))
        u32.GetForegroundWindow.restype = wintypes.HWND
        if u32.GetForegroundWindow() != self._hwnd:
            raise UserStop(tr("Cancelled – Roblox is no longer in the foreground."))

    def _point(self, fx: float, fy: float) -> tuple[int, int]:
        rect = winapi.capture_rect(self._hwnd, getattr(self, "_frame_size", None))
        if rect is None:
            raise Stop(tr("Roblox window not found"))
        left, top, right, bottom = rect
        return int(left + fx * (right - left)), int(top + fy * (bottom - top))

    def _click_roi(self, roi: list[float]) -> None:
        self._click(((roi[0] + roi[2]) / 2, (roi[1] + roi[3]) / 2))

    def _click_rel(self, box: list[float], rel: list[float]) -> None:
        x0, y0, x1, y1 = box
        self._click((x0 + (rel[0] + rel[2]) / 2 * (x1 - x0), y0 + (rel[1] + rel[3]) / 2 * (y1 - y0)))

    def _guard(self, pos: tuple[float, float]) -> None:
        """Hard block: targets in blocked areas (guild “Leave”, Kick, Delete …) are never approached –
        the mouse jumps straight to the target, so it never passes over other buttons."""
        from .knowledge import inside
        if inside(pos, self.forbidden):
            raise Stop(tr("Blocked area (e.g. “Leave”) – not clicked."))

    def _click(self, pos: tuple[float, float]) -> None:
        self._check()
        self._guard(pos)
        x, y = self._point(*pos)
        u32 = ctypes.windll.user32
        u32.SetCursorPos(x - 3, y - 3)
        time.sleep(0.04)
        for _ in range(3):                                # real movement, otherwise no “hover” in Roblox
            _mouse(0x0001, 1, 1)
            time.sleep(0.025)
        u32.SetCursorPos(x, y)
        self._cursor = (x, y)
        time.sleep(0.07)
        _mouse(0x0002)                                    # press left
        time.sleep(0.06)
        _mouse(0x0004)                                    # release
        time.sleep(0.12)

    def _wheel(self, pos: tuple[float, float], notches: int) -> None:
        self._check()
        self._guard(pos)
        x, y = self._point(*pos)
        u32 = ctypes.windll.user32
        u32.SetCursorPos(x - 3, y - 3)
        for _ in range(3):                                # real movement: otherwise the list doesn't count as “under the
            _mouse(0x0001, 1, 1)                          # mouse” and Roblox ignores the wheel
            time.sleep(0.025)
        u32.SetCursorPos(x, y)
        self._cursor = (x, y)
        time.sleep(0.08)
        step = 1 if notches > 0 else -1
        for _ in range(abs(notches)):
            _mouse(0x0800, data=120 * step)               # MOUSEEVENTF_WHEEL (+ = up, - = down)
            time.sleep(0.05)


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> None:
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    inp = INPUT(type=0)
    inp.mi = MOUSEINPUT(dx, dy, ctypes.c_uint32(data & 0xFFFFFFFF).value, flags, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
