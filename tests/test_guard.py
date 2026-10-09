"""Guard (guard.py): Roblox closed, no images, stuck counter, no raid end, memory – with a fake process and an
artificial clock."""
import unittest

import _env  # noqa: F401

from astral_monitor.engine import EngineState
from astral_monitor.guard import NO_FRAMES_AFTER, PROCESS_DOWN_AFTER, Guard
from astral_monitor.settings import Settings


class FakeProc:
    def __init__(self, ram_mb=1000):
        self.ram_mb = ram_mb

    def memory_info(self):
        return type("M", (), {"rss": self.ram_mb * 1048576})()

    def cpu_percent(self, _interval):
        return 10.0


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.s = Settings()
        self.s.guard_enabled = True
        self.s.stall_minutes = 10
        self.s.no_raid_minutes = 0
        self.s.ram_alert_gb = 5.0
        self.proc = FakeProc()
        self.alive = True
        self.notes, self.events = [], []
        self.state = EngineState()
        self.guard = Guard(lambda: self.s, self.state,
                           lambda kind, title, *a, **k: self.notes.append((kind, title)),
                           lambda text, level: self.events.append((level, text)),
                           lambda: None, process_finder=lambda: self.proc if self.alive else None)
        self.guard.reset(0.0)

    def test_roblox_closed_and_back(self):
        self.guard.poll_process(0.0)
        self.assertTrue(self.state.roblox_alive)
        self.alive = False
        self.guard.poll_process(10.0)                         # first noticed
        self.guard.poll_process(10.0 + PROCESS_DOWN_AFTER + 5)
        self.assertIn(("roblox_down", "Roblox was closed"), self.notes)
        self.alive = True
        self.guard.poll_process(100.0)
        self.assertIn(("roblox_down", "Roblox is running again"), self.notes)

    def test_never_seen_roblox_is_no_crash(self):
        self.alive = False
        for t in (0.0, 10.0, 60.0):
            self.guard.poll_process(t)
        self.assertEqual(self.notes, [])                    # program started before Roblox: no alert

    def test_no_images(self):
        self.guard.on_missing(0.0)
        self.guard.on_missing(NO_FRAMES_AFTER - 1)
        self.assertEqual(self.notes, [])
        self.guard.on_missing(NO_FRAMES_AFTER + 1)
        self.assertEqual(len(self.notes), 1)
        self.guard.on_missing(NO_FRAMES_AFTER + 50)         # only once per outage
        self.assertEqual(len(self.notes), 1)
        self.guard.on_frame()
        self.assertEqual(self.events[-1][0], "ok")

    def test_stall_only_in_a_raid_with_a_visible_counter(self):
        self.guard.on_wave(12, 0.0)
        self.guard.check_stall(9 * 60, in_raid=True)
        self.assertEqual(self.notes, [])
        self.guard.check_stall(11 * 60, in_raid=True)
        self.assertEqual(self.notes, [("stall", "Stall detected")])
        self.guard.on_wave(13, 12 * 60)                      # moves again
        self.assertEqual(self.notes[-1], ("stall", "Counter is moving again"))
        self.guard.on_wave(None, 13 * 60)                    # lobby: no counter, no stall
        self.guard.check_stall(60 * 60, in_raid=False)
        self.assertEqual(len(self.notes), 2)

    def test_no_raid_end(self):
        self.s.no_raid_minutes = 30
        self.guard.check_stall(29 * 60, in_raid=False)
        self.assertEqual(self.notes, [])
        self.guard.check_stall(31 * 60, in_raid=False)
        self.assertEqual(self.notes, [("stall", "No raid progress")])
        self.guard.on_raid_end(32 * 60)
        self.assertEqual(self.events[-1], ("ok", "Raids are running again"))

    def test_memory_alert_repeats_rarely(self):
        self.proc.ram_mb = 6 * 1024
        self.guard.poll_process(0.0)
        self.guard.poll_process(10.0)
        self.assertEqual([n for n in self.notes if n[0] == "health"], [("health", "High memory usage")])

    def test_switched_off(self):
        self.s.guard_enabled = False
        self.guard.on_wave(5, 0.0)
        self.guard.check_stall(3600, in_raid=True)
        self.guard.on_missing(0.0)
        self.guard.on_missing(999.0)
        self.assertEqual(self.notes, [])


if __name__ == "__main__":
    unittest.main()
