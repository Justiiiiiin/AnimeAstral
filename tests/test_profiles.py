"""Raids as a list of names: create, rename (incl. history), delete, clean up old images."""
import tempfile
import time
import unittest
from pathlib import Path

import _env  # noqa: F401
from astral_monitor.profiles import ProfileStore
from astral_monitor.stats import RunRecord, StatsStore


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.store = ProfileStore(self.base / "profiles")

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_rename_delete(self):
        self.assertEqual(self.store.create("  Alvarez   War "), "Alvarez War")
        self.store.create("new leaf")
        with self.assertRaises(ValueError):
            self.store.create("alvarez war")                   # duplicate (ignoring case)
        self.store.save_settings("Alvarez War", {"note": "Boss 27", "trigger_offset": 2})
        self.assertEqual(self.store.rename("Alvarez War", "Alvarez Krieg"), "Alvarez Krieg")
        self.assertEqual(self.store.settings("Alvarez Krieg")["note"], "Boss 27")   # settings move along
        self.assertEqual(self.store.rename("new leaf", "New Leaf"), "New Leaf")      # case only
        self.assertEqual(self.store.names(), ["Alvarez Krieg", "New Leaf"])
        with self.assertRaises(ValueError):
            self.store.rename("New Leaf", "alvarez krieg")
        with self.assertRaises(ValueError):
            self.store.rename("Gibt es nicht", "X")
        self.store.delete("New Leaf")
        self.assertEqual(self.store.names(), ["Alvarez Krieg"])

    def test_remove_reference_images(self):
        name = self.store.create("Owl")
        (self.base / "profiles" / name / "ref_01.jpg").write_bytes(b"x")
        (self.base / "profiles" / name / "ref_02.jpg").write_bytes(b"x")
        self.store.save_settings(name, {"note": "bleibt"})
        self.assertEqual(self.store.remove_reference_images(), 2)
        self.assertEqual(self.store.settings(name), {"note": "bleibt"})

    def test_stats_follow_rename(self):
        stats = StatsStore(self.base / "history.csv")
        now = time.time()
        for raid in ("Owl", "Owl", "Other"):
            stats.add(RunRecord(now, 60.0, 60.0, 100, 100, "ok", "", raid))
        self.assertEqual(stats.rename_raid("Owl", "Owl Suppression"), 2)
        again = StatsStore(self.base / "history.csv")                    # also changed in the file
        self.assertEqual(sorted(r.raid for r in again.records), ["Other", "Owl Suppression", "Owl Suppression"])


if __name__ == "__main__":
    unittest.main()


class RecentRaidTests(unittest.TestCase):
    def test_recent_first(self):
        from astral_monitor.settings import order_raids
        self.assertEqual(order_raids(["b", "A", "c", "d"], ["c", "gone", "A"]), ["c", "A", "b", "d"])
