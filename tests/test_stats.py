import csv
import time
import unittest
from pathlib import Path

import _env
from astral_monitor.stats import RunRecord, StatsStore


def store(name):
    path = Path(_env.DATA) / name
    path.unlink(missing_ok=True)
    return StatsStore(path)


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.st = store("hist.csv")
        now = time.time()
        for i in range(10):
            self.st.add(RunRecord(now - 100 + i, 100.0, None, 25 + i % 3, 100, "abgebrochen", raid="Militech Convoy"))
        self.st.add(RunRecord(now, 230.0, 300.0, 99, 100, "ok", raid="Militech Convoy"))
        self.st.add(RunRecord(now, 80.0, None, 40, 100, "abgebrochen", "geschätzt", raid="Defense"))

    def test_every_run_counts_the_same(self):
        """Alte Zeilen mit „abgebrochen“ zählen genauso wie „ok“ – es gibt keine Fehlversuche."""
        s = self.st.summary(None, "Militech Convoy")
        self.assertEqual(s.attempts, 11)
        self.assertEqual(s.waves_total, sum(25 + i % 3 for i in range(10)) + 99)
        self.assertAlmostEqual(s.avg_duration_all, (10 * 100.0 + 230.0) / 11)
        self.assertAlmostEqual(self.st.summary(None, None).avg_duration_all, (10 * 100.0 + 230.0) / 11)  # ~ zählt nicht
        snap = self.st.snapshot()
        self.assertEqual(snap.total_attempts, 12)
        self.assertFalse(hasattr(s, "failed"))

    def test_histogram_trend_and_best(self):
        hist = dict(self.st.wave_histogram(None, "Militech Convoy"))
        self.assertEqual(sum(hist.values()), 11)          # alle Versuche, auch der bis zum Ende
        self.assertLessEqual(len(hist), 10)               # lesbar: höchstens 10 Balken in runden Schritten
        self.assertEqual(hist["20–29"], 10)
        self.assertEqual(hist["90–99"], 1)
        self.assertEqual(self.st.best_wave("Militech Convoy"), 99)
        self.assertEqual(self.st.best_wave("Defense"), 40)
        self.assertTrue(self.st.trend(None, "Defense"))

    def test_seconds_per_wave_needs_samples(self):
        self.assertAlmostEqual(self.st.seconds_per_wave("Militech Convoy"), 100.0 / 26, delta=2.0)
        self.assertIsNone(store("empty.csv").seconds_per_wave())

    def test_delete_and_reload(self):
        rec = self.st.records[0]
        self.assertTrue(self.st.delete_record(rec))
        self.assertEqual(len(StatsStore(self.st._path).records), 11)

    def test_old_csv_without_raid_column_is_migrated(self):
        path = Path(_env.DATA) / "old.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["ts_end", "duration_s", "cycle_s", "max_wave", "total_waves", "result", "note"])
            w.writerow(["2026-10-05 20:01:02", "241.5", "", 99, 100, "ok", ""])
        st = StatsStore(path)
        self.assertEqual(len(st.records), 1)
        self.assertIn("raid", path.read_text(encoding="utf-8").splitlines()[0])


class WallTests(unittest.TestCase):
    def store(self, waves, raid="Militech Convoy"):
        path = Path(_env.DATA) / f"wall_{len(waves)}_{waves[-1]}.csv"
        path.unlink(missing_ok=True)
        st = StatsStore(path)
        for i, w in enumerate(waves):
            st.records.append(RunRecord(1_000_000 + i * 120, 108.0, None, w, 100, "abgebrochen", "", raid))
        return st

    def test_wall_found_and_broken(self):
        st = self.store([29] * 30)
        wall = st.wall("Militech Convoy")
        self.assertEqual((wall.wave, wall.streak), (29, 30))
        self.assertIsNone(st.wall(None))                       # nur je Raid
        self.assertIsNone(self.store([60] * 20, raid="").wall("Unbekannt"))   # gemischte, nicht erkannte Läufe
        self.assertIsNone(st.wall("Anderer Raid"))
        self.assertIsNone(self.store([29] * 30 + [34]).wall("Militech Convoy"))   # gerade durchbrochen
        self.assertEqual(self.store([29] * 30 + [34, 29, 29]).wall("Militech Convoy").streak, 2)

    def test_no_wall_when_spread_or_few_runs(self):
        self.assertIsNone(self.store([29] * 5).wall("Militech Convoy"))
        self.assertIsNone(self.store([20, 25, 29, 31, 22, 27, 29, 33, 24, 26]).wall("Militech Convoy"))


if __name__ == "__main__":
    unittest.main()


class CombinedStatsTests(unittest.TestCase):
    """Alle Versuche zählen gleich: Wellen, Wellen pro Stunde, Ø Endwelle, Zeit pro Welle."""

    def test_combined_summary(self):
        st = store("combined.csv")
        now = time.time()
        t = now - 2 * 3600
        for i in range(20):
            wave = 25 + i % 5
            dur = wave * 3.7
            t += dur + 20
            st.add(RunRecord(t, dur, None, wave, 100, "ok" if i == 0 else "abgebrochen", raid="Militech Convoy"))
        s = st.summary(None, "Militech Convoy")
        self.assertEqual(s.attempts, 20)
        self.assertEqual(s.waves_total, sum(25 + i % 5 for i in range(20)))
        self.assertEqual(s.best_wave, 29)
        self.assertAlmostEqual(s.avg_wave_all, s.waves_total / 20)
        self.assertAlmostEqual(s.sec_per_wave, 3.7, delta=0.05)
        self.assertGreater(s.waves_per_hour, 0)
        self.assertEqual(sum(c for _l, c in st.wave_histogram(None, "Militech Convoy")), 20)   # alle Versuche
        entry = st.per_raid()[0]
        self.assertEqual((entry["attempts"], entry["waves_total"]), (20, s.waves_total))
        self.assertTrue(any(w > 0 for _h, w in st.hourly_waves(4, "Militech Convoy")))


class FarmTimeTests(unittest.TestCase):
    def test_farm_time_week_and_month(self):
        from datetime import datetime
        from astral_monitor.stats import farm_seconds
        path = Path(_env.DATA) / "farm.csv"
        path.unlink(missing_ok=True)
        store = StatsStore(path)
        base = datetime(2026, 10, 6, 8, 0).timestamp()
        for i in range(10):                                   # 10 Raids im Abstand von 2 Minuten
            store.add(RunRecord(base + i * 120, 110.0, None, 50 + i, 100, "ok", "", "Alvarez"))
        store.add(RunRecord(base + 3 * 3600, 100.0, None, 90, 100, "ok", "", ""))   # nach langer Pause
        recs = store.last_runs(100)
        self.assertAlmostEqual(farm_seconds(recs), 110 + 9 * 120 + 100)            # Pause zählt nicht
        week = store.daily(7, end=datetime(2026, 10, 7))
        self.assertEqual([d["attempts"] for d in week], [0, 0, 0, 0, 0, 11, 0])
        m = store.month(2026, 10)
        self.assertEqual((m["attempts"], m["best_wave"], m["best_day"], m["active_days"]), (11, 90, 6, 1))
        self.assertEqual(m["favorite_raid"], "Alvarez")                             # benannter Raid vor „Unbekannt“
        self.assertEqual(m["peak_hour"], 8)
        self.assertEqual(store.month(2026, 11)["prev_attempts"], 11)
