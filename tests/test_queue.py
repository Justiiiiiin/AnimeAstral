"""Makro-Warteschlange: wann verlassen, Gigs-Zeiten, Pet-Raster aus Namensschildern – ohne Roblox/OCR."""
import unittest

import _env  # noqa: F401
import numpy as np

from astral_monitor.automation import hud_locate, leave_before, next_task, parse_timer, pet_tiles


class QueueTest(unittest.TestCase):
    def test_leave_only_before_another_raid(self):
        tasks = [{"kind": "raid", "target": "Alvarez War"}, {"kind": "autoroll", "target": "Pets"},
                 {"kind": "raid", "target": "Holy Grail War"}, {"kind": "raid", "target": "Holy Grail War"}]
        self.assertFalse(leave_before(tasks[0], next_task(tasks, 0, False)))   # danach Gacha: drinbleiben
        self.assertFalse(leave_before(tasks[2], next_task(tasks, 2, False)))   # gleicher Raid folgt
        self.assertFalse(leave_before(tasks[3], next_task(tasks, 3, False)))   # Ende der Schlange
        self.assertTrue(leave_before(tasks[3], next_task(tasks, 3, True)))     # Schleife: Alvarez War folgt
        self.assertTrue(leave_before({"kind": "raid", "target": "A"}, {"kind": "raid_join", "target": "B"}))

    def test_parse_timer(self):
        self.assertEqual(parse_timer("1:20:40"), 4840)
        self.assertEqual(parse_timer("33:57"), 2037)
        self.assertIsNone(parse_timer("3/3"))
        self.assertIsNone(parse_timer("12:75"))

    def test_pet_grid_from_labels(self):
        # 3 Zeilen × 8 Spalten Namensschilder (Lage wie im echten Pets-Fenster), in der letzten Zeile 5 Pets
        words = []
        for r, y in enumerate((0.45, 0.63, 0.82)):
            for c in range(8 if r < 2 else 5):
                x = 0.142 + c * 0.102
                words.append(("Maine", [x - 0.02, y - 0.009, x + 0.02, y + 0.009]))
        frame = np.zeros((867, 1525, 3), np.uint8)                       # leere Felder: glatt
        tiles = pet_tiles(frame, [0.06, 0.3, 0.94, 0.86], words)
        self.assertEqual(len(tiles), 21)
        last = tiles[-1]
        self.assertAlmostEqual((last[0] + last[2]) / 2, 0.142 + 4 * 0.102, places=3)
        self.assertLess(last[1], 0.82)                                   # Kachel liegt über ihrem Namen


    def test_hud_from_labels(self):
        # Beschriftungen wie bei GUI 100 % gelesen (Lesefehler „OUESTS“); Symbol liegt über dem Namen
        words = [("TELEPORT", [0.122, 0.508, 0.171, 0.52]), ("Equip", [0.535, 0.882, 0.556, 0.894]),
                 ("Best", [0.558, 0.882, 0.582, 0.894]), ("G.", [0.066, 0.983, 0.075, 0.995]),
                 ("OUESTS", [0.077, 0.983, 0.1, 0.995]), ("Guild", [0.015, 0.889, 0.038, 0.9])]
        found = hud_locate(words)
        self.assertEqual(sorted(found), ["Equip Best", "G. Quests", "Guild", "Teleporter"])
        tele = found["Teleporter"]
        self.assertLess(tele[3], 0.509)                       # Symbol oberhalb der Beschriftung
        self.assertLess(found["Equip Best"][0], 0.536)


if __name__ == "__main__":
    unittest.main()
