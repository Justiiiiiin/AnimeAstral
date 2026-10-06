"""Anti-AFK: Zeitplan, Warten auf Ruhe des Nutzers, Fehlerfall – mit künstlicher Uhr, ohne echte Eingaben."""
import unittest

import _env  # noqa: F401
from astral_monitor.antiafk import MAX_WAIT, RETRY_SECONDS, AntiAfk
from astral_monitor.settings import Settings


class Harness:
    def __init__(self, idle=100.0, ok=True):
        self.s = Settings()
        self.idle, self.ok = idle, ok
        self.jumps, self.events = [], []
        self.afk = AntiAfk(lambda: self.s, lambda text, level: self.events.append((text, level)),
                           jump=self._jump, idle_seconds=lambda: self.idle, clock=lambda: 0.0)

    def _jump(self, title):
        self.jumps.append(title)
        return (True, "ok") if self.ok else (False, "Roblox-Fenster nicht gefunden")


class AntiAfkTests(unittest.TestCase):
    def test_off_by_default_and_interval(self):
        h = Harness()
        h.afk.tick(0)
        self.assertEqual(h.jumps, [])                       # Standard: aus
        h.s.anti_afk_enabled, h.s.anti_afk_minutes = True, 10
        h.afk.tick(0)                                       # eingeschaltet: erster Sprung nach 10 Minuten
        h.afk.tick(599)
        self.assertEqual(h.jumps, [])
        h.afk.tick(600)
        self.assertEqual(h.jumps, ["Roblox"])
        h.afk.tick(1199)
        h.afk.tick(1200)
        self.assertEqual(len(h.jumps), 2)
        self.assertEqual(h.events[-1][1], "info")
        h.s.anti_afk_enabled = False
        h.afk.tick(1800)
        self.assertEqual(len(h.jumps), 2)
        self.assertIsNone(h.afk.next_at)

    def test_waits_while_user_is_typing(self):
        h = Harness(idle=0.5)
        h.s.anti_afk_enabled = True
        h.afk.tick(0)
        h.afk.tick(600)
        h.afk.tick(610)
        self.assertEqual(h.jumps, [])                       # Nutzer tippt: warten
        h.idle = 5
        h.afk.tick(611)
        self.assertEqual(len(h.jumps), 1)                   # Ruhe: jetzt springen

    def test_gives_up_waiting_and_retries_later(self):
        h = Harness(idle=0.1)
        h.s.anti_afk_enabled = True
        h.afk.tick(0)
        h.afk.tick(600)
        h.afk.tick(600 + MAX_WAIT)
        self.assertEqual(h.jumps, [])
        self.assertEqual(h.afk.next_at, 600 + MAX_WAIT + RETRY_SECONDS)

    def test_failure_is_reported_and_retried(self):
        h = Harness(ok=False)
        h.s.anti_afk_enabled = True
        h.afk.tick(0)
        h.afk.tick(600)
        self.assertEqual(h.events[-1][1], "warn")
        self.assertEqual(h.afk.next_at, 600 + RETRY_SECONDS)

    def test_shorter_interval_applies_immediately(self):
        h = Harness()
        h.s.anti_afk_enabled = True
        h.afk.tick(0)
        h.s.anti_afk_minutes = 2
        h.afk.tick(10)
        self.assertEqual(h.afk.next_at, 130)

    def test_settings_validation(self):
        s = Settings()
        s.anti_afk_minutes = 20
        self.assertIn("20", s.validate_detection())


if __name__ == "__main__":
    unittest.main()
