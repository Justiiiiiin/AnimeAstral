"""Raid-Verlauf (CSV) und Kennzahlen. Jeder Versuch ist ein beendeter Raid – in Anime Astral scheitert ein Raid
nicht, man kommt nur unterschiedlich weit (jede Welle gibt Belohnungen). Alte Zeilen mit Ergebnis „abgebrochen“
(bis 0.7.0) zählen genauso."""
from __future__ import annotations

import csv
import functools
import logging
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("stats")

TIME_BOUND = {"hourly_waves", "daily"}       # hängen von der aktuellen Uhrzeit ab (Schlüssel enthält die Minute)


def _key_part(value):
    """Zeitgrenzen („seit …“) auf die Minute runden, damit „letzte 12 Std.“ den Zwischenspeicher trifft."""
    return int(value // 60) if isinstance(value, float) else value


def _cached(fn):
    """Ergebnis merken, bis sich der Verlauf ändert (neuer Raid, Löschen, Umbenennen, Archiv). Die Statistik-Seite
    fragt alle 10 s viele Kennzahlen ab – mit einem Jahr Verlauf (>100 000 Raids) wären das sonst ~0,3 s Rechenzeit
    im Oberflächen-Thread."""
    name = fn.__name__

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        key = (name, tuple(_key_part(a) for a in args), tuple(sorted((k, _key_part(v)) for k, v in kwargs.items())),
               int(time.time() // 60) if name in TIME_BOUND else 0)
        with self._lock:
            state = (id(self.records), len(self.records), self.records[-1].ts_end if self.records else 0, self._edits)
            if state != self._cache_state or len(self._cache) > 300:
                self._cache, self._cache_state = {}, state
            if key not in self._cache:
                self._cache[key] = fn(self, *args, **kwargs)
            return self._cache[key]
    return wrapper

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


def _mean(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


class StatsStore:
    def __init__(self, path: Path, offset: int = 0) -> None:
        self._path = path
        self._lock = threading.RLock()
        self.offset = offset
        self.records: list[RunRecord] = []
        self._cache: dict = {}
        self._cache_state: tuple = ()
        self._edits = 0                              # zählt Änderungen ohne neue Zeile (Umbenennen)
        self._hours: dict = {}                       # Stunden-Schlüssel (Ortszeit), siehe _hour_key
        self.session_start = time.time()
        self._load()

    # ------------------------------------------------------------------ Datei
    def _load(self) -> None:
        migrate = False
        hours: dict = {}                                 # „JJJJ-MM-TT HH“ -> Zeitstempel der Stunde (Ortszeit)
        try:
            with self._path.open(newline="", encoding="utf-8") as fh:
                reader = csv.reader(fh)                  # schneller als DictReader (Spalten per Index)
                header = next(reader, None) or []
                migrate = bool(header) and "raid" not in header
                col = {name: header.index(name) for name in CSV_FIELDS if name in header}
                width = len(header)

                def cell(row, name, default=""):
                    i = col.get(name)
                    return row[i] if i is not None and i < len(row) else default
                current = header == CSV_FIELDS           # heutiges Format: Spalten direkt entpacken (schnell)
                append = self.records.append
                for row in reader:
                    if len(row) < width - 1:             # alte Zeilen ohne Raid-Spalte sind eine Spalte kürzer
                        continue
                    try:
                        if current and len(row) == 8:
                            stamp, dur, cyc, wave, total, result, note, raid = row
                        else:
                            stamp, dur, cyc = cell(row, "ts_end"), cell(row, "duration_s"), cell(row, "cycle_s")
                            wave, total = cell(row, "max_wave"), cell(row, "total_waves")
                            result, note, raid = cell(row, "result", "ok"), cell(row, "note"), cell(row, "raid")
                        base = hours.get(stamp[:13])
                        if base is None:                 # Umrechnung in Ortszeit nur einmal je Stunde
                            base = hours[stamp[:13]] = datetime.fromisoformat(stamp[:13] + ":00:00").timestamp()
                        append(RunRecord(base + int(stamp[14:16]) * 60 + int(stamp[17:19]),
                                         float(dur) if dur else None, float(cyc) if cyc else None,
                                         int(wave or 0), int(total or 0), result or "ok", note, raid))
                    except (IndexError, ValueError):
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

    def archive(self, folder: Path) -> Optional[Path]:
        """Statistik ins Archiv verschieben und neu beginnen. Rückgabe: Archivdatei (None = nichts zu archivieren)."""
        with self._lock:
            if not self.records:
                return None
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            target = folder / f"raid_history_{stamp}.csv"
            self._rewrite()                            # vollständigen Stand sichern
            self._path.replace(target)
            self.records = []
            self.offset = 0
            self.session_start = time.time()
            return target

    @staticmethod
    def archives(folder: Path) -> list[Path]:
        """Archivierte Statistiken, neueste zuerst."""
        return sorted(folder.glob("raid_history_*.csv"), reverse=True) if folder.is_dir() else []

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
        recs = self.records if since is None else self._tail_since(since)
        if raid is None:
            return list(recs)
        return [r for r in recs if (r.raid or "Unbekannt") == raid]

    def _hour_key(self, ts: float) -> tuple[float, float]:
        """(Beginn der Ortszeit-Stunde, Beginn des Ortszeit-Tages) – je volle Stunde nur einmal berechnet
        (datetime.fromtimestamp für jeden einzelnen Raid war der teuerste Teil der Auswertungen)."""
        bucket = int(ts // 3600)
        hit = self._hours.get(bucket)
        if hit is None:
            hour = datetime.fromtimestamp(bucket * 3600).replace(minute=0, second=0, microsecond=0)
            hit = (hour.timestamp(), hour.replace(hour=0).timestamp())
            self._hours[bucket] = hit
        return hit

    @_cached
    def raid_names(self) -> list[str]:
        """Alle Profilnamen im Verlauf (häufigste zuerst)."""
        with self._lock:
            counts: dict[str, int] = {}
            for r in self.records:
                counts[r.raid or "Unbekannt"] = counts.get(r.raid or "Unbekannt", 0) + 1
            return [n for n, _c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    @_cached
    def best_wave(self, raid: Optional[str] = None) -> int:
        with self._lock:
            return max((r.max_wave for r in self._in_range(None, raid)), default=0)

    @_cached
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

    @_cached
    def attempts(self, raid: Optional[str] = None) -> int:
        with self._lock:
            return len(self._in_range(None, raid))

    @_cached
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

    @_cached
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
        counts: dict = {}
        for w in waves:
            counts[w // size] = counts.get(w // size, 0) + 1
        out = []
        for base in range((lo // size) * size, hi + 1, size):
            out.append((str(base) if size == 1 else f"{base}–{base + size - 1}", counts.get(base // size, 0)))
        return out

    @_cached
    def trend(self, since: Optional[float] = None, raid: Optional[str] = None,
              by_day: bool = False, limit: int = 24) -> list[tuple[str, float, int]]:
        """Ø erreichte Welle je Stunde (oder Tag): [(Beschriftung, Ø Welle, Anzahl Versuche)]."""
        groups: dict[float, list[int]] = {}
        with self._lock:
            recs = self.records if since is None else self._tail_since(since)
            for r in reversed(recs):                       # neueste zuerst, aufhören sobald genug Gruppen da sind
                if raid is not None and (r.raid or "Unbekannt") != raid:
                    continue
                base = self._hour_key(r.ts_end)[1 if by_day else 0]
                if base not in groups and len(groups) >= limit:
                    break
                groups.setdefault(base, []).append(r.max_wave)
        out = []
        for key in sorted(groups)[-limit:]:
            label = datetime.fromtimestamp(key).strftime("%d.%m." if by_day else "%H")
            out.append((label, sum(groups[key]) / len(groups[key]), len(groups[key])))
        return out

    @_cached
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

    def _tail_since(self, since: float) -> list[RunRecord]:
        """Versuche ab `since`, von hinten gesucht (Verlauf ist zeitlich sortiert) – schnell auch bei großem Verlauf."""
        out = []
        for r in reversed(self.records):
            if r.ts_end < since:
                break
            out.append(r)
        out.reverse()
        return out

    def snapshot(self) -> StatsSnapshot:
        with self._lock:
            session = self._tail_since(self.session_start)
            elapsed_h = (time.time() - self.session_start) / 3600
            durations = []
            for r in reversed(self.records):               # nur die letzten 50 gemessenen (nicht alles durchgehen)
                if r.duration_s and not r.estimated:
                    durations.append(r.duration_s)
                    if len(durations) == 50:
                        break
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

    @_cached
    def hourly_waves(self, hours: int = 10, raid: Optional[str] = None) -> list[tuple[int, int]]:
        """[(Stunde 0-23, geschaffte Wellen)] für die letzten `hours` Stunden."""
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        starts = [(now.timestamp() - i * 3600) for i in range(hours - 1, -1, -1)]
        with self._lock:
            recent = [r for r in self._tail_since(starts[0]) if raid is None or (r.raid or "Unbekannt") == raid]
        return [(datetime.fromtimestamp(st).hour, sum(r.max_wave for r in recent if st <= r.ts_end < st + 3600))
                for st in starts]

    @_cached
    def daily(self, days: int = 7, raid: Optional[str] = None, end: Optional[datetime] = None) -> list[dict]:
        """Je Kalendertag (älteste zuerst, bis einschließlich `end`/heute): Versuche, Wellen, Farmzeit (s)."""
        from datetime import timedelta
        last = (end or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        out = []
        with self._lock:
            first = (last - timedelta(days=days - 1)).timestamp()
            recent = [r for r in self._tail_since(first) if raid is None or (r.raid or "Unbekannt") == raid]
            for i in range(days - 1, -1, -1):
                start = last - timedelta(days=i)
                lo, hi = start.timestamp(), (start + timedelta(days=1)).timestamp()
                recs = [r for r in recent if lo <= r.ts_end < hi]
                out.append({"day": start.date(), "attempts": len(recs), "waves": sum(r.max_wave for r in recs),
                            "farm_s": farm_seconds(recs)})
        return out

    @_cached
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

    @_cached
    def personal_records(self) -> dict:
        """Bestwerte über den ganzen Verlauf: Bestwelle, stärkster Tag (Raids/Wellen), beste Stunde (Wellen),
        längste Session (zusammenhängende Farmzeit, Pausen über FARM_GAP trennen)."""
        with self._lock:
            recs = sorted(self.records, key=lambda r: r.ts_end)
        out: dict = {"best_wave": None, "best_day": None, "best_hour": None, "longest": None}
        if not recs:
            return out
        best = max(recs, key=lambda r: (r.max_wave, -r.ts_end))
        out["best_wave"] = (best.max_wave, best.ts_end, best.raid)
        days: dict = {}
        hours: dict = {}
        with self._lock:
            for r in recs:
                hour_ts, day_ts = self._hour_key(r.ts_end)
                d = days.get(day_ts)
                if d is None:
                    d = days[day_ts] = [0, 0]
                d[0] += 1
                d[1] += r.max_wave
                hours[hour_ts] = hours.get(hour_ts, 0) + r.max_wave
        day_ts, (n, waves) = max(days.items(), key=lambda kv: (kv[1][0], kv[1][1]))
        out["best_day"] = (datetime.fromtimestamp(day_ts).date(), n, waves)
        hour_ts, waves = max(hours.items(), key=lambda kv: kv[1])
        out["best_hour"] = (datetime.fromtimestamp(hour_ts), waves)
        blocks, current = [], [recs[0]]
        for prev, rec in zip(recs, recs[1:]):
            if rec.ts_end - prev.ts_end > FARM_GAP:
                blocks.append(current)
                current = []
            current.append(rec)
        blocks.append(current)
        longest = max(blocks, key=farm_seconds)
        out["longest"] = (farm_seconds(longest), longest[0].ts_end - (longest[0].duration_s or 0), len(longest))
        return out

    @_cached
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
            self._edits += 1
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
