"""State logic: raid progress (WaveTracker) and quest tracking (QuestTracker)."""
from __future__ import annotations

import difflib
import itertools
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .quests import QuestLine

log = logging.getLogger("tracker")

START_MAX = 5            # from this wave value on, the raid start counts as “seen”
ABSENT_SECONDS = 8.0     # this long without a counter = raid over
DROP_MIN = 3             # counter drops by more than this = restart (after 2 matching readings)
UP_BASE = 4              # allowed jump upwards ...
UP_PER_SECOND = 1.5      # ... plus this many waves per elapsed second (anything above = misread)
CUT_CONFIRM = 2.0        # “4” instead of “54” (front digit hidden): restart only once the reading stays this long


def _cut_digits(value: int, last: int) -> bool:
    """Does value look like last (or the next waves) with a missing front digit? Real case 07.10.:
        at wave 54 “4” was read twice – without this check a false restart."""
    s = str(value)
    return any(len(str(n)) > len(s) and str(n).endswith(s) for n in (last, last + 1, last + 2))


@dataclass
class _Run:
    start_ts: Optional[float]
    first_wave: int
    max_wave: int
    total: int
    completed: bool = False
    profile: Optional[str] = None
    first_ts: float = 0.0          # time of the first reading (for the duration estimate)


class WaveTracker:
    """Tracks the wave counter. Returns events:
        ("candidate", None)  – counter >= trigger, please confirm
        ("run_end", dict)    – raid finished without a confirmed trigger (aborted/detected late)"""

    def __init__(self, offset: int = 1, cooldown: float = 60.0) -> None:
        self.offset = offset
        self.cooldown = cooldown
        self.run: Optional[_Run] = None
        self.armed = True
        self.last_value: Optional[int] = None
        self.total: Optional[int] = None
        self._last_seen = 0.0
        self._absent_since: Optional[float] = None
        self._last_trigger = float("-inf")
        self._drop_value: Optional[int] = None
        self._drop_ts = 0.0
        self.rejected = 0          # number of discarded misreads (diagnostics)
        self._rej_streak = 0

    def update(self, value: Optional[int], total: Optional[int], now: float) -> list[tuple[str, object]]:
        out: list[tuple[str, object]] = []
        if value is None or total is None:
            if self.run is not None:
                if self._absent_since is None:
                    self._absent_since = now
                if now - self._absent_since >= ABSENT_SECONDS:
                    log.info("Wave counter not visible for %.0f s – run finished (highest wave %d)",
                             now - self._absent_since, self.run.max_wave)
                    info = self._finish()
                    if info:
                        out.append(("run_end", info))
            return out

        self._absent_since = None
        if self.run is not None and self.last_value is not None:
            allowed = UP_BASE + UP_PER_SECOND * max(0.0, now - self._last_seen)
            if value > self.last_value + allowed:
                # Impossible jump upwards (e.g. 25 read as 95): ignore the reading, change nothing
                self.rejected += 1
                self._rej_streak += 1
                if self._rej_streak in (1, 10, 100):
                    log.warning("Implausible reading %d after %d (%.1f s) – ignored (%dx in a row)", value,
                                self.last_value, now - self._last_seen, self._rej_streak)
                return out
            self._rej_streak = 0
        restart_ts: Optional[float] = None
        if self.run is not None and self.last_value is not None and value < self.last_value - DROP_MIN:
            cand = self._drop_value
            if (cand is not None and cand <= value <= cand + DROP_MIN and _cut_digits(cand, self.last_value)
                    and now - self._drop_ts < CUT_CONFIRM):
                return out                                # suspicious (digit hidden?): keep waiting
            if cand is not None and cand <= value <= cand + DROP_MIN:
                self._drop_value = None
                if value > max(START_MAX, self.last_value // 2):
                    # A new run starts low. If the counter drops only a little (e.g. 29 -> 25), the higher
                    # readings were wrong (frozen frame while switching or similar) – within a run
                    # the counter never goes down. So correct instead of recording a failed attempt.
                    log.info("Counter correction: %d -> %d (higher reading was wrong)", self.last_value, value)
                    self.run.first_wave = min(self.run.first_wave, value)
                    self.run.max_wave = value
                    self.last_value = value
                else:
                    restart_ts = self._drop_ts           # second matching reading: restart confirmed
                    log.info("Restart confirmed: %d -> %d (highest wave of the attempt: %d)",
                             self.last_value, value, self.run.max_wave)
                    info = self._finish()
                    if info:
                        out.append(("run_end", info))
            else:
                self._drop_value, self._drop_ts = value, now     # first reading: wait a bit longer
                log.info("Counter drops from %d to %d – waiting for confirmation", self.last_value, value)
                return out
        else:
            self._drop_value = None
        if self.run is None:
            start = (restart_ts if restart_ts is not None else now) if value <= START_MAX else None
            self.run = _Run(start_ts=start, first_wave=value, max_wave=value, total=total,
                            first_ts=(restart_ts if restart_ts is not None else now))
            self.armed = True
            log.info("New run at wave %d/%d (start %s)", value, total,
                     "gesehen" if start is not None else "not seen")

        self.run.max_wave = max(self.run.max_wave, value)
        if total or not self.run.total:                 # a reading without a total doesn't change a known target
            self.run.total = total
        self.last_value, self.total, self._last_seen = value, total, now

        if (self.armed and not self.run.completed and self.run.total and value >= self.run.total - self.offset
                and now - self._last_trigger >= self.cooldown):
            out.append(("candidate", None))
        return out

    def hold(self) -> None:
        """The macro is clicking menus: the counter is often hidden or other numbers are in the image – decide
                nothing. A drop or absence that began doesn't count on; afterwards it continues normally."""
        self._absent_since = None
        self._drop_value = None

    def confirm(self, now: float) -> dict:
        """Trigger confirmed: the raid counts. Returns duration/waves."""
        run = self.run
        assert run is not None
        run.completed = True
        self.armed = False
        self._last_trigger = now
        duration = (now - run.start_ts) if run.start_ts is not None else None
        return {"duration": duration, "max_wave": run.max_wave, "total": run.total, "profile": run.profile,
                "first_wave": run.first_wave, "observed": now - run.first_ts}

    def _finish(self) -> Optional[dict]:
        run = self.run
        self.run = None
        self.armed = True
        self.last_value = None
        self._absent_since = None
        if run is None or run.completed:
            return None
        result = "ok_late" if run.total and run.max_wave >= run.total - self.offset else "abgebrochen"
        duration = (self._last_seen - run.start_ts) if run.start_ts is not None else None
        return {"result": result, "max_wave": run.max_wave, "total": run.total, "duration": duration,
                "profile": run.profile, "first_wave": run.first_wave,
                "observed": max(0.0, self._last_seen - run.first_ts)}


# --------------------------------------------------------------------------- Quests
@dataclass
class Quest:
    id: int
    title: str
    cur: Optional[int]
    total: Optional[int]
    votes: Counter = field(default_factory=Counter)
    missed: int = 0
    pending: Optional[int] = None
    pos: int = 0                         # position in the in-game list (shown in the same order)

    @property
    def percent(self) -> Optional[int]:
        if self.cur is None or not self.total:
            return None
        return min(100, int(self.cur * 100 / self.total))


@dataclass
class QuestChange:
    quest: Quest
    old: int
    new: int


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class QuestTracker:
    """Matches read quest lines with known quests (tolerant of OCR errors)
        and reports progress only once the same new value was read twice."""

    def __init__(self) -> None:
        self.items: list[Quest] = []
        self._ids = itertools.count(1)

    def update(self, lines: list[QuestLine]) -> tuple[list[QuestChange], list[Quest]]:
        changes: list[QuestChange] = []
        completed: list[Quest] = []
        seen: set[int] = set()

        for pos, line in enumerate(lines):
            quest = self._match(line, seen)
            if quest is None:
                quest = Quest(next(self._ids), line.title, line.cur, line.total, pos=pos)
                quest.votes[line.title] += 1
                self.items.append(quest)
                seen.add(quest.id)
                continue
            seen.add(quest.id)
            quest.missed = 0
            quest.pos = pos
            quest.votes[line.title] += 1
            quest.title = quest.votes.most_common(1)[0][0]
            if line.total:
                quest.total = line.total
            if line.cur is None or line.cur == quest.cur:
                quest.pending = None
                continue
            if quest.cur is None:
                quest.cur = line.cur
            elif quest.pending == line.cur:
                old, quest.cur, quest.pending = quest.cur, line.cur, None
                changes.append(QuestChange(quest, old, quest.cur))
                if quest.total and old < quest.total <= quest.cur:
                    completed.append(quest)
            else:
                quest.pending = line.cur

        for quest in self.items:
            if quest.id not in seen:
                quest.missed += 1
        self.items = sorted((q for q in self.items if q.missed < 3), key=lambda q: q.pos)
        return changes, completed

    def _match(self, line: QuestLine, seen: set[int]) -> Optional[Quest]:
        best, best_score = None, 0.72
        target = _norm(line.title)
        for quest in self.items:
            if quest.id in seen:
                continue
            if line.total and quest.total and line.total != quest.total:
                continue
            score = difflib.SequenceMatcher(None, target, _norm(quest.title)).ratio()
            if score > best_score:
                best, best_score = quest, score
        return best

    def snapshot(self) -> list[dict]:
        return [{"title": q.title, "cur": q.cur, "total": q.total, "percent": q.percent}
                for q in self.items]
