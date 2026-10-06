import json
import unittest
from pathlib import Path

import _env
from astral_monitor import app_paths, messages
from astral_monitor.hotkeys import parse_hotkey
from astral_monitor.report_card import render_card
from astral_monitor.settings import RPC_GAME_LINK, Settings
from astral_monitor.stats import RunRecord, StatsStore


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
        d["settings_version"] = 1                       # sehr alte Einstellungen landen ebenfalls auf dem neuesten Stand
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


class WaveColorTests(unittest.TestCase):
    def test_tiers(self):
        from astral_monitor.ui.page_monitor import wave_token
        self.assertEqual(wave_token(50, 0), "")                         # noch keine Bestwelle
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
        self.assertIn("Welle 42/100", out)                               # Nützliches bleibt
        self.assertIn("place 102072869879193", out)                      # Spiel-ID (15 Stellen) ist öffentlich


if __name__ == "__main__":
    unittest.main()
