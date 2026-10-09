"""Macro queue: when to leave, gig times, pet grid from name tags – without Roblox/OCR."""
import unittest

import _env  # noqa: F401
import numpy as np

from astral_monitor.automation import fmt_wait, gig_cards, gig_next_due, gig_refresh_box, gig_refresh_read, \
    gig_pill, gig_slot_states, gig_timer_box, gig_timer_vote, guild_next_time, hud_locate, leave_before, next_task, \
    parse_timer, pet_tiles, user_moved


class QueueTest(unittest.TestCase):
    def test_leave_only_before_another_raid(self):
        tasks = [{"kind": "raid", "target": "Alvarez War"}, {"kind": "autoroll", "target": "Pets"},
                 {"kind": "raid", "target": "Holy Grail War"}, {"kind": "raid", "target": "Holy Grail War"}]
        self.assertFalse(leave_before(tasks[0], next_task(tasks, 0, False)))   # gacha next: stay in
        self.assertFalse(leave_before(tasks[2], next_task(tasks, 2, False)))   # same raid follows
        self.assertFalse(leave_before(tasks[3], next_task(tasks, 3, False)))   # end of the queue
        self.assertTrue(leave_before(tasks[3], next_task(tasks, 3, True)))     # loop: Alvarez War follows
        self.assertTrue(leave_before({"kind": "raid", "target": "A"}, {"kind": "raid_join", "target": "B"}))

    def test_parse_timer(self):
        self.assertEqual(parse_timer("1:20:40"), 4840)
        self.assertEqual(parse_timer("33:57"), 2037)
        self.assertIsNone(parse_timer("3/3"))
        self.assertIsNone(parse_timer("12:75"))

    def test_gig_cards(self):
        # positions from the real Fixer Gigs window (fractions of the window roi); owner 09.10.2026: all three gigs
        # were running, but only one was recognized – the macro waited an hour
        words = [("NEW", [0.344, 0.276, 0.386, 0.298]), ("GIGS", [0.391, 0.276, 0.43, 0.298]),
                 ("IN", [0.436, 0.276, 0.453, 0.298]), ("27:10", [0.459, 0.276, 0.504, 0.298]),
                 ("STANDARD", [0.321, 0.373, 0.401, 0.392]), ("1H", [0.423, 0.373, 0.438, 0.392]),
                 ("WORKING", [0.352, 0.426, 0.408, 0.44]), ("4:36:98", [0.33, 0.70, 0.37, 0.72]),
                 ("left", [0.375, 0.70, 0.395, 0.72]), ("FINISH", [0.35, 0.84, 0.41, 0.861]),
                 ("WORKING", [0.571, 0.426, 0.627, 0.44]), ("left", [0.60, 0.70, 0.62, 0.72]),   # header unread
                 ("QUICK", [0.759, 0.373, 0.805, 0.392]), ("SEND", [0.78, 0.84, 0.82, 0.861]),
                 ("PETS", [0.825, 0.84, 0.86, 0.861])]
        cards = gig_cards(words, [0.0, 0.0, 1.0, 1.0])
        self.assertEqual([c["state"] for c in cards], ["working", "working", "open"])
        self.assertEqual([c["duration"] for c in cards], [3600, 10800, 1200])
        self.assertEqual([c["unknown"] for c in cards], [False, True, False])
        self.assertIsNone(cards[0]["claim"])                 # “FINISH NOW” costs currency – never a button
        self.assertIsNotNone(cards[2]["send"])
        box = gig_timer_box(cards[0])
        self.assertLess(box[0], 0.33)                         # time to the left of “left” is inside the area
        self.assertLess(box[2], 0.375)
        # the same window smaller and shifted (other GUI size): the slots move along with the roi
        roi = [0.2, 0.1, 0.7, 0.6]
        moved = [(w, [roi[0] + b[0] * 0.5, roi[1] + b[1] * 0.5, roi[0] + b[2] * 0.5, roi[1] + b[3] * 0.5])
                 for w, b in words]
        self.assertEqual([c["state"] for c in gig_cards(moved, roi)], ["working", "working", "open"])
        # done / empty
        ready = [("READY", [0.361, 0.426, 0.399, 0.44]), ("CLAIM", [0.35, 0.84, 0.41, 0.861])]
        cards = gig_cards(ready, [0.0, 0.0, 1.0, 1.0])
        self.assertEqual([c["state"] for c in cards], ["ready", "empty", "empty"])
        self.assertIsNotNone(cards[0]["claim"])

    def test_gig_next_due(self):
        words = [("STANDARD", [0.321, 0.373, 0.401, 0.392]), ("WORKING", [0.352, 0.426, 0.408, 0.44]),
                 ("WORKING", [0.571, 0.426, 0.627, 0.44]), ("WORKING", [0.79, 0.426, 0.846, 0.44])]
        cards = gig_cards(words, [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(gig_next_due(cards, {0: 3300, 1: 900, 2: 2000}), 900)   # the first one to finish
        self.assertEqual(gig_next_due(cards, {0: 3300, 1: 99999}), 1200)          # implausible/unread: 20 min
        cards[2]["state"] = "ready"
        self.assertEqual(gig_next_due(cards, {0: 3300, 1: 900}), 0)              # done: right away
        cards[2]["state"] = "empty"
        self.assertEqual(gig_next_due(cards, {0: 3300, 1: 900}, 300), 300)       # new gigs come first
        self.assertEqual(gig_next_due(cards, {0: 3300, 1: 900}, None), 300)     # empty, no countdown: 5 min
        self.assertEqual(gig_next_due(cards, {0: 3300, 1: 9000}, 99999), 300)    # implausible “NEW GIGS IN”

    def test_capture_rect(self):
        # owner 09.10.2026: maximized Roblox window – the capture has the title bar (0–1440), the client area starts
        # at 23; clicks used the client area and landed ~22 px too low (below the raid gear)
        from unittest import mock
        from astral_monitor import winapi
        with mock.patch.object(winapi, "client_rect", return_value=(0, 23, 2560, 1440)), \
                mock.patch.object(winapi, "frame_rect", return_value=(0, 0, 2560, 1440)):
            self.assertEqual(winapi.capture_rect(1, (2560, 1440)), (0, 0, 2560, 1440))     # window capture
            self.assertEqual(winapi.capture_rect(1, (2560, 1417)), (0, 23, 2560, 1440))    # screen fallback
            self.assertEqual(winapi.capture_rect(1, None), (0, 23, 2560, 1440))            # no image yet
        with mock.patch.object(winapi, "client_rect", return_value=(0, 0, 1920, 1080)), \
                mock.patch.object(winapi, "frame_rect", return_value=(0, 0, 1920, 1080)):
            self.assertEqual(winapi.capture_rect(1, (1920, 1080)), (0, 0, 1920, 1080))     # full screen (F11)

    def test_gig_timer_vote(self):
        # owner 09.10.2026: “43:41 left” was shown as 4 min, “2:59:47 left” not at all
        self.assertEqual(gig_timer_vote(["«3:11 Left", "_,, 43:41 left .", "43:41 left .", "43:41"], 10800), 2621)
        self.assertEqual(gig_timer_vote(["_ 2:59:47 left", ". 2:59:47 left °", "- 2:59:47 left 6"], 10800), 10787)
        self.assertEqual(gig_timer_vote(["ABMS left", "", "im 43:43 left t"], 10800), 2623)
        self.assertIsNone(gig_timer_vote(["4:36:98 left", "left", ""], 10800))            # no valid time
        self.assertIsNone(gig_timer_vote(["9:59:59 left"], 3600))                         # longer than the gig
        self.assertEqual(gig_timer_vote(["12:00 left", "11:00 left"], 3600), 660)        # tie: the shorter one
        # header without “BIG”: “JOB”/“3H” still name the kind
        words = [("JOB", [0.36, 0.373, 0.389, 0.393]), ("3H", [0.409, 0.373, 0.428, 0.393]),
                 ("WORKING", [0.352, 0.426, 0.408, 0.44])]
        card = gig_cards(words, [0.0, 0.0, 1.0, 1.0])[0]
        self.assertEqual((card["duration"], card["unknown"]), (10800, False))

    def test_gig_pills(self):
        words = [("STANDARD", [0.321, 0.373, 0.401, 0.392]), ("WORKING", [0.352, 0.426, 0.408, 0.44]),
                 ("READY", [0.579, 0.426, 0.618, 0.44]), ("CLAIM", [0.569, 0.84, 0.628, 0.861])]
        cards = gig_cards(words, [0.0, 0.0, 1.0, 1.0])
        slots = gig_slot_states(cards, {0: 2040}, 600, 1000.0)
        self.assertEqual([x["state"] for x in slots], ["working", "ready", "empty"])
        self.assertEqual(slots[0]["until"], 3040.0)
        self.assertEqual(slots[2]["until"], 1600.0)                # new gigs in 10 min
        self.assertEqual(gig_pill(slots[0], 1000.0), ("run", "34 min"))
        self.assertEqual(gig_pill(slots[0], 4000.0)[0], "done")    # time is up: done without a new reading
        self.assertEqual(gig_pill(slots[1], 1000.0)[0], "done")
        self.assertEqual(gig_pill(slots[2], 1000.0), ("empty", "new in 10 min"))
        self.assertEqual(gig_pill(slots[2], 2000.0), ("empty", "empty"))
        self.assertEqual(gig_pill({"state": "open", "until": None}, 0)[0], "pet")
        self.assertEqual(gig_pill(None, 0), ("none", "–"))

    def test_guild_next_time(self):
        import time
        now = time.mktime((2026, 10, 9, 8, 30, 0, 0, 0, -1))         # 09.10.2026 08:30 local PC time
        midnight = time.mktime((2026, 10, 10, 0, 0, 0, 0, 0, -1))
        self.assertEqual(guild_next_time("2026-10-09", 0.0, now), midnight)          # claimed today: tomorrow
        self.assertEqual(guild_next_time("2026-10-08", 0.0, now), 0.0)               # new day: right away
        self.assertEqual(guild_next_time("", 0.0, now), 0.0)                         # never claimed / old file
        self.assertEqual(guild_next_time("2026-10-08", now + 3 * 3600, now), now + 3 * 3600)   # nothing yet: +3 h
        late = time.mktime((2026, 10, 9, 23, 59, 0, 0, 0, -1))
        self.assertEqual(guild_next_time("2026-10-09", 0.0, late), midnight)

    def test_gig_refresh(self):
        words = [("NEW", [0.344, 0.276, 0.386, 0.298]), ("GIGS", [0.391, 0.276, 0.43, 0.298]),
                 ("IN", [0.436, 0.276, 0.453, 0.298]), ("27:10", [0.459, 0.276, 0.504, 0.298]),
                 ("SLOTS", [0.6, 0.277, 0.65, 0.298]), ("3/3", [0.655, 0.277, 0.68, 0.298])]
        box = gig_refresh_box(words)
        self.assertGreater(box[0], 0.453)                     # not into “IN” (its “N” was read as “1”)
        self.assertGreaterEqual(box[2], 0.504)
        self.assertEqual(gig_refresh_read(words), 1630)          # fallback: the general reading
        box = gig_refresh_box(words[:3])                       # time not read: area right of “IN”
        self.assertGreater(box[0], 0.453)
        self.assertIsNone(gig_refresh_box([("NEW", [0.344, 0.276, 0.386, 0.298])]))   # nothing more read: no guess

    def test_user_moved(self):
        rect = (0, 0, 1920, 1080)
        self.assertFalse(user_moved((500, 300), (510, 305), rect))       # small deviation: no abort
        self.assertIsNone(user_moved((500, 300), (960, 540), rect))      # the game puts the cursor in the middle
        self.assertTrue(user_moved((500, 300), (700, 300), rect))        # real movement
        self.assertTrue(user_moved((500, 300), (960, 540), None))

    def test_fmt_wait(self):
        self.assertEqual(fmt_wait(30), "30 s")
        self.assertEqual(fmt_wait(18 * 60), "18 min")
        self.assertEqual(fmt_wait(96 * 60), "1 h 36 min")
        self.assertEqual(fmt_wait(24 * 3600), "24 h")

    def test_pet_grid_from_labels(self):
        # 3 rows × 8 columns of name tags (positions as in the real pets window), 5 pets in the last row
        words = []
        for r, y in enumerate((0.45, 0.63, 0.82)):
            for c in range(8 if r < 2 else 5):
                x = 0.142 + c * 0.102
                words.append(("Maine", [x - 0.02, y - 0.009, x + 0.02, y + 0.009]))
        frame = np.zeros((867, 1525, 3), np.uint8)                       # empty slots: smooth
        tiles = pet_tiles(frame, [0.06, 0.3, 0.94, 0.86], words)
        self.assertEqual(len(tiles), 21)
        last = tiles[-1]
        self.assertAlmostEqual((last[0] + last[2]) / 2, 0.142 + 4 * 0.102, places=3)
        self.assertLess(last[1], 0.82)                                   # the tile sits above its name


    def test_hud_from_labels(self):
        # labels as read at GUI 100 % (misread “OUESTS”); the icon sits above the name
        words = [("TELEPORT", [0.122, 0.508, 0.171, 0.52]), ("Equip", [0.535, 0.882, 0.556, 0.894]),
                 ("Best", [0.558, 0.882, 0.582, 0.894]), ("G.", [0.066, 0.983, 0.075, 0.995]),
                 ("OUESTS", [0.077, 0.983, 0.1, 0.995]), ("Guild", [0.015, 0.889, 0.038, 0.9])]
        found = hud_locate(words)
        self.assertEqual(sorted(found), ["Equip Best", "G. Quests", "Guild", "Teleporter"])
        tele = found["Teleporter"]
        self.assertLess(tele[3], 0.509)                       # icon above the label
        self.assertLess(found["Equip Best"][0], 0.536)


    def test_guard_blocks_forbidden_targets(self):
        from astral_monitor.automation import Navigator, Stop
        nav = Navigator(lambda: None, "Roblox", lambda: None, lambda _t: None)
        nav.forbidden = [[0.2, 0.75, 0.36, 0.9]]
        with self.assertRaises(Stop):
            nav._guard((0.3, 0.8))                       # “Leave” at the bottom left: never go there
        nav._guard((0.5, 0.5))                           # elsewhere: allowed
        nav.forbidden = []                               # outside guild/explore no no-go zones:
        nav._guard((0.5, 0.11))                          # the raid “LEAVE!” at the top middle stays pressable
        from astral_monitor import knowledge
        zones = knowledge.forbidden_zones([("Leave", [0.265, 0.776, 0.331, 0.805])], [0.16, 0.15, 0.83, 0.88], "Guild")
        self.assertFalse(knowledge.inside((0.5, 0.11), zones))   # the guild block doesn't hit the raid LEAVE!


    def test_scroll_vs_animation(self):
        """Scrolling = the content shifts; running timers/animations don't count (Boosts, Equip Best)."""
        from astral_monitor.explorer import scrolled_box
        rng = np.random.default_rng(1)
        img = (rng.random((180, 320)) * 255).astype(np.uint8)
        img = np.repeat(np.repeat(img[::6, ::6], 6, axis=0), 6, axis=1)[:180, :320]   # coarse structure
        moved = img.copy()
        moved[50:165] = img[65:180]
        self.assertIsNotNone(scrolled_box(img, moved))
        timer = img.copy()
        timer[80:92, 100:200] = 255 - timer[80:92, 100:200]
        self.assertIsNone(scrolled_box(img, timer))
        self.assertIsNone(scrolled_box(img, img))
        side = img.copy()                                  # sideways list (Swords, Professions)
        side[:, 40:300] = img[:, 60:320]
        self.assertIsNotNone(scrolled_box(img, side))


if __name__ == "__main__":
    unittest.main()
