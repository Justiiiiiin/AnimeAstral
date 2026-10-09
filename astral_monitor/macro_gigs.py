"""Macro part “Fixer Gigs” (W21): read the three slots (running / done / needs a pet / empty), their times and
“NEW GIGS IN …”, claim, send one pet per gig. Never “FINISH NOW” (costs currency). Without Qt."""

from __future__ import annotations

import re
import time
from typing import Optional

import cv2
import numpy as np

from . import vision
from .i18n import N_, tr
from .macro_base import SCROLL_NOTCHES, STEP_WAIT, Stop, fmt_wait, parse_timer

GIGS_PETS = 3             # “Send Pets”: 1 pet per gig, in turn one of the last 3 (owner 08.10.2026)
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


class GigsMixin:
    """Part of the Navigator (automation.Navigator) – uses its input, image and log methods."""

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
