"""Automation (beta, off by default, owner's wish 07.10.2026): walk paths in the game using the UI map (uimap) –
open the teleporter, scroll to the world, click the icon, check that the right menu is open; press “Auto!” in the
pets roll. Input via SendInput (like Anti-AFK, AutoHotkey and autoclickers), only with Roblox in the foreground.
Emergency stop: move the mouse or Esc – every action checks that first.

Runs in its own thread; messages via log(text). Without Qt."""
from __future__ import annotations

import ctypes
import difflib
import json
import logging
import re
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from . import vision, winapi
from .i18n import N_, tr
from .uimap import ROW, UiMap, match_row, world_number

_log = logging.getLogger("macro")

STEP_WAIT = 0.15          # spacing of the checks after a click
OPEN_TIMEOUT = 5.0        # a menu may take this long to open
SCROLL_NOTCHES = 4        # mouse wheel notches per step
BAR_STEP = 0.15           # drag the scroll bar by this share of the track per step
MAX_SCROLLS = 60
USER_MOVE_PX = 25         # mouse this far from the set spot = the user intervenes -> stop
AUTO_SETTLE = 0.8         # after “Auto!” wait briefly, then close (auto roll keeps running in the background)


_ACTIVE = threading.Event()    # a macro run is going on right now (Anti-AFK waits then)


def macro_running() -> bool:
    return _ACTIVE.is_set()


TASK_KINDS = ("raid", "autoroll", "progression", "gigs", "guild_claim", "wait",
              "raid_farm", "raid_leave", "raid_create", "raid_join", "navigate", "pets", "close")   # from raid_farm on: older
RAID_KINDS = ("raid", "raid_farm", "raid_create", "raid_join")     # tasks that lead into a raid/mode
IN_RAID_KINDS = ("autoroll", "progression")      # quick menu tasks that also work inside a raid (owner 09.10.2026)
CLAIM_LIMIT = 8           # at most this many “Claim” per page (protection against endless loops)
CLAIM_GAP = 0.35          # between two “Claim” clicks of one reading
CLAIM_SETTLE = 0.5        # after the clicks of one reading, before reading again
GIGS_PETS = 3             # “Send Pets”: 1 pet per gig, in turn one of the last 3 (owner 08.10.2026)
GUILD_RETRY = 3 * 3600    # guild missions: nothing to claim yet today -> try again this much later (owner 09.10.2026)
GUILD_TAB_WAIT = 0.6      # after switching a guild tab, before reading (was 1 s – owner: too slow)
EXTRA_RETRY = 15 * 60     # after a failure try again this much later at the earliest
RAID_GEAR = Path(__file__).with_name("uimap_static") / "raid_gear.png"   # gear at the top right in a raid (fixed, not from the map)
GEAR_REGION = [0.4, 0.0, 0.9, 0.16]
LEAVE_REGION = [0.35, 0.0, 0.75, 0.2]
GEAR_HIT = 0.75
# raid settings layout (measured 09.10.2026), in widths of the “Auto Leave” label: Auto Retry this far above, the
# field “Wave N” centered this far right/below, half width/height of the field
RAID_LAYOUT = {"dy": 0.464, "field_dx": 1.058, "field_dy": 0.363, "field_hw": 0.45, "field_hh": 0.09}
TOGGLE_TRIES = 24          # looks at the switch color (cheap) – messages pass within a few seconds
GEAR_TRIES = 6            # click the gear again if the menu doesn't open (loading screen swallows clicks)
GEAR_WAIT = 2.0           # wait this long for the menu after each click


