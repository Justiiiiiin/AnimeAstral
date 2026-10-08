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


if __name__ == "__main__":
    unittest.main()
