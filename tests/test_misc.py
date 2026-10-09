import json
import unittest
from pathlib import Path

import _env
from astral_monitor import app_paths, messages
from astral_monitor.hotkeys import parse_hotkey
from astral_monitor.report_card import render_card
from astral_monitor.settings import RPC_GAME_LINK, Settings
from astral_monitor.stats import RunRecord, StatsStore



def setUpModule():                                     # these tests check the German texts
    from astral_monitor import i18n
    i18n.set_language("de")


def tearDownModule():
    from astral_monitor import i18n
    i18n.set_language("en")

class SettingsTests(unittest.TestCase):
    def test_roundtrip_and_defaults(self):
        s = Settings()
        s.webhook_url = "https://discord.com/api/webhooks/1/x"
        s.save()
        self.assertEqual(Settings.load().to_dict(), s.to_dict())
        self.assertIsNone(s.validate())

    def test_migration_from_v4(self):
        d = Settings().to_dict()
        d["settings_version"], d["wizard_done"] = 4, False
        app_paths.settings_file().write_text(json.dumps(d), encoding="utf-8")
        loaded = Settings.load()
        self.assertTrue(loaded.wizard_done)
        self.assertEqual(loaded.settings_version, Settings.settings_version)

    def test_migration_fixes_old_game_link_only(self):
        d = Settings().to_dict()
        d["settings_version"] = 5
        d["rpc_game_link"] = "https://www.roblox.com/games/9797806474/Anime-Astral-Simulator"
        self.assertEqual(Settings.from_dict(d).rpc_game_link, RPC_GAME_LINK)
        d["rpc_game_link"] = "https://www.roblox.com/games/123456789/Eigenes"
        self.assertEqual(Settings.from_dict(d).rpc_game_link, d["rpc_game_link"])
        d["settings_version"] = 1                       # very old settings end up up to date as well
        self.assertEqual(Settings.from_dict(d).settings_version, Settings.settings_version)

    def test_validation(self):
        s = Settings()
        s.hotkey_pause = s.hotkey_toggle
        self.assertIn("unterschiedlich", s.validate_detection())
        s = Settings()
        s.rpc_client_id = "abc"
        self.assertIn("Ziffern", s.validate_detection())
        s = Settings()
        s.status_interval = 5
        self.assertIsNotNone(s.validate_detection())

    def test_hotkeys(self):
        self.assertEqual(parse_hotkey("Ctrl+Alt+S"), (3, 83))
        for bad in ("S", "Ctrl+Foo", "Alt+F25"):
            with self.assertRaises(ValueError):
                parse_hotkey(bad)


class MessageTests(unittest.TestCase):
    def test_png_attachment_content_type(self):
        payload, files = messages.build_message(Settings(), "report", "Titel", messages.COLOR_OK,
                                                image=("bericht.png", b"PNG", "image/png"))
        self.assertEqual(files[0][2], "image/png")
        self.assertEqual(payload["embeds"][0]["image"]["url"], "attachment://bericht.png")

    def test_formatting(self):
        self.assertEqual(messages.fmt_duration(101), "1:41")
        self.assertEqual(messages.fmt_duration_est(101, True), "~1:41")
        self.assertEqual(messages.fmt_int(1284), "1.284")