def task_label(task: dict) -> str:
    """Display of a routine task."""
    kind = task.get("kind")
    if kind == "autoroll":
        return tr("Auto Roll · {target}", target=task.get("target", "?"))
    if kind == "raid":
        until = task.get("until", "runs")
        text = tr("Farm · {target}", target=task.get("target", "?"))
        if until == "runs":
            text += " · " + tr("{runs} raids", runs=int(task.get("runs", 1)))
        elif until == "minutes":
            text += " · " + tr("{minutes} min.", minutes=int(task.get("minutes", 30)))
        else:
            text += " · " + tr("until stopped")
        if int(task.get("leave_wave", 0)):
            text += " · " + tr("leave from wave {wave}", wave=int(task["leave_wave"]))
        return text + (" · " + tr("join") if task.get("join") else "")
    if kind == "progression":
        return tr("Progressions: Auto All")
    if kind == "gigs":
        return tr("Collect Fixer Gigs")
    if kind == "guild_claim":
        return tr("Guild: claim missions")
    if kind == "raid_farm":
        text = tr("Farm raid: {target} × {runs}", target=task.get("target", "?"), runs=int(task.get("runs", 1)))
        if int(task.get("leave_wave", 0)):
            text += " · " + tr("leave from wave {wave}", wave=int(task["leave_wave"]))
        return text + (" · " + tr("join") if task.get("join") else "")
    if kind == "raid_leave":
        return tr("Leave raid")
    if kind == "raid_create":
        return tr("Start raid: {target}", target=task.get("target", "?"))
    if kind == "raid_join":
        return tr("Join raid: {target}", target=task.get("target", "?"))
    if kind == "navigate":
        return tr("Open: {target}", target=task.get("target", "?"))
    if kind == "pets":
        return tr("Roll pets (Auto!): {world}", world=task.get("world", "?"))
    if kind == "close":
        return tr("Close menu")
    if kind == "wait":
        seconds = int(task.get("seconds", 60))
        return tr("Pause · {minutes} min", minutes=seconds // 60) if seconds % 60 == 0 and seconds >= 60 else \
            tr("Pause · {seconds} s", seconds=seconds)
    return str(kind)


class Stop(Exception):
    """Stop (user, timeout, not found) – text = reason for the log."""


class UserStop(Stop):
    """Stopped by the user (stop, Esc, mouse, Roblox not in front) – the routine ends right away."""


def next_task(tasks: list[dict], index: int, loop: bool) -> Optional[dict]:
    """Task after tasks[index] (with loop the first one again), otherwise None."""
    if index + 1 < len(tasks):
        return tasks[index + 1]
    return tasks[0] if loop and len(tasks) > 1 else None


def raid_side_steps(tasks: list[dict], index: int) -> list[int]:
    """Steps right after the raid step tasks[index] that run INSIDE the raid, once its settings are set: Auto Roll
    and Progressions up to the next raid or pause (owner 09.10.2026: “Farm … until stopped” never ended, so the
    gachas/pets after it never started)."""
    if tasks[index].get("kind") != "raid":
        return []
    out = []
    for j in range(index + 1, len(tasks)):
        if tasks[j].get("kind") not in IN_RAID_KINDS:
            break
        out.append(j)
    return out


def leave_before(task: dict, following: Optional[dict]) -> bool:
    """Leave the raid before continuing? Only if a DIFFERENT raid/mode comes next (owner 08.10.2026) –
    for Auto Roll, gigs, guild … you stay in (Auto Retry keeps farming)."""
    if following is None or following.get("kind") not in RAID_KINDS:
        return False
    return following.get("target") != task.get("target")


def _clusters(values: list[float], tol: float) -> list[list[float]]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def pet_tiles(frame: np.ndarray, grid: list[float], words: list[tuple[str, list[float]]]) -> list[list[float]]:
    """Tiles of a pet grid from the name tags (see Navigator._pet_tiles); testable without Qt/OCR."""
    found = [(b, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)) for w, b in words
             if len(re.sub(r"[^A-Za-z]", "", w)) >= 3 and b[3] - b[1] < 0.045]
    # name rows: at least three words with ≥ 4 letters at the same height (image noise drops out that way)
    long_y = [m[1] for (b, m), (w, _x) in zip(found, [x for x in words if len(re.sub(r"[^A-Za-z]", "", x[0])) >= 3
                                                       and x[1][3] - x[1][1] < 0.045]) if len(re.sub(r"[^A-Za-z]", "", w)) >= 4]
    row_y = [float(np.median(c)) for c in _clusters(long_y, 0.02) if len(c) >= 3]
    if not row_y:
        return []
    labels = []                                           # merge the words of one tag (“Kirito Armor”)
    for y in row_y:
        boxes = sorted((b for b, m in found if abs(m[1] - y) <= 0.025), key=lambda b: b[0])
        for b in boxes:
            if labels and abs(labels[-1][1] - y) < 1e-6 and b[0] - labels[-1][2] < 0.02:
                labels[-1][2] = b[2]
            else:
                labels.append([b[0], y, b[2]])
    labels = [(None, ((x0 + x1) / 2, y)) for x0, y, x1 in labels]
    cols = [float(np.median(c)) for c in _clusters([m[0] for _b, m in labels], 0.03)]
    if len(cols) < 2:
        return []
    diffs = sorted(b - a for a, b in zip(cols, cols[1:]) if b - a > 0.04)
    if not diffs:
        return []
    steps = max(1, round((cols[-1] - cols[0]) / diffs[0]))  # smallest spacing ≈ one column (gaps = missing
    pitch = (cols[-1] - cols[0]) / steps                     # names), averaged exactly over the whole width
    cols = [cols[0] + i * pitch for i in range(steps + 1)]
    row_pitch = min((b - a for a, b in zip(row_y, row_y[1:])), default=pitch * 1.75)
    fh, fw = frame.shape[:2]
    tiles = []
    for ly in row_y:
        for cx in cols:
            box = [cx - pitch * 0.45, ly - row_pitch * 0.82, cx + pitch * 0.45, ly + row_pitch * 0.08]
            named = any(box[0] <= m[0] <= box[2] and abs(m[1] - ly) <= 0.025 for _b, m in labels)
            crop = frame[max(0, int(box[1] * fh)):int(box[3] * fh), max(0, int(box[0] * fw)):int(box[2] * fw)]
            if named or (crop.size and vision.sharpness(crop) >= vision.SlotLayout.SHARP_MIN):
                tiles.append([round(v, 4) for v in box])
    return tiles


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


