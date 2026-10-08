"""Einstellungssuche: Umlaute, Bindestriche, Tippfehler."""
import unittest

import _env  # noqa: F401

from astral_monitor.search import Haystack, matches


class SearchTest(unittest.TestCase):
    def test_tolerant(self):
        guard = Haystack("Wächter · Stillstand nach · Roblox-Speicher über")
        afk = Haystack("Anti-AFK · Ausführen alle")
        keys = Haystack("Hotkeys · Start / Stopp · Pause / Fortsetzen")
        rpc = Haystack("Discord-Profilstatus · Anwendungs-ID")
        self.assertTrue(matches("wachter", guard))
        self.assertTrue(matches("Waechter", guard))
        self.assertTrue(matches("antiafk", afk))
        self.assertTrue(matches("anti afk", afk))
        self.assertTrue(matches("hotkey", keys))
        self.assertTrue(matches("discrod", rpc))           # Tippfehler
        self.assertTrue(matches("speicher roblox", guard))  # alle Wörter, Reihenfolge egal
        self.assertFalse(matches("hotkey", guard))
        self.assertFalse(matches("speicher discord", guard))
        self.assertFalse(matches("", guard))


if __name__ == "__main__":
    unittest.main()
