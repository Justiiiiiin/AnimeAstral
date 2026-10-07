"""Quest-Titel und -Fortschritt säubern, Reihenfolge wie im Spiel (ohne Tesseract)."""
import unittest

import _env  # noqa: F401
from astral_monitor.quests import QuestLine, clean_title, parse_progress
from astral_monitor.tracker import QuestTracker

NAMES = ("Militech Convoy", "MaxTac Call", "Alvarez War")


class QuestTextTests(unittest.TestCase):
    def test_titles(self):
        cases = {"Complete Alvarez War 80 time": "Complete Alvarez War 80",
                 "Complete Militech Conv oy 90 time": "Complete Militech Convoy 90",   # zerteilter Name
                 "Complete MaxTac Call 90 time(s": "Complete MaxTac Call 90",
                 "Clear 8000 waves in MaxTac Ca": "Clear 8000 waves in MaxTac Ca",     # Wörter nach der Zahl bleiben
                 "Complete Alvarez War 80 tirr": "Complete Alvarez War 80"}            # Wortstück am Rand
        for raw, expected in cases.items():
            self.assertEqual(clean_title(raw, NAMES), expected)

    def test_progress(self):
        for text, expected in (("l/90", (1, 90)), ("I/90", (1, 90)), ("255/8000", (255, 8000)), ("0f 90", (0, 90))):
            self.assertEqual(parse_progress(text), expected)

    def test_number_format(self):
        from astral_monitor import i18n, messages
        i18n.set_language("de")
        self.assertEqual([messages.fmt_k(v) for v in (950, 2255, 18109, 843231, 1250000)],
                         ["950", "2,3k", "18,1k", "843k", "1,25M"])
        line = messages.quest_text([{"title": "Clear", "cur": 843231, "total": 900000, "percent": 93}])
        self.assertIn("843.231/900k", line)                          # Zählstand genau, Ziel kurz

    def test_game_order(self):
        tracker = QuestTracker()
        a, b = QuestLine("Complete Alvarez War 80", 24, 80), QuestLine("Clear 8000 waves", 255, 8000)
        tracker.update([b])
        tracker.update([a, b])                                   # A erscheint später, steht im Spiel aber oben
        self.assertEqual([q["title"] for q in tracker.snapshot()], [a.title, b.title])


if __name__ == "__main__":
    unittest.main()