def fmt_wait(seconds: float) -> str:
    """Short waiting time: “45 s”, “18 min”, “1 h 36 min”, “23 h”."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return tr("{n} s", n=seconds)
    minutes = (seconds + 59) // 60
    if minutes < 60:
        return tr("{n} min", n=minutes)
    hours, rest = divmod(minutes, 60)
    return tr("{h} h {m} min", h=hours, m=rest) if rest and hours < 10 else tr("{h} h", h=hours)


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


def parse_timer(text: str) -> Optional[int]:
    """“1:20:40” / “33:57” -> seconds (Fixer Gigs times), otherwise None."""
    m = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})", text.strip())
    if not m:
        return None
    h, mnt, s = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    return h * 3600 + mnt * 60 + s if mnt < 60 and s < 60 else None


# Fixer Gigs: header of every card (“QUICK · 20 MIN”, “STANDARD · 1H”, “BIG JOB · 3H”) -> duration. Which kind comes is
# random (owner 08.10.2026) – so read per card instead of fixed times.
GIG_KINDS = {"quick": 20 * 60, "standard": 3600, "big": 3 * 3600, "bis": 3 * 3600}
GIG_NAMES = {20 * 60: N_("Quick 20 min"), 3600: N_("Standard 1 h"), 3 * 3600: N_("Big Job 3 h")}
GIG_KIND_WORDS = {"job": 3 * 3600, "3h": 3 * 3600, "1h": 3600}
# time line “43:41 left” of a card (fractions of the card frame, measured on the real window); two bands, so a
# slightly different GUI size still hits it
GIG_TIMER_BANDS = ((0.61, 0.70), (0.62, 0.69))
GIG_UNKNOWN = 3 * 3600        # card without a readable header: duration unknown (at most a Big Job)
# the three card frames in the Fixer Gigs window (fractions of the window roi, measured on the real window)
GIG_SLOT_BOXES = ((0.276, 0.347, 0.481, 0.897), (0.496, 0.347, 0.700, 0.897), (0.714, 0.347, 0.919, 0.897))
GIG_REFRESH_MAX = 4 * 3600    # longer “NEW GIGS IN” readings are misreads
GIG_EMPTY_CHECK = 5 * 60      # empty slot without a readable countdown: open the window again this soon


def _gig_kind(word: str) -> Optional[int]:
    """Duration of a card header word – also glued together (“standard1h”, “quick20min”); “JOB”, “3H”, “1H” alone
    count too (owner 09.10.2026: “BIG” of “BIG JOB · 3H” was not read)."""
    return GIG_KIND_WORDS.get(word) or next((d for k, d in GIG_KINDS.items() if word.startswith(k)), None)


def gig_cards(words: list[tuple[str, list[float]]], roi: list[float]) -> list[dict]:
    """The three slots of the Fixer Gigs window, each read on its own (owner 09.10.2026: recognize directly whether a
    gig is running, done, needs pets or the slot is empty). The card frames always sit at the same place in the
    window (GIG_SLOT_BOXES, fractions of the window roi). Per slot: x (center), pitch (slot width), duration (s,
    GIG_UNKNOWN + “unknown” if the header wasn't read), state (“ready”/“open” = needs pets/“working”/“empty”),
    left (position of “left” below the time left), claim/send (button position or None).
    “FINISH NOW” costs currency – never returned."""
    rx, ry, rw, rh = roi[0], roi[1], roi[2] - roi[0], roi[3] - roi[1]
    norm = [(re.sub(r"[^a-z0-9]", "", w.lower()), b) for w, b in words]
    cards = []
    for fx0, fy0, fx1, fy1 in GIG_SLOT_BOXES:
        box = [rx + fx0 * rw, ry + fy0 * rh, rx + fx1 * rw, ry + fy1 * rh]
        inside = [(w, b) for w, b in norm if w and box[0] <= (b[0] + b[2]) / 2 <= box[2]
                  and box[1] <= (b[1] + b[3]) / 2 <= box[3]]
        head_zone = box[1] + 0.2 * (box[3] - box[1])
        duration = next((_gig_kind(w) for w, b in inside if b[1] < head_zone and _gig_kind(w)), None)
        found = {w for w, _b in inside}
        if found & {"ready", "claim"}:
            state = "ready"
        elif found & {"send", "sendpets"}:
            state = "open"
        elif found & {"working", "left", "finish", "finishnow"} or duration is not None:
            state = "working"                             # header without a readable status: running, time unknown
        else:
            state = "empty"
        cards.append({"x": (box[0] + box[2]) / 2, "pitch": box[2] - box[0], "box": box,
                      "duration": duration or GIG_UNKNOWN, "unknown": duration is None, "state": state,
                      "left": next((b for w, b in inside if w == "left"), None),
                      "claim": next((b for w, b in inside if w == "claim"), None),
                      "send": next((b for w, b in inside if w in ("send", "sendpets")), None)})
    return cards


def gig_timer_vote(texts: list[str], duration: int) -> Optional[int]:
    """Time left from several readings of the same line (“43:41 left”, “«3:11 Left”, “2:59:47 left”): every valid
    time counts as one vote, the most frequent wins (a tie: the shorter one – better to come back too early).
    Single readings slip now and then, but rarely the same way."""
    votes: dict[int, int] = {}
    for text in texts:
        for m in re.finditer(r"(?<![\d:])(\d{1,2}:)?\d{1,2}:\d{2}(?![\d:])", text or ""):
            seconds = parse_timer(m.group(0))
            if seconds is not None and 0 < seconds <= duration + 60:
                votes[seconds] = votes.get(seconds, 0) + 1
    if not votes:
        return None
    return min(votes, key=lambda t: (-votes[t], t))


def gig_timer_box(card: dict) -> Optional[list[float]]:
    """Area of the time left (“1:36:38 left”) to the left of “left” – for the exact digit reading."""
    left = card.get("left")
    if left is None:
        return None
    h = left[3] - left[1]
    return [max(card["x"] - 0.4 * card["pitch"], left[0] - 9 * h), left[1] - 0.4 * h, left[0] - 0.1 * h,
            left[3] + 0.4 * h]


def gig_refresh_box(words: list[tuple[str, list[float]]]) -> Optional[list[float]]:
    """Area of the countdown “NEW GIGS IN 52:37” above the cards (time until empty slots get new gigs) – for the
    exact digit reading. None = the line wasn't read."""
    norm = [(re.sub(r"[^a-z0-9:]", "", w.lower()), b) for w, b in words]
    new = next((b for w, b in norm if w == "new"), None)
    if new is None:
        return None
    h = new[3] - new[1]
    row = [(w, b) for w, b in norm if abs((b[1] + b[3]) / 2 - (new[1] + new[3]) / 2) < 0.6 * h
           and new[2] <= b[0] < new[0] + 16 * h]
    timer = next((b for w, b in row if re.search(r"\d:\d", w)), None)       # not “3/3” of “SLOTS”
    if timer is not None:                                 # the general reading found the time: read it exactly there
        before = max((b[2] for w, b in row + [("new", new)] if b[2] <= timer[0] + 0.1 * h), default=0.0)
        return [max(timer[0] - 0.5 * h, before + 0.1 * h), timer[1] - 0.4 * h, timer[2] + 0.8 * h,
                timer[3] + 0.4 * h]                       # not into “IN” (its “N” was read as “1”)
    after = max((b[2] for w, b in row if w in ("gigs", "in")), default=None)
    if after is None:                                     # neither the time nor “GIGS IN” read: don't guess
        return None
    return [after + 0.2 * h, new[1] - 0.4 * h, after + 3.6 * h, new[3] + 0.4 * h]


def gig_refresh_read(words: list[tuple[str, list[float]]]) -> Optional[int]:
    """Fallback: “NEW GIGS IN 52:37” from the general reading (when the exact digit reading fails)."""
    box = gig_refresh_box(words)
    if box is None:
        return None
    for w, b in words:
        if b[0] < box[2] and b[2] > box[0] and b[1] < box[3] and b[3] > box[1]:
            seconds = parse_timer(w)
            if seconds is not None and 0 < seconds <= GIG_REFRESH_MAX:
                return seconds
    return None


def gig_slot_states(cards: list[dict], timers: dict[int, Optional[int]], refresh: Optional[int],
                    now: float) -> list[dict]:
    """What the card shows per slot (pills on the start page), saved in extras_state.json: state as read, “until”
    = end of the running gig or arrival of new gigs (time.time, None = unknown), duration (None = header unread)."""
    out = []
    for i, c in enumerate(cards):
        until = None
        if c["state"] == "working" and timers.get(i):
            until = now + timers[i]
        elif c["state"] == "empty" and refresh is not None and 0 < refresh <= GIG_REFRESH_MAX:
            until = now + refresh
        out.append({"state": c["state"], "until": until, "duration": None if c["unknown"] else c["duration"]})
    return out


def gig_pill(slot: Optional[dict], now: float) -> tuple[str, str]:
    """(kind for the style, text) of one pill: run / done / pet / empty / none."""
    if not slot:
        return "none", "–"
    state, until = slot.get("state"), slot.get("until")
    if state == "working":
        if until is None:
            return "run", tr("running")
        return ("done", tr("done")) if until <= now else ("run", fmt_wait(until - now))
    if state == "ready":
        return "done", tr("done")
    if state == "open":
        return "pet", tr("needs pet")
    if until is not None and until > now:
        return "empty", tr("new in {time}", time=fmt_wait(until - now))
    return "empty", tr("empty")


def gig_next_due(cards: list[dict], timers: dict[int, Optional[int]], refresh: Optional[int] = None) -> int:
    """Seconds until the next visit: smallest valid time left (at most as long as the gig); running gigs without a
    readable time count as 20 min, done ones and ones that need pets right away, empty slots when new gigs come
    (“NEW GIGS IN …”, refresh in seconds; unreadable = GIG_EMPTY_CHECK)."""
    due = []
    for i, card in enumerate(cards):
        if card["state"] == "empty":
            due.append(refresh if refresh is not None and 0 < refresh <= GIG_REFRESH_MAX else GIG_EMPTY_CHECK)
        elif card["state"] != "working":
            due.append(0)
        else:
            t = timers.get(i)
            due.append(t if t is not None and 0 < t <= card["duration"] + 60 else min(card["duration"], 20 * 60))
    return min(due) if due else 20 * 60


def guild_next_time(done_day: str, retry: float, now: float) -> float:
    """Guild missions once per PC day: claimed today (done_day = today's local date) -> next local midnight; on a
    new day right away – unless “nothing to claim yet” set a retry time today."""
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    if done_day == today:
        t = time.localtime(now)
        return time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 0, 0, 0, 0, -1))
    return retry


