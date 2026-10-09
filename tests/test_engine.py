"""Monitoring loop (engine.py) without Roblox, OCR or threads: a fake image source and a fake wave reader play
through raids; the engine is driven tick by tick with an artificial clock."""
import unittest
from unittest import mock

import _env  # noqa: F401
import numpy as np

from astral_monitor import engine as engine_mod
from astral_monitor.capture import GrabResult
from astral_monitor.settings import Settings
from astral_monitor.wave import WaveReading


class FakeSource:
    name = "Fake"

    def __init__(self):
        self.frames = True                    # False = no image (window minimized / gone)
        self.stopped = False

    def grab(self, rois, full=False, timeout=1.0):
        if not self.frames:
            return None
        crops = [np.zeros((20, 60, 3), np.uint8) for _ in rois]
        return GrabResult(crops, np.zeros((90, 160, 3), np.uint8) if full else None, (160, 90))

    def is_alive(self):
        return True

    def stop(self):
        self.stopped = True


class FakeReader:
    """Returns the scripted counter values one per tick (None = no counter on screen)."""

    def __init__(self):
        self.values = []

    def read(self, crop):
        value = self.values.pop(0) if self.values else None
        return None if value is None else WaveReading(value, 100)

    def set_allowed(self, allowed):
        pass


class _NoThread:
    """Stands in for the loop thread: “running” until joined, but the test drives the ticks itself."""

    def __init__(self, *args, **kwargs):
        self.alive = False

    def start(self):
        self.alive = True

    def join(self, timeout=None):
        self.alive = False

    def is_alive(self):
        return self.alive


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.source = FakeSource()
        s = Settings()
        s.read_quests = False                 # quests have their own tests
        s.guard_enabled = False
        s.webhook_url = ""                    # nothing is sent
        self.engine = engine_mod.Engine(s, source_factory=lambda *a, **k: self.source)
        self.engine.get_ocr = lambda: object()
        with mock.patch.object(engine_mod.threading, "Thread", _NoThread):
            self.engine.start()               # everything but the loop thread
        self.reader = FakeReader()
        self.engine.wave_reader = self.reader
        self.now = 1000.0

    def tearDown(self):
        self.engine._halt.set()
        for worker in (self.engine.sender, self.engine.publisher, self.engine.presence, self.engine.anti_afk,
                       self.engine.rejoin):
            stop = getattr(worker, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:  # noqa: BLE001 – test cleanup
                    pass

    def play(self, values, step=4.0):
        """One tick per value, `step` seconds apart (≈ one wave every 4 s like in the game)."""
        self.reader.values = list(values)
        for _ in values:
            self.now += step
            self.engine._tick(self.now)

    def test_full_raid_counts_once(self):
        before = self.engine.stats.snapshot().total_attempts
        self.play(range(1, 101))              # Wave 1/100 … 100/100
        self.play([None, None])               # result screen
        self.play(range(1, 4))                # the next attempt starts
        snap = self.engine.stats.snapshot()
        self.assertEqual(snap.total_attempts - before, 1)
        self.assertEqual(self.engine.stats.records[-1].max_wave, 100)
        self.assertEqual(self.engine.state.wave_value, 3)

    def test_restart_counts_the_reached_wave(self):
        before = self.engine.stats.snapshot().total_attempts
        self.play(range(1, 38))               # reached wave 37, then a new attempt begins
        self.play([1, 2, 3, 4])
        self.assertEqual(self.engine.stats.snapshot().total_attempts - before, 1)
        self.assertEqual(self.engine.stats.records[-1].max_wave, 37)

    def test_misread_jump_is_ignored(self):
        before = self.engine.stats.snapshot().total_attempts
        self.play([10, 11, 12, 99, 13, 14])   # “99” in between: impossible jump, not a raid end
        self.assertEqual(self.engine.stats.snapshot().total_attempts - before, 0)
        self.assertEqual(self.engine.state.wave_value, 14)

    def test_no_image_is_reported(self):
        self.source.frames = False
        self.play([None])
        self.assertIsNone(self.engine.state.wave_value)
        self.assertIn("No image", self.engine.state.info)
        self.source.frames = True
        self.play([5])
        self.assertEqual(self.engine.state.wave_value, 5)

    def test_stop_releases_the_source(self):
        self.engine.stop()
        self.assertTrue(self.source.stopped)
        self.assertFalse(self.engine.running)


if __name__ == "__main__":
    unittest.main()
