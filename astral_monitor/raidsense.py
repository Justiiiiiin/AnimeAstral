"""Which raid is running? (without Qt, owner's wish 08.10.2026) – independent of the camera:

1. **Read along the raid window:** before you join a raid (yourself or via the macro), the raid window is open and
   the name is in large red/orange letters below the banner (“Holy Grail War”). The monitoring checks every few
   seconds whether such a window is open and remembers the name. If a new run starts afterwards – and the wave
   counter was gone in between (teleport) – it belongs to that raid. Only looking and staying in the same raid
   (Auto Retry) doesn't count.
2. (planned) **Drops:** drops unique to one raid from the “Enemy Drops” lists (learned by exploring) – for
   auto-join modes like MaxTac Call that have no raid window."""
from __future__ import annotations

import difflib
import logging
import re
from typing import Optional

import numpy as np

from . import vision

log = logging.getLogger("raid")

RAID_TITLES = ("raid", "boss rush", "defense mode", "tower")   # banner titles of windows with Create/Join
SEEN_TWICE = 2          # same name read this often = certain (misreads would otherwise create wrong raids)
VALID_FOR = 300.0       # the run may start this long after the window (lobby, countdown)
ABSENT_MIN = 2.0        # the wave counter must have been gone this long in between (teleport into the raid)


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def match_name(read: str, known: list[str]) -> Optional[str]:
    """Match a read name to a known raid (misreads: “Het Grail War” ≈ “Holy Grail War”)."""
    key = norm(read)
    if not key:
        return None
    best, score = None, 0.0
    for name in known:
        k = norm(name)
        s = 1.0 if k == key else difflib.SequenceMatcher(None, key, k).ratio()
        if s > score:
            best, score = name, s
    return best if score >= 0.8 else None


class RaidSense:
    def __init__(self) -> None:
        self.pending: Optional[str] = None                 # last raid name read with certainty
        self.pending_ts = 0.0
        self._candidate: Optional[str] = None
        self._count = 0
        self._absent_since: Optional[float] = None
        self._teleported = False                          # the counter was gone long enough after the window

    # ------------------------------------------------------------------ 1. Raid window
    def seen_name(self, name: str, known: list[str], now: float) -> None:
        """Name from an open raid window (already read). Known raids are matched."""
        name = match_name(name, known) or name.strip()
        if not norm(name):
            return
        if self._candidate and (norm(self._candidate) == norm(name) or difflib.SequenceMatcher(
                None, norm(self._candidate), norm(name)).ratio() >= 0.85):
            self._count += 1                              # small misreads count as the same name –
            if name not in known:                         # a known name wins, otherwise the first reading
                name = self._candidate
        else:
            self._candidate, self._count = name, 1
        if self._count >= SEEN_TWICE and (self.pending != name or now - self.pending_ts > 5):
            if self.pending != name:
                log.info("Raid window: %s", name)
            self.pending, self.pending_ts, self._teleported = name, now, False

    def wave_visible(self, visible: bool, now: float) -> None:
        """From the wave counter: if it is gone (teleport/lobby), the next run may belong to the raid that was read."""
        if visible:
            if self._absent_since is not None and now - self._absent_since >= ABSENT_MIN \
                    and self.pending and now > self.pending_ts:
                self._teleported = True                   # the counter came (back) into the image after the raid window
            self._absent_since = None
        elif self._absent_since is None:
            self._absent_since = now

    def take(self, now: float) -> Optional[str]:
        """When a new run starts: raid name, if a raid window was open shortly before and you have teleported since –
        otherwise None (e.g. only looked, Auto Retry in the same raid)."""
        if not self.pending or now - self.pending_ts > VALID_FOR:
            return None
        if not (self._teleported or self._absent_since is not None):
            return None
        name, self.pending = self.pending, None
        self._candidate, self._count, self._teleported = None, 0, False
        return name


def read_raid_window(frame: np.ndarray, menu: "vision.MenuFrame", ocr) -> Optional[str]:
    """Is a raid window open? Then its name (red/orange below the banner), otherwise None."""
    state = menu.state(frame, ocr, wide=False)          # raid windows have the standard size: fast check only
    if state is None:
        return None
    roi, title, _x = state
    t = title.lower().strip(" !")
    if not any(t.startswith(r) for r in RAID_TITLES):
        return None
    fh, fw = frame.shape[:2]
    crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
    name = vision.read_name_below_banner(crop, ocr) if crop.size else ""
    return name or None