def complete_raid_labels(out: dict, aspect: float) -> dict:
    """The raid settings always have the same layout: “Auto Retry” above “Auto Leave”, the field “Wave N” below.
    “Wave cleared!” messages often cover part of it (owner 09.10.2026: 4–6 at once) – from one readable label the
    others follow (RAID_LAYOUT, in widths of the “Auto Leave” label; aspect = image width / height). The grey
    field text “Wave 12” is often not read at all: its position is calculated."""
    out = dict(out)
    ref = out.get("leave") or out.get("retry")
    if ref is None:
        return out
    w = ref[2] - ref[0]
    dy = RAID_LAYOUT["dy"] * w * aspect                  # x and y fractions have different scales
    if "leave" not in out:
        r = out["retry"]
        out["leave"] = [r[0], r[1] + dy, r[2], r[3] + dy]
    if "retry" not in out:
        lv = out["leave"]
        out["retry"] = [lv[0], lv[1] - dy, lv[2], lv[3] - dy]
    if "wave" not in out:
        lv = out["leave"]
        cx = lv[0] + RAID_LAYOUT["field_dx"] * w
        cy = (lv[1] + lv[3]) / 2 + RAID_LAYOUT["field_dy"] * w * aspect
        hw, hh = RAID_LAYOUT["field_hw"] * w, RAID_LAYOUT["field_hh"] * w * aspect
        out["wave"] = [cx - hw, cy - hh, cx + hw, cy + hh]
    return out


