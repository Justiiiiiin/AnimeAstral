"""Raid-Verlauf (CSV) und Kennzahlen. Jeder Versuch ist ein beendeter Raid – in Anime Astral scheitert ein Raid
nicht, man kommt nur unterschiedlich weit (jede Welle gibt Belohnungen). Alte Zeilen mit Ergebnis „abgebrochen“
(bis 0.7.0) zählen genauso."""
from __future__ import annotations

import csv
import logging
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("stats")

CSV_FIELDS = ["ts_end", "duration_s", "cycle_s", "max_wave", "total_waves", "result", "note", "raid"]
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class RunRecord:
    ts_end: float                    # Unix-Zeit
    duration_s: Optional[float]
    cycle_s: Optional[float]
    max_wave: int
    total_waves: int
    result: str                      # immer "ok"; ältere Dateien: "abgebrochen" – wird nicht mehr unterschieden
    note: str = ""
    raid: str = ""                   # Raid-Name aus der Profil-Erkennung

    @property
    def estimated(self) -> bool:
        return "geschätzt" in self.note


@dataclass
class Summary:
    """Kennzahlen für einen Zeitraum – alle Versuche gleich behandelt."""
    attempts: int = 0
    waves_total: int = 0
    best_wave: int = 0
    avg_wave_all: Optional[float] = None
    avg_duration_all: Optional[float] = None      # nur gemessene Dauern
    sec_per_wave: Optional[float] = None
    waves_per_hour: Optional[float] = None
    attempts_per_hour: Optional[float] = None


@dataclass
class StatsSnapshot:
    """Schnelle Kennzahlen für die Hauptseite und Discord."""
    total_attempts: int = 0                       # inkl. Startwert (total_offset) – zugleich die Raid-Nummer
    session_attempts: int = 0
    session_waves: int = 0
    waves_per_hour: Optional[float] = None
    avg_wave: Optional[float] = None
    avg_duration: Optional[float] = None          # letzte 50 gemessene Versuche
    per_hour: Optional[float] = None              # Versuche pro Stunde in dieser Session


@dataclass
class Wall:
    """„Wand“: die Welle, an der die meisten der letzten Versuche eines Raids enden (z. B. eine Boss-Welle)."""
    wave: int
    streak: int          # so viele Versuche in Folge sind nicht darüber hinausgekommen
    share: float         # Anteil der letzten Versuche, die genau dort enden


WALL_RECENT = 20         # betrachtete letzte Versuche
WALL_MIN_RUNS = 8        # erst ab so vielen Versuchen von einer Wand sprechen
WALL_SHARE = 0.6         # so viele davon müssen an derselben Welle enden


def _span_hours(recs: list) -> float:
    """Aktive Zeit vom Start des ersten bis zum Ende des letzten Versuchs (in Stunden)."""
    if not recs:
        return 0.0
    first = min(recs, key=lambda r: r.ts_end)
    start = first.ts_end - (first.duration_s or 0)
    return (max(r.ts_end for r in recs) - start) / 3600


FARM_GAP = 15 * 60       # längere Lücken zwischen zwei Raid-Enden zählen als Pause, nicht als Farmzeit


def farm_seconds(recs: list) -> float:
    """Farmzeit: Abstände zwischen aufeinanderfolgenden Raid-Enden (bis FARM_GAP); der erste Raid eines Blocks
    zählt mit seiner gemessenen Dauer (sonst mit der typischen Dauer)."""
    if not recs:
        return 0.0
    ends = sorted(recs, key=lambda r: r.ts_end)
    measured = [r.duration_s for r in ends if r.duration_s]
    typical = statistics.median(measured) if measured else 0.0
    total, prev = 0.0, None
    for rec in ends:
        gap = None if prev is None else rec.ts_end - prev
        total += gap if gap is not None and gap <= FARM_GAP else (rec.duration_s or typical)
        prev = rec.ts_end
    return total


def _opt_float(text) -> Optional[float]:
    try:
        return float(text) if text not in ("", None) else None
    except ValueError:
        return None


