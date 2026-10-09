"""Secrets: locally via DPAPI, export/import with a password."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401
from astral_monitor import secure
from astral_monitor.settings import Settings

HOOK = "https://discord.com/api/webhooks/123/abcdefgh"
LINK = "https://www.roblox.com/share?code=0123456789abcdef0123456789abcdef&type=Server"


class SecureTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "DPAPI only on Windows")
    def test_settings_json_has_no_plain_secrets(self):
        s = Settings(webhook_url=HOOK, private_server_link=LINK, ping_user_id="42",
                     server_favorites=[{"name": "Mein Server", "link": LINK}])
        raw = s.to_dict(protect=True)
        text = json.dumps(raw)
        self.assertNotIn("webhooks/123", text)
        self.assertNotIn("0123456789abcdef", text)
        self.assertTrue(raw["webhook_url"].startswith(secure.PREFIX))
        back = Settings.from_dict(raw)
        self.assertEqual((back.webhook_url, back.private_server_link, back.ping_user_id), (HOOK, LINK, "42"))
        self.assertEqual(back.server_favorites, [{"name": "Mein Server", "link": LINK}])

    def test_plain_old_files_still_load_and_foreign_values_are_dropped(self):
        self.assertEqual(Settings.from_dict({"webhook_url": HOOK}).webhook_url, HOOK)          # plain text (old)
        self.assertEqual(Settings.from_dict({"webhook_url": secure.PREFIX + "AAAA"}).webhook_url, "")   # other PC

    def test_export_import_roundtrip(self):
        s = Settings(webhook_url=HOOK, server_favorites=[{"name": "A", "link": LINK}], ui_zoom=75)
        with tempfile.TemporaryDirectory() as d:
            path = secure.export_settings(s.to_dict(), "geheim123", Path(d) / "x.txt")
            self.assertEqual(path.suffix, secure.EXPORT_SUFFIX)
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("webhooks", content)
            self.assertNotIn("0123456789abcdef", content)
            data = secure.import_settings(path, "geheim123")
            back = Settings.from_dict(data)
            self.assertEqual((back.webhook_url, back.ui_zoom, back.server_favorites[0]["link"]), (HOOK, 75, LINK))
            with self.assertRaises(secure.SecureError):
                secure.import_settings(path, "falsch12345")
            payload = json.loads(content)
            payload["n"] = 2 ** 16                                       # tampered header is detected
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(secure.SecureError):
                secure.import_settings(path, "geheim123")

    def test_password_rules(self):
        self.assertIsNotNone(secure.check_password("kurz"))
        self.assertIsNotNone(secure.check_password("langgenug", "anders123"))
        self.assertIsNone(secure.check_password("langgenug", "langgenug"))
        with self.assertRaises(secure.SecureError):
            secure.export_settings({}, "kurz", Path("egal.astralsettings"))


if __name__ == "__main__":
    unittest.main()
