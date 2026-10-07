"""Zustandslogik: Raid-Verlauf (WaveTracker) und Quest-Verfolgung (QuestTracker)."""
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

START_MAX = 5            # ab diesem Wellenwert gilt der Raid-Beginn als „gesehen"
ABSENT_SECONDS = 8.0     # so lange ohne Zähler = Raid vorbei
DROP_MIN = 3             # Zähler fällt um mehr als so viel = Neustart (nach 2 passenden Lesungen)
UP_BASE = 4              # erlaubter Sprung nach oben ...
UP_PER_SECOND = 1.5      # ... plus so viele Wellen pro vergangener Sekunde (alles darüber = Fehllesung)


@dataclass
class _Run:
    start_ts: Optional[float]
    first_wave: int
    max_wave: int
    total: int
    completed: bool = False
    profile: Optional[str] = None
    first_ts: float = 0.0          # Zeitpunkt der ersten Lesung (für die Dauer-Schätzung)


class WaveTracker:
    """Verfolgt den Wellenzähler. Liefert Ereignisse:
    ("candidate", None)  – Zähler >= Auslöser, bitte bestätigen
    ("run_end", dict)    – Raid beendet ohne bestätigten Auslöser (abgebrochen/spät erkannt)"""

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
        self.rejected = 0          # Anzahl verworfener Fehllesungen (Diagnose)
        self._rej_streak = 0

    def update(self, value: Optional[int], total: Optional[int], now: float) -> list[tuple[str, object]]:
        out: list[tuple[str, object]] = []
        if value is None or total is None:
            if self.run is not None:
                if self._absent_since is None:
                    self._absent_since = now
                if now - self._absent_since >= ABSENT_SECONDS:
                    log.info("Wellenzähler seit %.0f s nicht sichtbar – Lauf beendet (höchste Welle %d)",
                             now - self._absent_since, self.run.max_wave)
                    info = self._finish()
                    if info:
                        out.append(("run_end", info))
            return out

        self._absent_since = None
        if self.run is not None and self.last_value is not None:
            allowed = UP_BASE + UP_PER_SECOND * max(0.0, now - self._last_seen)
            if value > self.last_value + allowed:
                # Unmöglicher Sprung nach oben (z. B. 25 als 95 gelesen): Lesung ignorieren, nichts ändern
                self.rejected += 1
                self._rej_streak += 1
                if self._rej_streak in (1, 10, 100):
                    log.warning("Unplausible Lesung %d nach %d (%.1f s) – ignoriert (%dx in Folge)", value,
                                self.last_value, now - self._last_seen, self._rej_streak)
                return out
            self._rej_streak = 0
        restart_ts: Optional[float] = None
        if self.run is not None and self.last_value is not None and value < self.last_value - DROP_MIN:
            cand = self._drop_value
            if cand is not None and cand <= value <= cand + DROP_MIN:
                self._drop_value = None
                if value > max(START_MAX, self.last_value // 2):
                    # Ein neuer Lauf beginnt niedrig. Fällt der Zähler nur ein Stück (z. B. 29 -> 25), waren die
                    # höheren Lesungen falsch (eingefrorenes Bild beim Umschalten o. Ä.) – innerhalb eines Laufs
                    # sinkt der Zähler nie. Also korrigieren statt einen Fehlversuch einzutragen.
                    log.info("Zähler-Korrektur: %d -> %d (höhere Lesung war falsch)", self.last_value, value)
                    self.run.first_wave = min(self.run.first_wave, value)
                    self.run.max_wave = value
                    self.last_value = value
                else:
                    restart_ts = self._drop_ts           # zweite passende Lesung: Neustart bestätigt
                    log.info("Neustart bestätigt: %d -> %d (höchste Welle des Versuchs: %d)",
                             self.last_value, value, self.run.max_wave)
                    info = self._finish()
                    if info:
                        out.append(("run_end", info))
            else:
                self._drop_value, self._drop_ts = value, now     # erste Lesung: noch abwarten
                log.info("Zähler fällt von %d auf %d – warte auf Bestätigung", self.last_value, value)
                return out
        else:
            self._drop_value = None
        if self.run is None:
            start = (restart_ts if restart_ts is not None else now) if value <= START_MAX else None
            self.run = _Run(start_ts=start, first_wave=value, max_wave=value, total=total,
                            first_ts=(restart_ts if restart_ts is not None else now))
            self.armed = True
            log.info("Neuer Lauf bei Welle %d/%d (Start %s)", value, total,
                     "gesehen" if start is not None else "nicht gesehen")

        self.run.max_wave = max(self.run.max_wave, value)
        if total or not self.run.total:                 # Lesung ohne Gesamtzahl ändert ein bekanntes Ziel nicht
            self.run.total = total
        self.last_value, self.total, self._last_seen = value, total, now

        if (self.armed and not self.run.completed and self.run.total and value >= self.run.total - self.offset
                and now - self._last_trigger >= self.cooldown):
            out.append(("candidate", None))
        return out

    def confirm(self, now: float) -> dict:
        """Auslöser bestätigt: Raid zählt. Gibt Dauer/Wellen zurück."""
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
    pos: int = 0                         # Platz in der Liste im Spiel (Anzeige in derselben Reihenfolge)

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
    """Gleicht gelesene Quest-Zeilen mit bekannten Quests ab (OCR-Fehler tolerant)
    und meldet Fortschritt erst, wenn derselbe neue Wert zweimal gelesen wurde."""

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
