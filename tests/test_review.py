"""Rückfrage nach dem Erkunden: Funde warten auf Bestätigung, korrigierte Arten gelten in der Karte."""
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401

from astral_monitor import review


class ReviewTest(unittest.TestCase):
    def test_flow(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            review.add_finding(data, "Boosts Fenster", {"category": "unknown", "tabs": [], "scroll": [[0.5, 0.5]],
                                                       "actions": ["EQUIP"], "lines": ["Power", "Play"]})
            self.assertEqual([n for n, _e in review.pending(data)], ["Boosts Fenster"])
            self.assertEqual(review.status_of(data, "Boosts Fenster"), review.PENDING)
            self.assertIn("1", review.summary(review.load(data)["Boosts Fenster"]))
            review.set_status(data, "Boosts Fenster", review.OK, "boosts")
            self.assertEqual(review.pending(data), [])
            self.assertEqual(review.category_overrides(data), {"Boosts Fenster": "boosts"})
            # neuer Scan desselben Fensters: bestätigte Art bleibt, wartet wieder auf Bestätigung
            review.add_finding(data, "Boosts Fenster", {"category": "unknown"})
            self.assertEqual(review.load(data)["Boosts Fenster"]["category"], "boosts")
            review.set_status(data, "Boosts Fenster", review.RECHECK)
            self.assertEqual(review.status_of(data, "Boosts Fenster"), review.RECHECK)


    def test_marks_become_map_entries(self):
        """Markierungen des Nutzers: Lage im Roblox-Fenster, „nie drücken“ = Sperrzone, „Liste“ = scrollbar."""
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            review.add_finding(data, "Ranks", {"category": "ranks", "roi": [0.2, 0.2, 0.8, 0.8]})
            review.set_notes(data, "Ranks", [{"box": [0.62, 0.8, 0.9, 0.9], "kind": "never", "text": "Rank Up"},
                                             {"box": [0.1, 0.3, 0.5, 0.7], "kind": "list", "text": "Liste"}],
                             "Rank aufsteigen")
            els = {e["extra"]["annotation"]: e for e in review.annotation_elements(data)}
            self.assertTrue(els["never"]["extra"]["forbid"])
            self.assertEqual(els["never"]["roi"], [0.572, 0.68, 0.74, 0.74])
            self.assertTrue(els["list"]["extra"]["scroll"])
            self.assertEqual(els["list"]["parent"], "Ranks")
            self.assertEqual(review.load(data)["Ranks"]["description"], "Rank aufsteigen")


if __name__ == "__main__":
    unittest.main()