# ---------------------------------------------------------------------- 2. Drops (area on the left above the bottom bar)
DROP_REGION = [0.08, 0.32, 0.86, 0.90]  # drop tiles (up to 4 rows) above the buttons at the bottom – depending on the GUI size
DROP_SCALE = 3                          # labels are tiny: read them enlarged
DROP_HIT = 0.8                          # fuzzy comparison (misread “Sreet Cred”)
DROP_CONFIRM = 2                        # in front this many times in a row = take over the raid


GENERIC = {"token", "tokens", "coin", "coins", "shard", "shards", "key", "keys", "fragment", "fragments", "chest",
           "box", "orb", "stone", "crystal", "part", "parts"}     # say nothing on their own – keywords decide


def _keywords(name: str) -> list[str]:
    words = [norm(w) for w in re.split(r"\s+", name) if norm(w)]
    special = [w for w in words if w not in GENERIC and len(w) >= 3]
    return special or words


def _word_hit(key: str, read: list[str]) -> bool:
    if len(key) <= 3:
        return key in read
    return any(r == key or (abs(len(r) - len(key)) <= 1 and difflib.SequenceMatcher(None, key, r).ratio() >= DROP_HIT)
               for r in read)


class DropIndex:
    """Which drops exist in exactly one raid? (from the “Enemy Drops” lists read by exploring).
    The keywords of a drop are compared one by one (“Primordial”, “Street”+“Cred”) – the order of the words read
    in the drop area isn't reliable."""

    def __init__(self, drops_by_raid: dict[str, list[str]]) -> None:
        owners: dict[str, set[str]] = {}
        names: dict[str, str] = {}
        for raid, drops in drops_by_raid.items():
            for d in drops:
                key = norm(d)
                if len(key) >= 5:
                    owners.setdefault(key, set()).add(raid)
                    names[key] = d
        self.unique = {key: next(iter(r)) for key, r in owners.items() if len(r) == 1}
        self._keys = {key: _keywords(names[key]) for key in self.unique}

    @classmethod
    def from_map(cls, umap) -> "DropIndex":
        table: dict[str, list[str]] = {}
        for e in umap.entries:
            extra = e.get("extra") or {}
            if extra.get("drops") and extra.get("raid_name"):
                table.setdefault(extra["raid_name"], []).extend(extra["drops"])
        return cls(table)

    def votes(self, words: list[str]) -> dict[str, int]:
        """Hits per raid for the words read in the drop area (only unique drops count)."""
        read = [norm(w) for w in words if norm(w)]
        out: dict[str, int] = {}
        for key, raid in self.unique.items():
            if all(_word_hit(k, read) for k in self._keys[key]):
                out[raid] = out.get(raid, 0) + 1
        return out


class DropWatcher:
    """Decides over several readings: the same raid clearly ahead DROP_CONFIRM times in a row -> raid."""

    def __init__(self) -> None:
        self._leader: Optional[str] = None
        self._streak = 0

    def feed(self, votes: dict[str, int]) -> Optional[str]:
        if not votes:
            return None
        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        leader, score = ranked[0]
        if len(ranked) > 1 and ranked[1][1] >= score:
            self._leader, self._streak = None, 0          # tie: say nothing
            return None
        if leader == self._leader:
            self._streak += 1
        else:
            self._leader, self._streak = leader, 1
        return leader if self._streak >= DROP_CONFIRM else None

    def reset(self) -> None:
        self._leader, self._streak = None, 0


def drop_scale(frame_h: int, wave_text_h: Optional[float]) -> float:
    """Scale for the drop area from the game's GUI size: the labels are about a third as tall as the wave counter
    (measured at GUI 50 % and 100 %); Tesseract needs ~20 px. Without a counter: from the image height."""
    if wave_text_h and wave_text_h > 4:
        return max(1.0, min(3.5, 20.0 / (0.4 * wave_text_h)))
    return max(1.5, min(DROP_SCALE, DROP_SCALE * 720 / max(1, frame_h)))


def read_drop_words(frame: np.ndarray, ocr, wave_text_h: Optional[float] = None) -> list[str]:
    """Words in the drop area. The position depends on the game's GUI size, hence a generous area (at the bottom,
    without the side bars); the scale follows the size of the wave counter. ~0.3–0.7 s – rarely!"""
    import cv2
    fh, fw = frame.shape[:2]
    x0, y0, x1, y1 = DROP_REGION
    crop = frame[int(y0 * fh):int(y1 * fh), int(x0 * fw):int(x1 * fw)]
    if crop.size == 0:
        return []
    f = drop_scale(fh, wave_text_h)
    big = crop if f == 1.0 else cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return [w for w, _b in vision.words_in(big, [0.0, 0.0, 1.0, 1.0], ocr)
            if len(re.sub(r"[^A-Za-z]", "", w)) >= 3]
