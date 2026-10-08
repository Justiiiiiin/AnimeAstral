"""Gelernte Welt-Fenster aus alten Erkundungs-Berichten zurückholen (nach „Vergessen“ oder abgebrochenem Lauf)."""
import json
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401

from astral_monitor import explorer
from astral_monitor.uimap import LOCAL_FILE, UiMap


def _report(folder: Path, stamp: str, worlds: list) -> None:
    (folder / "explore" / stamp).mkdir(parents=True)
    (folder / "explore" / stamp / "report.json").write_text(json.dumps({"worlds": worlds}), encoding="utf-8")


class RestoreTest(unittest.TestCase):
    def test_restore_and_forget(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            _report(data, "20261008_085008", [
                {"name": "W21 Night City", "windows": [
                    {"slot": 9, "window": "Fixer Gigs Fenster", "category": "gigs", "title": "Fixer Gigs"},
                    {"slot": 2, "window": "Crafting Unit Fenster", "category": "crafting", "title": "Crafting"},
                    {"slot": 4, "window": "Progression Fenster", "category": "upgrade_tree",
                     "title": "Street cred progression"}]},
                {"name": "W13 2 City", "windows": [               # gelesen „2 City“, Karte: „W13 Z City“
                    {"slot": 8, "window": "W13 Defense Mode!", "category": "defense", "title": "Defense Mode!"}]}])
            m = UiMap.load(local=data / LOCAL_FILE)
            if not m.list_windows():
                self.skipTest("mitgelieferte Karte fehlt")
            self.assertEqual(explorer.restore_from_reports(data, m), 4)
            m = UiMap.load(local=data / LOCAL_FILE)
            gigs = next(e for e in m.entries if (e.get("extra") or {}).get("category") == "gigs")
            self.assertEqual((gigs.get("extra") or {}).get("category"), "gigs")
            self.assertEqual(m.world_of(gigs), 21)
            self.assertEqual(m.world_of(m.container("W21 Crafting")), 21)
            self.assertEqual((m.container("W21 Progression").get("extra") or {}).get("category"), "progression")
            self.assertEqual(m.world_of(m.container("W13 Defense Mode!")), 13)
            self.assertEqual(explorer.restore_from_reports(data, m), 0)       # schon bekannt: nichts doppelt
            explorer.forget_local(data)                                      # danach zählen alte Berichte nicht
            self.assertEqual(explorer.restore_from_reports(data, UiMap.load(local=data / LOCAL_FILE)), 0)


if __name__ == "__main__":
    unittest.main()


class ProbeTest(unittest.TestCase):
    def test_probe_points_skip_empty(self):
        import numpy as np
        content = np.zeros((270, 480), np.uint8)
        for x in range(40, 200, 16):
            content[150:240, x:x + 8] = 255                       # Inhalt unten links (Kacheln)
        pts = explorer.probe_points(content, [], [0.0, 0.0, 1.0, 1.0])
        self.assertTrue(pts)
        self.assertLessEqual(len(pts), explorer.PROBE_MAX)
        self.assertTrue(all(x < 0.5 and y > 0.5 for x, y in pts))   # leere Flächen werden nicht probiert

    def test_teleporter_in_picture(self):
        words = [("TELEPORT!", [0, 0, 0.1, 0.1]), ("RESPAWN!", [0, 0.2, 0.1, 0.3]), ("Lobby", [0, 0, 0.1, 0.1])]
        self.assertTrue(explorer._is_teleporter(words))
        self.assertFalse(explorer._is_teleporter([("Create", [0, 0, 0.1, 0.1])]))
