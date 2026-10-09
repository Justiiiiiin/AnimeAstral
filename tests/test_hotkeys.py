"""Hotkey names in English (same keys) and the removed design “Classic”."""
import json
import unittest

import _env  # noqa: F401
from astral_monitor import app_paths
from astral_monitor.hotkeys import english_hotkey, parse_hotkey
from astral_monitor.settings import Settings


class HotkeyNameTests(unittest.TestCase):
    def test_english_names_same_keys(self):
        for german, english in (("Strg+F1", "Ctrl+F1"), ("strg + umschalt + s", "Ctrl+Shift+S"),
                                ("Strg+Entf", "Ctrl+Delete"), ("alt+f12", "Alt+F12"), ("Ctrl+Alt+B", "Ctrl+Alt+B")):
            self.assertEqual(english_hotkey(german), english)
            self.assertEqual(parse_hotkey(german), parse_hotkey(english))       # still the same key

    def test_settings_load_english_and_no_classic(self):
        path = app_paths.data_dir() / "settings.json"
        backup = path.read_text(encoding="utf-8") if path.exists() else None
        try:
            path.write_text(json.dumps({"settings_version": 12, "ui_design": "classic", "hotkey_toggle": "Strg+F1",
                                        "hotkey_pause": "Strg+F2"}), encoding="utf-8")
            s = Settings.load()
            self.assertEqual(s.ui_design, "nightcity")
            self.assertEqual((s.hotkey_toggle, s.hotkey_pause), ("Ctrl+F1", "Ctrl+F2"))
        finally:
            if backup is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(backup, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