class Navigator:
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

    def navigate(self, target: str) -> bool:
        return self.start(tr("Navigate to: {target}", target=target), lambda: self._open(self._window(target)))

    def pets_auto(self, world: str, close_after: bool = True) -> bool:
        return self.start(tr("Roll pets: {world}", world=world), lambda: self._pets_auto(world, close_after))

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
        elif kind == "gigs":
            self._gigs()
        elif kind == "guild_claim":
            self._guild_claim()
        elif kind == "autoroll":
            self._autoroll(self._window(task.get("target", "")))
        elif kind == "raid_farm":
            self._raid_farm(self._window(task.get("target", "")), bool(task.get("join")), int(task.get("runs", 1)),
                            int(task.get("leave_wave", 0)))
        elif kind == "raid_leave":
            self._leave_raid()
        elif kind in ("raid_create", "raid_join"):
            self._raid(self._window(task.get("target", "")), join=kind == "raid_join")
        elif kind == "navigate":
            self._open(self._window(task.get("target", "")))
        elif kind == "pets":
            self._pets_auto(task.get("world", ""), bool(task.get("close", True)))
        elif kind == "close":
            self._close_any()

    # ------------------------------------------------------------------ Tasks in the window
    def autoroll(self, target: str) -> bool:
        return self.start(tr("Auto roll: {target}", target=target), lambda: self._autoroll(self._window(target)))

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

    def _autoroll(self, window: dict) -> None:
        """Open the window, press “Auto Roll” (gacha, titans) or “Auto!” (pets), close right away – the game keeps
        rolling in the background."""
        self._open(window)
        auto = self.map.element(window, "Auto!")
        if auto is not None:
            self.log(tr("Clicking “Auto!”."))
            self._click_roi(auto["roi"])
        else:
            self._press(window, ("auto", "roll"), ("autoroll",), ("auto",))
        time.sleep(AUTO_SETTLE)
        self.log(tr("Auto-roll keeps running in the background – closing the menu."))
        self._close_any()

    def _raid(self, window: dict, join: bool) -> None:
        """Open the raid window and press “Create”/“Start” (own raid, costs a key) or “Join”.
        What comes afterwards (lobby, teleport) is logged and saved as an image for troubleshooting."""
        self._open(window)
        if join:
            self._press(window, ("join",))
        else:
            self._press(window, ("create",), ("start",))
        time.sleep(3.0)
        frame = self._frame()
        kind, st = self._screen(frame)
        self.log(tr("Afterwards: {state}", state=(st[1] if kind == "menu" else kind) or "?"))
        try:
            from .app_paths import debug_dir
            path = debug_dir() / f"makro_raid_{time.strftime('%H%M%S')}.jpg"
            small = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(str(path))
        except Exception:  # noqa: BLE001 – only a debugging aid
            pass

    # ------------------------------------------------------------------ Raid: gear, Auto Retry, Auto Leave
    def _gear(self, frame: np.ndarray) -> Optional[list[float]]:
        """Gear at the top right next to wave/timer – only visible in a raid."""
        if not hasattr(self, "_gear_tpl"):
            self._gear_tpl = cv2.imdecode(np.fromfile(str(RAID_GEAR), dtype=np.uint8), cv2.IMREAD_COLOR)
        score, box = vision.find_multiscale(frame, self._gear_tpl, GEAR_REGION)
        return box if score >= GEAR_HIT else None

    def _stable_gear(self, timeout: float = 12.0) -> Optional[list[float]]:
        """Only click the gear once the raid is really running: “Starting defense …” darkens the image and swallows
        clicks. It waits until the monitoring reads a wave (if connected) and the gear is at the same spot twice."""
        end = time.monotonic() + timeout
        last = None
        while time.monotonic() < end:
            self._check()
            gear = self._gear(self._frame())
            wave_ok = self.wave_visible is None or self.wave_visible()
            if gear is not None and wave_ok and last is not None and abs(gear[0] - last[0]) < 0.004                     and abs(gear[1] - last[1]) < 0.004:
                return gear
            last = gear
            time.sleep(0.5)
        return last

    def _labels(self, frame: np.ndarray) -> dict:
        """Labels in the gear menu: {"retry": position, "leave": position, "wave": position of the wave field}."""
        words = vision.words_in(frame, [0.2, 0.1, 0.8, 0.9], self._ocr)
        norm = [(re.sub(r"[^a-z0-9]", "", w.lower()), b) for w, b in words]
        out = {}
        for key, second in (("retry", "retry"), ("leave", "leave")):
            for w, b in norm:
                if w != "auto":
                    continue
                nxt = next((b2 for w2, b2 in norm if w2 == second and 0 <= b2[0] - b[2] < 0.03
                            and abs((b2[1] + b2[3]) / 2 - (b[1] + b[3]) / 2) < 0.015), None)
                if nxt is not None:
                    out[key] = [b[0], min(b[1], nxt[1]), nxt[2], max(b[3], nxt[3])]
                    break
        if "leave" in out:                                # field “Wave 85” right below “Auto Leave”
            lv = out["leave"]
            field = next((b for w, b in norm if w == "wave" and 0 < b[1] - lv[3] < 0.08
                          and abs(b[0] - lv[0]) < 0.12), None)
            if field is not None:
                out["wave"] = field
        return complete_raid_labels(out, frame.shape[1] / frame.shape[0])

    def _open_raid_settings(self) -> dict:
        """Open the gear menu and remember where its parts are (self._raid_labels) – the menu doesn't move, so the
        following steps don't need to read it again (fast, and messages covering it don't matter)."""
        self._raid_labels = {}
        frame = self._frame()
        labels = self._labels(frame)
        if "retry" in labels or "leave" in labels:
            self._raid_labels = labels
            return labels
        gear = self._stable_gear()
        if gear is None:
            raise Stop(tr("No raid gear found – are you in a raid?"))
        self.log(tr("Opening the raid settings (gear)."))
        for attempt in range(GEAR_TRIES):
            if attempt:                                   # loading screen (“Starting defense …”) swallowed the click
                self.log(tr("Gear: no reaction yet (loading screen?) – clicking again."))
                gear = self._gear(self._frame()) or gear
            self._click(((gear[0] + gear[2]) / 2, (gear[1] + gear[3]) / 2))
            end = time.monotonic() + GEAR_WAIT
            while time.monotonic() < end:
                time.sleep(0.3)
                labels = self._labels(self._frame())
                if "retry" in labels or "leave" in labels:   # one readable label is enough (complete_raid_labels)
                    self._raid_labels = labels
                    return labels
        raise Stop(tr("The raid settings did not open."))

    def _set_toggle(self, key: str, on: bool) -> None:
        """Set the switch “Auto Retry”/“Auto Leave” and verify it. Uses the remembered position of the open menu
        and only looks at the switch color – while a message covers it, wait briefly and look again."""
        name = "Auto Retry" if key == "retry" else "Auto Leave"
        clicks = 0
        for _ in range(TOGGLE_TRIES):
            frame = self._frame()
            label = (getattr(self, "_raid_labels", {}) or {}).get(key) or self._labels(frame).get(key)
            if label is None:
                time.sleep(0.3)
                continue
            state = vision.toggle_state(frame, label)
            if state is None:                             # covered by “Wave cleared!”: look again shortly
                time.sleep(0.25)
                continue
            if state == on:
                self.log(tr("{name}: {state}", name=name, state=tr("on") if on else tr("off")))
                return
            if clicks >= 3:
                break
            cy = (label[1] + label[3]) / 2
            self._click((label[2] + 0.05, cy))           # switch to the right of the label
            clicks += 1
            time.sleep(0.5)
        raise Stop(tr("Couldn't switch “{name}” reliably.", name=name))

    def _set_leave_wave(self, wave: int) -> None:
        field = (getattr(self, "_raid_labels", {}) or {}).get("wave") or self._labels(self._frame()).get("wave")
        if field is None:
            raise Stop(tr("Wave field (auto leave) not found."))
        from .antiafk import _key
        self._click_roi(field)
        time.sleep(0.3)
        for _ in range(6):                                # delete the old number
            _key(0x08, True, 0x0E)
            _key(0x08, False, 0x0E)
            time.sleep(0.04)
        scans = {"1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A,
                 "0": 0x0B}
        for ch in str(int(wave)):
            _key(ord(ch), True, scans[ch])
            _key(ord(ch), False, scans[ch])
            time.sleep(0.05)
        _key(0x0D, True, 0x1C)                            # Enter
        _key(0x0D, False, 0x1C)
        self.log(tr("Auto leave from wave {wave}.", wave=wave))
        time.sleep(0.4)

    def _close_raid_settings(self) -> None:
        frame = self._frame()
        labels = self._labels(frame) or (getattr(self, "_raid_labels", {}) or {})   # covered: remembered position
        self._raid_labels = {}
        if not labels:
            return
        anchor = labels.get("retry") or labels.get("leave")
        region = [anchor[0], max(0.0, anchor[1] - 0.2), min(1.0, anchor[2] + 0.25), anchor[1]]
        score, box = vision.find_multiscale(frame, self._menu.x_tpl, region, (0.4, 0.5, 0.6, 0.7, 0.8, 1.0))
        if score >= 0.6 and box is not None:
            self._click_roi(box)                          # pink X at the top right of the menu
        else:
            gear = self._gear(frame)
            if gear is not None:
                self._click_roi(gear)                     # the gear closes it again
        time.sleep(0.6)

    def _leave_raid(self) -> None:
        """Leave the raid: first Auto Retry off (otherwise you are thrown back in), then LEAVE!."""
        self._open_raid_settings()
        self._set_toggle("retry", False)
        self._close_raid_settings()
        box = vision.find_word(self._frame(), LEAVE_REGION, self._ocr, "leave", "leave!")
        if box is None:
            raise Stop(tr("“LEAVE!” not found."))
        self.log(tr("Clicking “{button}”.", button="LEAVE!"))
        # The raid “LEAVE!” at the top middle is wanted (leave the raid). No-go zones only apply while the guild or
        # a window is open while exploring – none is active here (guild “Leave” at the bottom left of the guild window).
        self._click_roi(box)
        time.sleep(3.0)

    def _raid_farm(self, window: dict, join: bool, runs: int, leave_wave: int) -> None:
        """Start/join a raid, Auto Retry on (+ Auto Leave from wave N), wait until the monitoring counted N raid ends,
        then Auto Retry off and leave."""
        if self.monitoring is None or self.raid_count is None or not self.monitoring():
            raise Stop(tr("“Farm raid” needs monitoring to be running (it counts the raids)."))
        self._raid(window, join)
        end = time.monotonic() + 120                      # until you are in the raid (teleport, lobby)
        while self._gear(self._frame()) is None:
            if time.monotonic() > end:
                raise Stop(tr("Did not arrive in the raid."))
            time.sleep(1.0)
        self._open_raid_settings()
        self._set_toggle("retry", True)
        if leave_wave > 0:                                # wave first, then the switch: the game's default is 5 –
            self._set_leave_wave(leave_wave)              # switched on first it could leave too early (owner 09.10.2026)
        self._set_toggle("leave", leave_wave > 0)
        self._close_raid_settings()
        start = self.raid_count()
        self.log(tr("Farming {runs} raids …", runs=runs))
        _ACTIVE.clear()                                   # Anti-AFK may run while waiting
        try:
            last = 0
            while True:
                done = self.raid_count() - start
                if done >= runs:
                    break
                if done != last:
                    last = done
                    self.log(tr("{done}/{runs} raids", done=done, runs=runs))
                if self._halt.wait(2.0):
                    raise UserStop(tr("Stopped."))
                if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                    raise UserStop(tr("Cancelled (Esc)."))
        finally:
            _ACTIVE.set()
        self._focus()
        self._leave_raid()

    # ------------------------------------------------------------------ Auto collect (own switches)
    @property
    def guild_next(self) -> float:
        """Next guild visit: done today (PC date) -> local midnight, otherwise the retry time (0 = right away)."""
        return guild_next_time(self.guild_day, self.guild_retry, time.time())

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
    def _ensure_monitoring(self) -> None:
        if self.monitoring is None or self.raid_count is None:
            raise Stop(tr("Raids need monitoring to run (it counts the raids)."))
        if self.monitoring():
            return
        if self.start_monitoring is None:
            raise Stop(tr("Raids need monitoring to run (it counts the raids)."))
        self.log(tr("Starting monitoring (it counts the raids)."))
        self.start_monitoring()
        end = time.monotonic() + 15
        while not self.monitoring():
            if time.monotonic() > end:
                raise Stop(tr("Monitoring could not be started."))
            self._check()
            time.sleep(0.3)

    def _raid_task(self, task: dict, following: Optional[dict]) -> None:
        """Start/join a raid (unless you are already farming exactly this one), set Auto Retry + Auto Leave, farm to
        the
                end (N raids, M minutes or without end), then only leave if a different raid/mode follows."""
        target = task.get("target", "")
        self._ensure_monitoring()
        if self.set_raid is not None:
            self.set_raid(target)
        leave_wave = int(task.get("leave_wave", 0))
        if self._in_raid == target and self._gear(self._frame()) is not None:
            self.log(tr("Already in raid “{name}” – farming on.", name=target))
        else:
            if self._gear(self._frame()) is not None:     # still in another raid
                self._leave_raid()
            self._in_raid = None
            self._raid(self._window(target), bool(task.get("join")))
            end = time.monotonic() + 120                  # until you are in the raid (teleport, lobby)
            while self._gear(self._frame()) is None:
                if time.monotonic() > end:
                    raise Stop(tr("Did not arrive in the raid."))
                time.sleep(1.0)
            self._in_raid = target
        self._open_raid_settings()
        self._set_toggle("retry", True)
        if leave_wave > 0:                                # wave first, then the switch: the game's default is 5 –
            self._set_leave_wave(leave_wave)              # switched on first it could leave too early (owner 09.10.2026)
        self._set_toggle("leave", leave_wave > 0)
        self._close_raid_settings()
        self._run_side_steps()
        until = task.get("until", "runs")
        runs, minutes = int(task.get("runs", 1)), float(task.get("minutes", 30))
        start, t0 = self.raid_count(), time.monotonic()
        self.log({"runs": tr("Farming {runs} raids …", runs=runs),
                  "minutes": tr("Farming {minutes} min …", minutes=int(minutes))}.get(until, tr("Farming until you stop …")))
        _ACTIVE.clear()                                   # Anti-AFK may run while waiting
        try:
            last = 0
            while True:
                done = self.raid_count() - start
                if until == "runs" and done >= runs:
                    break
                if until == "minutes" and time.monotonic() - t0 >= minutes * 60:
                    break
                if done != last:
                    last = done
                    self.log(tr("{done} raids done", done=done))
                self._extras_while_waiting()
                if self._halt.wait(2.0):
                    raise UserStop(tr("Stopped."))
                if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                    raise UserStop(tr("Cancelled (Esc)."))
        finally:
            _ACTIVE.set()
        self._focus()
        if leave_before(task, following):
            self.log(tr("A different raid is next – leaving this one."))
            self._leave_raid()
            self._in_raid = None
        else:
            self.log(tr("Staying in the raid (Auto Retry keeps farming)."))

    def _run_side_steps(self) -> None:
        """Auto Roll & co. placed after the raid step: run them now, inside the raid (raid_side_steps)."""
        steps, self._side_steps = getattr(self, "_side_steps", []), []
        for j, side, count in steps:
            self.queue_pos = j
            self.log(tr("In the raid – step {n}/{count}: {task}", n=j + 1, count=count, task=task_label(side)))
            for attempt in (1, 2):
                try:
                    self._task(side)
                    break
                except UserStop:
                    raise
                except Stop as exc:
                    if attempt == 2:
                        self.log("⚠ " + tr("Skipped: {reason}", reason=exc))
                    else:
                        self.log("⚠ " + tr("{reason} – trying once more.", reason=exc))
                        self._close_any_quiet()
            time.sleep(0.6)
        if steps:
            self.queue_pos = steps[0][0] - 1                  # back to the raid step for the display

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
    def _guild_claim(self) -> int:
        """Open the guild (button at the bottom left) → “Missions” → claim “Personal” and “Guild Weekly” → close.
        Returns the number of claims."""
        button = next((e for e in self.map.hud() if e["name"] == "Guild"), None)
        if button is None:
            raise Stop(tr("The guild button is unknown yet."))
        self._close_any()
        self.log(tr("Clicking “{button}”.", button="Guild"))
        self._click_roi(self.hud_roi(button))
        end = time.monotonic() + OPEN_TIMEOUT
        while self._screen(self._frame())[0] == "none":
            if time.monotonic() > end:
                raise Stop(tr("The guild did not open."))
            time.sleep(STEP_WAIT)
        time.sleep(0.6)
        guild = {"name": "Guild"}
        roi, frame = self._window_area(guild)                # block “Leave” at the bottom left before anything is clicked
        from .knowledge import forbidden_zones
        self.forbidden = forbidden_zones(vision.words_in(frame, roi, self._ocr), roi, "Guild")
        try:
            total = self._guild_pages(guild)
        finally:
            self.forbidden = []
        self._close_any()
        return total

    def _guild_forbidden(self) -> list:
        """Recompute the no-go zones for the guild page visible right now. Otherwise the zones of the home page (Kick,
        Leave …) lay over “Personal” after switching to “Missions” – the tab counted as blocked. Returns the words
        read (reused for the “Claim” search – one text recognition per page instead of two)."""
        from .knowledge import forbidden_zones
        roi, frame = self._window_area({"name": "Guild"})
        words = vision.words_in(frame, roi, self._ocr)
        self.forbidden = forbidden_zones(words, roi, "Guild")
        return words

    def _guild_pages(self, guild: dict) -> int:
        self._press(guild, ("missions",))
        time.sleep(GUILD_TAB_WAIT)
        self._guild_forbidden()
        total = 0
        for tab, label in ((("personal",), "Personal"), (("guild", "weekly"), "Guild Weekly")):
            try:
                self._press(guild, tab)
            except UserStop:
                raise
            except Stop as exc:
                self.log(tr("Tab “{tab}”: {reason}", tab=label, reason=exc))
                continue
            time.sleep(GUILD_TAB_WAIT)
            total += self._claim_all(label, self._guild_forbidden())
        if not total:
            self._snap("gilde")
        return total

    # ------------------------------------------------------------------ Fixer Gigs (W21)
    def _gigs(self) -> None:
        """Open Fixer Gigs, claim finished gigs (“Claim”), send new ones with “Send Pets” (the last pets in the pets
        window), remember the durations – the task is skipped before they run out."""
        wait = self.gigs_next - time.time()
        if wait > 0 and len(self.gig_slots) == len(GIG_SLOT_BOXES):
            self.log(tr("Fixer Gigs: nothing finished yet – checking again in {time}.", time=fmt_wait(wait)))
            return
        window = self._gigs_window()
        if window is None:
            raise Stop(tr("Fixer Gigs is unknown yet – run “Explore” once."))
        self._open(window)
        time.sleep(0.8)
        self._claim_all("Fixer Gigs")
        for nth in range(1, GIGS_PETS + 1):               # per free slot: “Send Pets” with one pet
            words, _roi = self._words()
            box = self._send_box(words)
            if box is None:
                break
            self.log(tr("Clicking “{button}”.", button="Send Pets"))
            self._click_roi(box)
            time.sleep(1.2)
            self._send_pets(nth)
            if not self._is_open(window, self._frame()):
                self._open(window)
                time.sleep(0.8)
        words, roi = self._words()
        if roi == [0.0, 0.0, 1.0, 1.0]:                   # frame not found in the image: position from the map
            roi = window["roi"]
        cards = gig_cards(words, roi)
        frame = self._frame()
        timers = {i: self._read_slot_timer(frame, c, words) for i, c in enumerate(cards) if c["state"] == "working"}
        self._snap_gigs(frame, cards)
        refresh = None
        if any(c["state"] == "empty" for c in cards):    # new gigs only after “NEW GIGS IN …”
            refresh = self._read_timer(frame, gig_refresh_box(words), GIG_REFRESH_MAX) or gig_refresh_read(words)
        parts = []
        for i, c in enumerate(cards):
            kind = tr("Gig") if c["unknown"] else tr(GIG_NAMES.get(c["duration"], "Gig"))
            if c["state"] == "working":
                parts.append(tr("{gig}: {time} left", gig=kind, time=fmt_wait(timers[i])) if timers.get(i)
                             else tr("{gig}: running", gig=kind))
            elif c["state"] == "ready":
                parts.append(tr("{gig}: done", gig=kind))
            elif c["state"] == "open":
                parts.append(tr("{gig}: needs a pet", gig=kind))
            else:
                parts.append(tr("Slot {n}: empty, new gigs in {time}", n=i + 1, time=fmt_wait(refresh)) if refresh
                             else tr("Slot {n}: empty", n=i + 1))
        self.log(tr("Fixer Gigs: {cards}", cards=" · ".join(parts)))
        if all(c["state"] == "empty" for c in cards):     # nothing read at all: keep the image for checking
            self._snap("gigs")
        wait = max(60, gig_next_due(cards, timers, refresh) + 20)
        self.gigs_next = time.time() + wait
        self.gig_slots = gig_slot_states(cards, timers, refresh, time.time())
        self._save_state()
        self.log(tr("Fixer Gigs: next visit in {time}.", time=fmt_wait(wait)))
        self._close_any()

    def _snap_gigs(self, frame: np.ndarray, cards: list[dict]) -> None:
        """Check image of the last visit (debug/gigs_last.jpg, overwritten): slot frames and time bands drawn in –
        shows at once whether the slots sit on the cards."""
        try:
            from .app_paths import debug_dir
            img = frame.copy()
            fh, fw = img.shape[:2]
            for c in cards:
                x0, y0, x1, y1 = c["box"]
                cv2.rectangle(img, (int(x0 * fw), int(y0 * fh)), (int(x1 * fw), int(y1 * fh)), (255, 0, 255), 2)
                for fy0, fy1 in GIG_TIMER_BANDS[:1]:
                    cv2.rectangle(img, (int((x0 + 0.1 * (x1 - x0)) * fw), int((y0 + fy0 * (y1 - y0)) * fh)),
                                  (int((x1 - 0.1 * (x1 - x0)) * fw), int((y0 + fy1 * (y1 - y0)) * fh)), (0, 255, 255), 1)
            small = cv2.resize(img, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(str(debug_dir() / "gigs_last.jpg"))
        except Exception:  # noqa: BLE001 – only a debugging aid
            pass

    def _read_slot_timer(self, frame: np.ndarray, card: dict, words: list) -> Optional[int]:
        """Time left of a running gig: the time line at its fixed height in the card, read several ways (two bands ×
        two thresholds) plus the general reading, then a vote (gig_timer_vote). Independent of “left” being read
        (owner 09.10.2026: “2:59:47 left” was missed, “43:41” read as “4:41”)."""
        texts = [w for w, b in words if card["box"][0] <= (b[0] + b[2]) / 2 <= card["box"][2]
                 and card["box"][1] + 0.55 * (card["box"][3] - card["box"][1]) <= (b[1] + b[3]) / 2
                 <= card["box"][1] + 0.75 * (card["box"][3] - card["box"][1])]
        fh, fw = frame.shape[:2]
        x0, y0, x1, y1 = card["box"]
        for fy0, fy1 in GIG_TIMER_BANDS:
            crop = frame[int((y0 + fy0 * (y1 - y0)) * fh):int((y0 + fy1 * (y1 - y0)) * fh),
                         int((x0 + 0.1 * (x1 - x0)) * fw):int((x1 - 0.1 * (x1 - x0)) * fw)]
            if crop.size == 0 or self._ocr is None:
                continue
            gray = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            for thresh in (170, 0):
                flag = cv2.THRESH_BINARY_INV | (cv2.THRESH_OTSU if thresh == 0 else 0)
                binary = cv2.copyMakeBorder(cv2.threshold(gray, thresh, 255, flag)[1], 10, 10, 10, 10,
                                            cv2.BORDER_CONSTANT, value=255)
                try:
                    texts.append(self._ocr.line(binary, 7))
                except Exception:  # noqa: BLE001 – read error: one vote less
                    pass
        return gig_timer_vote(texts, card["duration"])

    def _read_timer(self, frame: np.ndarray, box: Optional[list[float]], duration: int) -> Optional[int]:
        """Read the time left exactly: crop scaled up 4×, bright text, only digits and “:” (the general reading likes
        to
                turn “1:36:38” into “4:36:98”). Only valid if at most as long as the gig."""
        if box is None or self._ocr is None:
            return None
        fh, fw = frame.shape[:2]
        crop = frame[max(0, int(box[1] * fh)):int(box[3] * fh), max(0, int(box[0] * fw)):int(box[2] * fw)]
        if crop.size == 0:
            return None
        gray = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        for thresh in (170, 0):
            flag = cv2.THRESH_BINARY_INV | (cv2.THRESH_OTSU if thresh == 0 else 0)
            binary = cv2.copyMakeBorder(cv2.threshold(gray, thresh, 255, flag)[1], 10, 10, 10, 10,
                                        cv2.BORDER_CONSTANT, value=255)
            try:
                seconds = parse_timer(self._ocr.line(binary, 7, "0123456789:"))
            except Exception:  # noqa: BLE001 – read error: then not
                seconds = None
            if seconds is not None and 0 < seconds <= duration + 60:
                return seconds
        return None

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

    def _gigs_window(self) -> Optional[dict]:
        """Fixer Gigs window of the map (kind “gigs” from exploring, or the name)."""
        return next((e for e in self.map.entries if e.get("kind") == "Fenster / Bereich" and (
            (e.get("extra") or {}).get("category") == "gigs" or "fixer gigs" in e["name"].lower())), None)

    @staticmethod
    def _send_box(words) -> Optional[list[float]]:
        """“SEND PETS” (two words side by side) or “SEND” alone."""
        norm = [(re.sub(r"[^a-z]", "", w.lower()), b) for w, b in words]
        return next((b for w, b in norm if w in ("send", "sendpets")), None)

    def _send_pets(self, nth: int = 1) -> None:
        """Pets window after “Send Pets”: scroll to the very bottom, click ONE pet – for the n-th gig the n-th from the
        end (so in turn one of the last GIGS_PETS, whichever); the click sends it off. One gig at a time.
        Unknown steps are logged and saved as an image (debug/makro_gigs_*.jpg)."""
        roi, frame = self._window_area({"name": "Pets"})
        x0, y0, x1, y1 = roi
        grid = [x0 + 0.06 * (x1 - x0), y0 + 0.30 * (y1 - y0), x0 + 0.94 * (x1 - x0), y0 + 0.86 * (y1 - y0)]
        center = ((grid[0] + grid[2]) / 2, (grid[1] + grid[3]) / 2)
        # until the list is at the bottom: “bottom” = the content doesn't shift anymore (phase correlation). The plain
        # image comparison ran on forever with animated pets when the list was already at the bottom (2nd gig, owner)
        from .explorer import scrolled_box

        def grid_img() -> tuple[np.ndarray, np.ndarray]:
            f = self._frame()
            fh, fw = f.shape[:2]
            crop = f[int(grid[1] * fh):int(grid[3] * fh), int(grid[0] * fw):int(grid[2] * fw)]
            return f, cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (480, 270), interpolation=cv2.INTER_AREA)

        frame, last = grid_img()
        still = 0
        for _ in range(25):
            self._wheel(center, -SCROLL_NOTCHES)
            time.sleep(0.35)
            frame, now = grid_img()
            if scrolled_box(last, now) is None:
                still += 1
                if still >= 2:
                    break                                 # nothing shifted twice: arrived at the bottom
            else:
                still = 0
            last = now
        tiles = self._pet_tiles(frame, grid)
        if not tiles:
            self.log(tr("No pets recognised in the window."))
            self._snap("gigs_pets")
            self._close_any_quiet()
            return
        # A click on the pet sends it off – no confirmation (owner 08.10.2026). First the n-th from the end;
        # if the pets window stays open (pet already busy or similar), try the others of the last GIGS_PETS.
        gigs = self._gigs_window() or {"name": "Fixer Gigs"}
        order = [nth] + [k for k in range(1, GIGS_PETS + 1) if k != nth]
        for k in order[:min(GIGS_PETS, len(tiles))]:
            self._click_roi(tiles[-k])
            self.log(tr("Clicked pet no. {n} from the end.", n=k))
            end = time.monotonic() + 2.5
            while time.monotonic() < end:
                time.sleep(STEP_WAIT * 2)
                frame = self._frame()
                if self._is_open(gigs, frame) or self._screen(frame)[0] == "none":
                    self.log(tr("Pet sent."))
                    return
        self.log(tr("No pet could be sent – the image is in the debug folder."))
        self._snap("gigs_pets_offen")
        self._close_any_quiet()

    def _pet_tiles(self, frame: np.ndarray, grid: list[float]) -> list[list[float]]:
        """Pet tiles in the grid (reading order). The grid follows from the name tags at the bottom of the tiles
        (“Maine”, “Rias” …): rows = same height, columns = same spacing. A tile counts if a name is in it or its
        content is sharp (empty slots are smooth)."""
        return pet_tiles(frame, grid, vision.words_in(frame, grid, self._ocr))

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
            self.log("✖ " + tr("Error: {error}", error=exc))
        finally:
            _ACTIVE.clear()
            if self._source is not None:
                try:
                    self._source.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._source = None

    def _prepare(self) -> None:
        if not self.map.entries:
            raise Stop(tr("The UI map is missing."))
        self._hwnd = winapi.find_window(self.window_title)
        if self._hwnd is None:
            raise Stop(tr("Roblox window not found"))
        if winapi.is_minimized(self._hwnd):
            raise Stop(tr("Roblox is minimized"))
        if self._ocr is None:
            self._ocr = self.ocr_factory()                # own text recognition (not the monitoring's)
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

    def _close_any(self) -> None:
        for attempt in range(4):
            if attempt == 2 and time.monotonic() - getattr(self, "_warped", 0.0) < 10:
                self._unlock_camera()                     # not closed twice and the cursor is held
            kind, st = self._screen(self._frame())
            if kind == "none":
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

    def _pets_auto(self, world: str, close_after: bool = True) -> None:
        window = self._window(f"{world} Pets-Roll")
        self._open(window)
        auto = self.map.element(window, "Auto!")
        cost = self.map.element(window, "Kosten (Yen)")
        if cost is not None:
            text = vision.read_text(self._frame(), cost["roi"], self._ocr)
            self.log(tr("Cost per pet: {cost}", cost=text or "?"))
        if auto is None:
            raise Stop(tr("“Auto!” is missing from the map."))
        self.log(tr("Clicking “Auto!”."))
        self._click_roi(auto["roi"])
        if close_after:
            self._close_after_auto(window)

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