def _mean(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


class StatsStore:
    def __init__(self, path: Path, offset: int = 0) -> None:
        self._path = path
        self._lock = threading.RLock()
        self.offset = offset
        self.records: list[RunRecord] = []
        self.session_start = time.time()
        self._load()

    # ------------------------------------------------------------------ Datei
    def _load(self) -> None:
        migrate = False
        try:
            with self._path.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                migrate = reader.fieldnames is not None and "raid" not in reader.fieldnames
                for row in reader:
                    try:
                        ts = datetime.strptime(row["ts_end"], _TS_FORMAT).timestamp()
                        self.records.append(RunRecord(
                            ts, _opt_float(row.get("duration_s")), _opt_float(row.get("cycle_s")),
                            int(row.get("max_wave") or 0), int(row.get("total_waves") or 0),
                            row.get("result", "ok") or "ok", row.get("note", "") or "",
                            row.get("raid", "") or ""))
                    except (KeyError, ValueError):
                        continue
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Verlauf konnte nicht gelesen werden: %s", exc)
        if migrate and self.records:
            self._rewrite()

    @staticmethod
    def _row(rec: RunRecord) -> list:
        return [datetime.fromtimestamp(rec.ts_end).strftime(_TS_FORMAT),
                "" if rec.duration_s is None else f"{rec.duration_s:.1f}",
                "" if rec.cycle_s is None else f"{rec.cycle_s:.1f}",
                rec.max_wave, rec.total_waves, rec.result, rec.note, rec.raid]

    def _rewrite(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        try:
            with tmp.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(CSV_FIELDS)
                for rec in self.records:
                    writer.writerow(self._row(rec))
            tmp.replace(self._path)
        except OSError as exc:
            log.warning("Verlauf konnte nicht aktualisiert werden: %s", exc)

    def add(self, rec: RunRecord) -> None:
        with self._lock:
            self.records.append(rec)
            new_file = not self._path.exists()
            try:
                with self._path.open("a", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    if new_file:
                        writer.writerow(CSV_FIELDS)
                    writer.writerow(self._row(rec))
            except OSError as exc:
                log.error("Verlauf konnte nicht gespeichert werden: %s", exc)

    # ---------------------------------------------------------------- Verwaltung
    def begin_session(self) -> None:
        self.session_start = time.time()

    def set_offset(self, offset: int) -> None:
        self.offset = max(0, int(offset))

    # ------------------------------------------------------------- Kennzahlen
    def _in_range(self, since: Optional[float], raid: Optional[str] = None) -> list[RunRecord]:
        return [r for r in self.records
                if (since is None or r.ts_end >= since) and (raid is None or (r.raid or "Unbekannt") == raid)]

    def raid_names(self) -> list[str]:
        """Alle Profilnamen im Verlauf (häufigste zuerst)."""
        with self._lock:
            counts: dict[str, int] = {}
            for r in self.records:
                counts[r.raid or "Unbekannt"] = counts.get(r.raid or "Unbekannt", 0) + 1
            return [n for n, _c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    def best_wave(self, raid: Optional[str] = None) -> int:
        with self._lock:
            return max((r.max_wave for r in self._in_range(None, raid)), default=0)

    def wall(self, raid: Optional[str]) -> Optional[Wall]:
        """Wand eines Raids (nur je Raid sinnvoll, nicht über alle Raids gemischt)."""
        if not raid or raid == "Unbekannt":            # nicht erkannte Läufe sind verschiedene Raids gemischt
            return None
        with self._lock:
            recs = self._in_range(None, raid)
        recent = recs[-WALL_RECENT:]
        if len(recent) < WALL_MIN_RUNS:
            return None
        counts: dict[int, int] = {}
        for r in recent:
            counts[r.max_wave] = counts.get(r.max_wave, 0) + 1
        wave, n = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
        if n / len(recent) < WALL_SHARE or any(r.max_wave >= r.total_waves for r in recent[-3:] if r.total_waves):
            return None
        streak = 0
        for r in reversed(recs):
            if r.max_wave > wave:
                break
            streak += 1
        return Wall(wave, streak, n / len(recent)) if streak else None   # gerade durchbrochen: keine Wand

    def attempts(self, raid: Optional[str] = None) -> int:
        with self._lock:
            return len(self._in_range(None, raid))

    def seconds_per_wave(self, raid: Optional[str] = None) -> Optional[float]:
        """Typische Sekunden pro Welle aus Läufen mit gemessener Dauer (für die Dauer-Schätzung)."""
        with self._lock:
            def sample(name: Optional[str]) -> list[float]:
                return [r.duration_s / r.max_wave for r in self._in_range(None, name)
                        if r.duration_s and r.max_wave >= 5 and not r.estimated][-30:]
            values = sample(raid) if raid else []
            if len(values) < 3:
                values = sample(None)
            return statistics.median(values) if len(values) >= 3 else None

    def wave_histogram(self, since: Optional[float] = None, raid: Optional[str] = None,
                       max_bars: int = 10) -> list[tuple[str, int]]:
        """Verteilung der Endwellen: [(Beschriftung, Anzahl)] in runden Schritten (1, 2, 5, 10, 20 …), höchstens
        ~10 Balken – vorher bis zu 20 Balken in krummen Schritten, deren Beschriftung unlesbar war."""
        with self._lock:
            waves = [r.max_wave for r in self._in_range(since, raid)]
        if not waves:
            return []
        lo, hi = min(waves), max(waves)
        size = next((n for n in (1, 2, 5, 10, 20, 25, 50, 100) if hi // n - lo // n + 1 <= max_bars), 100)
        out = []
        for base in range((lo // size) * size, hi + 1, size):
            count = sum(1 for w in waves if base <= w < base + size)
            out.append((str(base) if size == 1 else f"{base}–{base + size - 1}", count))
        return out

    def trend(self, since: Optional[float] = None, raid: Optional[str] = None,
              by_day: bool = False, limit: int = 24) -> list[tuple[str, float, int]]:
        """Ø erreichte Welle je Stunde (oder Tag): [(Beschriftung, Ø Welle, Anzahl Versuche)]."""
        with self._lock:
            recs = self._in_range(since, raid)
        groups: dict[float, list[int]] = {}
        for r in recs:
            dt = datetime.fromtimestamp(r.ts_end)
            base = dt.replace(hour=0, minute=0, second=0, microsecond=0) if by_day \
                else dt.replace(minute=0, second=0, microsecond=0)
            groups.setdefault(base.timestamp(), []).append(r.max_wave)
        out = []
        for key in sorted(groups)[-limit:]:
            label = datetime.fromtimestamp(key).strftime("%d.%m." if by_day else "%H")
            out.append((label, sum(groups[key]) / len(groups[key]), len(groups[key])))
        return out

    def summary(self, since: Optional[float] = None, raid: Optional[str] = None) -> Summary:
        with self._lock:
            recs = self._in_range(since, raid)
            s = Summary()
            if recs:
                s.attempts = len(recs)
                s.waves_total = sum(r.max_wave for r in recs)
                s.best_wave = max(r.max_wave for r in recs)
                s.avg_wave_all = s.waves_total / len(recs)
                exact = [r for r in recs if r.duration_s and not r.estimated]
                s.avg_duration_all = _mean(r.duration_s for r in exact)
                if exact:
                    s.sec_per_wave = sum(r.duration_s for r in exact) / max(1, sum(r.max_wave for r in exact))
                hours = _span_hours(recs)
                if hours >= 0.1:
                    s.waves_per_hour = s.waves_total / hours
                    s.attempts_per_hour = s.attempts / hours
            return s

    def snapshot(self) -> StatsSnapshot:
        with self._lock:
            session = [r for r in self.records if r.ts_end >= self.session_start]
            elapsed_h = (time.time() - self.session_start) / 3600
            durations = [r.duration_s for r in self.records if r.duration_s and not r.estimated][-50:]
            span = _span_hours(session)
            waves = sum(r.max_wave for r in session)
            return StatsSnapshot(
                total_attempts=self.offset + len(self.records),
                session_attempts=len(session),
                session_waves=waves,
                waves_per_hour=(waves / span) if span >= 0.1 else None,
                avg_wave=(waves / len(session)) if session else None,
                avg_duration=sum(durations) / len(durations) if durations else None,
                per_hour=len(session) / elapsed_h if elapsed_h >= 5 / 60 else None,
            )

    def hourly_waves(self, hours: int = 10, raid: Optional[str] = None) -> list[tuple[int, int]]:
        """[(Stunde 0-23, geschaffte Wellen)] für die letzten `hours` Stunden."""
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        starts = [(now.timestamp() - i * 3600) for i in range(hours - 1, -1, -1)]
        with self._lock:
            return [(datetime.fromtimestamp(st).hour,
                     sum(r.max_wave for r in self.records if st <= r.ts_end < st + 3600
                         and (raid is None or (r.raid or "Unbekannt") == raid)))
                    for st in starts]

    def daily(self, days: int = 7, raid: Optional[str] = None, end: Optional[datetime] = None) -> list[dict]:
        """Je Kalendertag (älteste zuerst, bis einschließlich `end`/heute): Versuche, Wellen, Farmzeit (s)."""
        from datetime import timedelta
        last = (end or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        out = []
        with self._lock:
            for i in range(days - 1, -1, -1):
                start = last - timedelta(days=i)
                lo, hi = start.timestamp(), (start + timedelta(days=1)).timestamp()
                recs = [r for r in self.records if lo <= r.ts_end < hi
                        and (raid is None or (r.raid or "Unbekannt") == raid)]
                out.append({"day": start.date(), "attempts": len(recs), "waves": sum(r.max_wave for r in recs),
                            "farm_s": farm_seconds(recs)})
        return out

    def month(self, year: int, month: int) -> dict:
        """Monatsrückblick: Summen, Bestwerte, bester Tag, Lieblingsraid, Raids je Tag, Vergleich zum Vormonat."""
        import calendar
        n_days = calendar.monthrange(year, month)[1]
        lo = datetime(year, month, 1).timestamp()
        hi = datetime(year + (month == 12), month % 12 + 1, 1).timestamp()
        py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
        plo = datetime(py, pm, 1).timestamp()
        with self._lock:
            recs = [r for r in self.records if lo <= r.ts_end < hi]
            prev = [r for r in self.records if plo <= r.ts_end < lo]
        per_day = [0] * n_days
        for r in recs:
            per_day[datetime.fromtimestamp(r.ts_end).day - 1] += 1
        raids: dict[str, int] = {}
        for r in recs:
            raids[r.raid or "Unbekannt"] = raids.get(r.raid or "Unbekannt", 0) + 1
        hours: dict[int, int] = {}
        for r in recs:
            h = datetime.fromtimestamp(r.ts_end).hour
            hours[h] = hours.get(h, 0) + 1
        best_day = max(range(n_days), key=lambda i: per_day[i]) if recs else None
        named = {k: v for k, v in raids.items() if k != "Unbekannt"} or raids     # benannte Raids bevorzugen
        favorite = max(named.items(), key=lambda kv: kv[1])[0] if named else ""
        return {"year": year, "month": month, "attempts": len(recs), "waves": sum(r.max_wave for r in recs),
                "farm_s": farm_seconds(recs), "best_wave": max((r.max_wave for r in recs), default=0),
                "avg_wave": (sum(r.max_wave for r in recs) / len(recs)) if recs else None,
                "per_day": per_day, "best_day": (best_day + 1) if best_day is not None else None,
                "best_day_attempts": per_day[best_day] if best_day is not None else 0,
                "favorite_raid": favorite, "favorite_count": raids.get(favorite, 0),
                "peak_hour": max(hours.items(), key=lambda kv: kv[1])[0] if hours else None,
                "active_days": sum(1 for n in per_day if n),
                "prev_attempts": len(prev), "prev_waves": sum(r.max_wave for r in prev)}

    def per_raid(self, since: Optional[float] = None) -> list[dict]:
        """Kennzahlen je Raid-Name (leerer Name = „Unbekannt“)."""
        with self._lock:
            groups: dict[str, list[RunRecord]] = {}
            for rec in self._in_range(since):
                groups.setdefault(rec.raid or "Unbekannt", []).append(rec)
            out = []
            for name, recs in groups.items():
                waves = [r.max_wave for r in recs]
                exact_all = [r for r in recs if r.duration_s and not r.estimated]
                hours = _span_hours(recs)
                avg = _mean(r.duration_s for r in exact_all)
                out.append({"raid": name, "attempts": len(recs), "waves_total": sum(waves),
                            "avg_duration_all": avg, "avg": avg,
                            "waves_per_hour": (sum(waves) / hours) if hours >= 0.1 else None,
                            "best_wave": max(waves), "avg_wave": sum(waves) / len(waves)})
            out.sort(key=lambda d: (-d["attempts"], d["raid"]))
            return out

    def last_runs(self, n: int = 100, since: Optional[float] = None,
                  raid: Optional[str] = None) -> list[RunRecord]:
        with self._lock:
            return list(reversed(self._in_range(since, raid)[-n:]))

    def rename_raid(self, old: str, new: str) -> int:
        """Raid umbenennen: alle bisherigen Versuche zählen danach zum neuen Namen. Rückgabe: Anzahl."""
        with self._lock:
            count = 0
            for rec in self.records:
                if rec.raid == old:
                    rec.raid = new
                    count += 1
            if count:
                self._rewrite()
            return count

    def delete_record(self, rec: RunRecord) -> bool:
        """Entfernt einen einzelnen Eintrag dauerhaft (z. B. eine Fehllesung)."""
        with self._lock:
            for i, r in enumerate(self.records):
                if r is rec:
                    del self.records[i]
                    self._rewrite()
                    return True
            return False