class CardTests(unittest.TestCase):
    def test_card_renders_with_and_without_data(self):
        st = StatsStore(Path(_env.DATA) / "card.csv")
        empty = render_card(st, None, None, "Bericht")
        self.assertTrue(empty.startswith(b"\x89PNG"))
        for i in range(12):
            st.add(RunRecord(1_700_000_000 + i * 120, 100.0, None, 20 + i % 5, 100, "abgebrochen", raid="Militech Convoy"))
        st.add(RunRecord(1_700_003_000, 230.0, 300.0, 99, 100, "ok", raid="Militech Convoy"))
        full = render_card(st, None, None, "Nacht-Bericht")
        self.assertTrue(full.startswith(b"\x89PNG"))
        self.assertGreater(len(full), len(empty) // 2)


class AppearanceSettingsTests(unittest.TestCase):
    def test_background_and_accent_are_sanitized(self):
        s = Settings.from_dict({"ui_background": "..\\..\\evil.png", "ui_background_dim": 400, "ui_accent": "rot"})
        self.assertEqual((s.ui_background, s.ui_background_dim, s.ui_accent), ("", 95, ""))
        s = Settings.from_dict({"ui_background": "background.jpg", "ui_background_dim": 40, "ui_accent": "#FF6FB5"})
        self.assertEqual((s.ui_background, s.ui_background_dim, s.ui_accent), ("background.jpg", 40, "#FF6FB5"))


class SeasonTests(unittest.TestCase):
    def test_season_dates(self):
        from datetime import date
        from astral_monitor.ui import theme
        cases = {date(2026, 10, 14): "", date(2026, 10, 15): "halloween", date(2026, 11, 2): "halloween",
                 date(2026, 11, 3): "", date(2026, 12, 24): "winter", date(2027, 1, 6): "winter",
                 date(2027, 1, 7): "", date(2026, 12, 31): "newyear", date(2027, 1, 2): "newyear",
                 date(2027, 4, 1): "spring", date(2027, 7, 15): "summer", date(2027, 9, 10): ""}
        for day, expected in cases.items():
            self.assertEqual(theme.season_design(day), expected, day)
        self.assertEqual(theme.effective_design("astral", True, date(2026, 12, 24)), "winter")
        self.assertEqual(theme.effective_design("astral", False, date(2026, 12, 24)), "astral")
        self.assertEqual(theme.effective_design("astral", True, date(2026, 6, 1)), "astral")


class SafeStartTests(unittest.TestCase):
    def test_safe_mode_never_overwrites(self):
        own = Settings()
        own.username = "Mein Name"
        own.save()
        safe = Settings.safe_defaults()
        self.assertTrue(safe.wizard_done)
        safe.username = "Anders"
        safe.save()                                                     # darf nichts schreiben
        self.assertEqual(Settings.load().username, "Mein Name")
        self.assertNotIn("safe_mode", safe.to_dict())


class StorageTests(unittest.TestCase):
    def test_usage_and_clean(self):
        import tempfile
        from astral_monitor import storage
        base = Path(tempfile.mkdtemp(dir=_env.DATA))
        (base / "debug").mkdir()
        (base / "debug" / "a.png").write_bytes(b"x" * 500)
        (base / "updates" / "apply").mkdir(parents=True)
        (base / "updates" / "AnimeAstralMonitor-Setup-1.exe").write_bytes(b"x" * 1000)
        (base / "updates" / "apply" / "apply.log").write_text("ok")
        (base / "monitor.log.1").write_bytes(b"x" * 200)
        sizes = {u.label: u.size for u in storage.usage(base)}
        self.assertEqual(sizes["Debug images"], 500)
        self.assertEqual(sizes["Older logs"], 200)
        self.assertEqual(storage.clean(base), 1700)
        self.assertTrue((base / "updates" / "apply" / "apply.log").exists())     # Update-Protokoll bleibt
        self.assertEqual(storage.fmt_size(1536), "2 KB")


class WaveColorTests(unittest.TestCase):
    def test_tiers(self):
        from astral_monitor.ui.page_monitor import wave_token
        self.assertEqual(wave_token(50, 0), "")                         # no best wave yet
        self.assertEqual([wave_token(w, 80) for w in (10, 48, 72, 80, 95)], ["", "info", "accent", "warn", "warn"])


class DiagnosticsTests(unittest.TestCase):
    def test_scrub_removes_personal_data(self):
        import os
        from astral_monitor.diagnostics import scrub
        user = os.environ.get("USERNAME", "")
        text = ("POST https://discord.com/api/webhooks/123/abcDEF-x fehlgeschlagen\n"
                "Join https://www.roblox.com/share?code=abc123&type=Server\n"
                "roblox://placeId=1&linkCode=9f8e7d\n"
                "Ping 123456789012345678 · Welle 42/100 · place 102072869879193\n"
                f"C:\\Users\\{user}\\AppData\\Local\\Roblox\\logs")
        out = scrub(text)
        for secret in ("abcDEF", "abc123", "9f8e7d", "123456789012345678"):
            self.assertNotIn(secret, out)
        if len(user) >= 3:
            self.assertNotIn(user, out)
        self.assertIn("Welle 42/100", out)                               # useful stuff stays
        self.assertIn("place 102072869879193", out)                      # game ID (15 digits) is public


if __name__ == "__main__":
    unittest.main()


class SeasonDecorTests(unittest.TestCase):
    def test_particles_wrap_around(self):
        from astral_monitor.ui import seasonal
        leaves = seasonal.make_particles("halloween", 10)
        flakes = seasonal.make_particles("winter", 10)
        self.assertEqual((len(leaves), len(flakes)), (10, 10))
        for _ in range(400):                                   # 80 s Bewegung
            seasonal.step(leaves, 0, 0.2)
        self.assertTrue(all(-0.06 <= f.y <= 1.05 for f in leaves))   # fall out at the bottom, back in at the top


class SpookyTests(unittest.TestCase):
    def test_rare_enough(self):
        import random
        from astral_monitor.ui import spooky
        rnd = random.Random(1)
        self.assertTrue(all(spooky.FIRST_MIN <= spooky.next_delay(True, rnd) for _ in range(50)))
        self.assertTrue(all(spooky.next_delay(False, rnd) >= 3600 for _ in range(50)))   # at most 1× per hour


class AccentFromImageTests(unittest.TestCase):
    def test_dominant_vivid_color(self):
        import os
        import tempfile
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
        app = QGuiApplication.instance() or QGuiApplication([])          # noqa: F841
        from astral_monitor.ui.backdrop import accent_from_image
        img = QImage(100, 100, QImage.Format.Format_RGB32)
        img.fill(QColor("#202020"))                                      # grey doesn't count
        p = QPainter(img)
        p.fillRect(0, 0, 100, 60, QColor("#C0306A"))                     # viel Pink
        p.fillRect(0, 60, 100, 15, QColor("#2A70D0"))                    # some blue
        p.end()
        path = os.path.join(tempfile.mkdtemp(dir=_env.DATA), "bg.png")
        img.save(path)
        h = QColor(accent_from_image(path)).hsvHue()
        self.assertTrue(320 <= h <= 345, h)                              # Pink gewinnt
        img.fill(QColor("#808080"))
        img.save(path)
        self.assertIsNone(accent_from_image(path))                       # grey: no color


class NewDotsTests(unittest.TestCase):
    def test_pending(self):
        from astral_monitor.ui import newdots
        old = newdots.__version__
        newdots.__version__ = "9.9.9"
        newdots.NEW_FEATURES["9.9.9"] = ("nav:1", "tab:Roblox")
        try:
            self.assertEqual(newdots.pending([]), {"nav:1", "tab:Roblox"})
            self.assertEqual(newdots.pending(["nav:1"]), {"tab:Roblox"})
        finally:
            newdots.__version__ = old
            del newdots.NEW_FEATURES["9.9.9"]
        self.assertEqual(newdots.pending([]), set(newdots.NEW_FEATURES.get(old, ())))


class FixedDetectionTests(unittest.TestCase):
    def test_old_custom_values_are_replaced(self):
        from astral_monitor.settings import DEFAULT_QUEST_ROI, DEFAULT_WAVE_ROI, PRESETS
        s = Settings.from_dict({"wave_roi": [0.4, 0.0, 0.5, 0.05], "quest_roi": [0.9, 0.1, 1.0, 0.2],
                                "trigger_offset": 3, "confirm_reads": 4, "capture_mode": "screen",
                                "tesseract_path": "C:/x/tesseract.exe", "settings_version": 8})
        self.assertEqual(s.wave_roi.as_list(), DEFAULT_WAVE_ROI.as_list())
        self.assertEqual(s.quest_roi.as_list(), DEFAULT_QUEST_ROI.as_list())
        self.assertEqual((s.trigger_offset, s.confirm_reads, s.capture_mode, s.tesseract_path), (0, 1, "auto", ""))
        self.assertTrue(all("interval" in p and "hot" not in p for p in PRESETS.values()))   # no “hot” tick
        self.assertIsNone(Settings().validate_detection())

    def test_raids_of_any_length(self):
        from astral_monitor.wave import parse_wave
        allowed = Settings().allowed_totals_list()
        for text, expected in (("Wave 12/30", (12, 30)), ("Wave 50/50", (50, 50)), ("Wave 99/100", (99, 100)),
                               ("Wave 1500/2000", (1500, 2000)), ("Wave 44/10", None), ("Wave 7/3", None)):
            self.assertEqual(parse_wave(text, allowed), expected, text)       # 30, 50, 100 … 2000 waves

    def test_endless_modes_without_total(self):
        from astral_monitor import messages
        from astral_monitor.tracker import WaveTracker
        from astral_monitor.wave import parse_bare_wave
        self.assertEqual(parse_bare_wave("Wave 542"), 542)
        self.assertIsNone(parse_bare_wave("Wave 54/1OO"))                 # with “/”: never count as “54”
        self.assertIsNone(parse_bare_wave("542"))                         # without “Wave” in front: no
        tr = WaveTracker(offset=0)
        events = []
        for i, v in enumerate(range(1, 30)):
            events += tr.update(v, 0, 100.0 + i * 4)
        self.assertFalse([e for e in events if e[0] == "candidate"])       # without a target no early end
        events = tr.update(1, 0, 300.0) + tr.update(1, 0, 304.0)          # counter jumps back: raid ends
        ends = [d for k, d in events if k == "run_end"]
        self.assertEqual((ends[0]["max_wave"], ends[0]["total"]), (29, 0))
        self.assertEqual(messages.fmt_wave(542, 0), "542")
        self.assertEqual(messages.fmt_wave(50, 100), "50/100")
