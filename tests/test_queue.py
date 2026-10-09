"""Makro-Warteschlange: wann verlassen, Gigs-Zeiten, Pet-Raster aus Namensschildern – ohne Roblox/OCR."""
import unittest

import _env  # noqa: F401
import numpy as np

from astral_monitor.automation import fmt_wait, gig_cards, gig_next_due, gig_timer_box, hud_locate, \
    leave_before, next_task, parse_timer, pet_tiles, user_moved


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

    def test_gig_cards(self):
        # Wörter wie aus dem echten Fixer-Gigs-Fenster (Big Job working, Quick ready, Big Job working)
        words = [("NEW", [0.338, 0.277, 0.379, 0.298]), ("1:38:43", [0.452, 0.277, 0.51, 0.298]),
                 ("BIS", [0.331, 0.373, 0.354, 0.393]), ("JOB", [0.36, 0.373, 0.389, 0.393]),
                 ("3H", [0.409, 0.373, 0.428, 0.393]), ("QUICK", [0.54, 0.373, 0.586, 0.393]),
                 ("20", [0.608, 0.373, 0.624, 0.393]), ("BIS", [0.768, 0.373, 0.792, 0.393]),
                 ("WORKING", [0.352, 0.427, 0.408, 0.44]), ("READY", [0.579, 0.427, 0.618, 0.44]),
                 ("WORKING", [0.791, 0.427, 0.845, 0.44]), ("4:36:98", [0.346, 0.702, 0.389, 0.719]),
                 ("left", [0.393, 0.702, 0.414, 0.719]), ("left", [0.831, 0.702, 0.852, 0.719]),
                 ("FINISH", [0.335, 0.841, 0.395, 0.862]), ("CLAIM", [0.568, 0.841, 0.629, 0.862])]
        cards = gig_cards(words)
        self.assertEqual([c["duration"] for c in cards], [10800, 1200, 10800])
        self.assertEqual([c["state"] for c in cards], ["working", "ready", "working"])
        self.assertIsNotNone(cards[1]["claim"])
        self.assertIsNone(cards[0]["claim"])                 # „FINISH NOW“ kostet Währung – nie ein Knopf
        box = gig_timer_box(cards[0])
        self.assertLess(box[0], 0.346)                        # Zeit links von „left“ liegt im Bereich
        self.assertLess(box[2], 0.393)
        self.assertEqual(gig_next_due(cards, {0: 5798, 2: 5822}), 0)          # eine Karte ist fertig
        self.assertEqual(gig_next_due(cards[:1] + cards[2:], {0: 5798, 1: 5822}), 5798)
        self.assertEqual(gig_next_due(cards[:1], {0: 99999}), 1200)       # unplausibel: verworfen, bald nachsehen
        self.assertEqual(gig_next_due(cards[:1], {}), 1200)   # Zeit unlesbar: in 20 Min. nachsehen

    def test_user_moved(self):
        rect = (0, 0, 1920, 1080)
        self.assertFalse(user_moved((500, 300), (510, 305), rect))       # kleine Abweichung: kein Abbruch
        self.assertIsNone(user_moved((500, 300), (960, 540), rect))      # Spiel setzt Zeiger zur Mitte
        self.assertTrue(user_moved((500, 300), (700, 300), rect))        # echte Bewegung
        self.assertTrue(user_moved((500, 300), (960, 540), None))

    def test_fmt_wait(self):
        self.assertEqual(fmt_wait(30), "30 s")
        self.assertEqual(fmt_wait(18 * 60), "18 min")
        self.assertEqual(fmt_wait(96 * 60), "1 h 36 min")
        self.assertEqual(fmt_wait(24 * 3600), "24 h")

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


    def test_guard_blocks_forbidden_targets(self):
        from astral_monitor.automation import Navigator, Stop
        nav = Navigator(lambda: None, "Roblox", lambda: None, lambda _t: None)
        nav.forbidden = [[0.2, 0.75, 0.36, 0.9]]
        with self.assertRaises(Stop):
            nav._guard((0.3, 0.8))                       # „Leave“ unten links: nie anfahren
        nav._guard((0.5, 0.5))                           # anderswo: erlaubt
        nav.forbidden = []                               # außerhalb von Gilde/Erkunden keine Sperrzonen:
        nav._guard((0.5, 0.11))                          # Raid-„LEAVE!“ oben in der Mitte bleibt drückbar
        from astral_monitor import knowledge
        zones = knowledge.forbidden_zones([("Leave", [0.265, 0.776, 0.331, 0.805])], [0.16, 0.15, 0.83, 0.88], "Guild")
        self.assertFalse(knowledge.inside((0.5, 0.11), zones))   # Gilden-Sperre trifft das Raid-LEAVE! nicht


    def test_scroll_vs_animation(self):
        """Scrollen = Inhalt verschiebt sich; laufende Timer/Animationen zählen nicht (Boosts, Equip Best)."""
        from astral_monitor.explorer import scrolled_box
        rng = np.random.default_rng(1)
        img = (rng.random((180, 320)) * 255).astype(np.uint8)
        img = np.repeat(np.repeat(img[::6, ::6], 6, axis=0), 6, axis=1)[:180, :320]   # grobe Struktur
        moved = img.copy()
        moved[50:165] = img[65:180]
        self.assertIsNotNone(scrolled_box(img, moved))
        timer = img.copy()
        timer[80:92, 100:200] = 255 - timer[80:92, 100:200]
        self.assertIsNone(scrolled_box(img, timer))
        self.assertIsNone(scrolled_box(img, img))
        side = img.copy()                                  # seitliche Liste (Swords, Professions)
        side[:, 40:300] = img[:, 60:320]
        self.assertIsNotNone(scrolled_box(img, side))


if __name__ == "__main__":
    unittest.main()
