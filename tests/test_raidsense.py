"""Raid-Erkennung über das Raid-Fenster (raidsense) – ohne Bilder."""
import unittest

import _env  # noqa: F401

from astral_monitor.raidsense import DropIndex, DropWatcher, RaidSense, match_name


class RaidSenseTest(unittest.TestCase):
    def test_match_known_with_typos(self):
        known = ["Alvarez War", "Holy Grail War", "Titan Wall Defense"]
        self.assertEqual(match_name("Holy Grall War", known), "Holy Grail War")
        self.assertEqual(match_name("Titan Walt Defense", known), "Titan Wall Defense")
        self.assertIsNone(match_name("Zaban Rush!", known))
        self.assertIsNone(match_name("Soul Raid", ["Sins Raid"]))         # ähnliche Namen nicht verwechseln

    def test_window_then_teleport_then_new_run(self):
        rs = RaidSense()
        rs.wave_visible(False, 0.0)                       # Lobby: kein Zähler
        rs.seen_name("Holy Grail War", ["Holy Grail War"], 1.0)
        rs.seen_name("Holy Grail War", ["Holy Grail War"], 3.0)
        rs.wave_visible(False, 5.0)
        rs.wave_visible(True, 12.0)                       # im Raid angekommen
        self.assertEqual(rs.take(12.0), "Holy Grail War")
        self.assertIsNone(rs.take(13.0))                  # nur einmal

    def test_only_looked_at_window_stays_in_raid(self):
        rs = RaidSense()
        rs.wave_visible(True, 0.0)                        # mitten im Raid, Zähler die ganze Zeit sichtbar
        rs.seen_name("Alvarez War", [], 1.0)
        rs.seen_name("Alvarez War", [], 3.0)
        rs.wave_visible(True, 4.0)
        self.assertIsNone(rs.take(5.0))                   # Auto Retry im selben Raid: nicht umstellen

    def test_single_misread_is_ignored(self):
        rs = RaidSense()
        rs.seen_name("Clover Raid", [], 1.0)
        self.assertIsNone(rs.pending)                     # erst nach zweimal lesen
        rs.seen_name("Clover Rald", [], 3.0)              # Lesefehler zählt als derselbe Name
        self.assertEqual(rs.pending, "Clover Raid")


class DropTest(unittest.TestCase):
    TABLE = {"Night Raid": ["Street Cred Token", "Cyberware Token", "Yen"],
             "Tempest Raid": ["Tempest Token", "Cyberware Token"],
             "Holy Grail War": ["Grail Shard", "Servant Token"]}

    def test_only_unique_drops_count(self):
        idx = DropIndex(self.TABLE)
        self.assertNotIn("cyberwaretoken", idx.unique)      # in zwei Raids: sagt nichts
        # echte Lesung aus dem Drop-Feld (Screenshot 08.10.2026): Lesefehler, fremde Tokens, gelöschte Pets
        words = ["Oni", "Token", "Sreet", "Cred", "Token", "Tempe", "Eddie", "Magic", "Token", "Rain", "Ultima"]
        self.assertEqual(idx.votes(words), {"Night Raid": 1})

    def test_watcher_needs_two_reads_and_clear_lead(self):
        w = DropWatcher()
        self.assertIsNone(w.feed({"Night Raid": 1}))
        self.assertEqual(w.feed({"Night Raid": 2}), "Night Raid")
        w.reset()
        self.assertIsNone(w.feed({"Night Raid": 1, "Holy Grail War": 1}))   # Gleichstand
        self.assertIsNone(w.feed({}))


if __name__ == "__main__":
    unittest.main()
