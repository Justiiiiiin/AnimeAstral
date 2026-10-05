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

    def test_summary_per_raid_and_estimates(self):
        s = self.st.summary(None, "Militech Convoy")
        self.assertEqual((s.ok, s.failed), (1, 10))
        self.assertAlmostEqual(s.avg_fail_duration, 100.0)
        all_ = self.st.summary(None, None)
        self.assertEqual(all_.failed, 11)
        self.assertAlmostEqual(all_.avg_fail_duration, 100.0)       # geschätzte Dauer zählt nicht mit

    def test_histogram_trend_and_best(self):
        hist = dict(self.st.wave_histogram(None, "Militech Convoy"))
        self.assertEqual(sum(hist.values()), 10)
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

    def test_fails_since_last_ok(self):
        st = store("fails.csv")
        st.add(RunRecord(1.0, 10.0, None, 99, 100, "ok"))
        st.add(RunRecord(2.0, 50.0, None, 20, 100, "abgebrochen"))
        st.add(RunRecord(3.0, 70.0, None, 25, 100, "abgebrochen"))
        self.assertEqual(st.fails_since_last_ok(), (2, 60.0))

    def test_old_csv_without_raid_column_is_migrated(self):
        path = Path(_env.DATA) / "old.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["ts_end", "duration_s", "cycle_s", "max_wave", "total_waves", "result", "note"])
            w.writerow(["2026-10-05 20:01:02", "241.5", "", 99, 100, "ok", ""])
        st = StatsStore(path)
        self.assertEqual(len(st.records), 1)
        self.assertIn("raid", path.read_text(encoding="utf-8").splitlines()[0])


if __name__ == "__main__":
    unittest.main()
