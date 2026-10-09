"""Private-Server-Link lesen (ohne Roblox zu starten)."""
import unittest

import _env  # noqa: F401
from astral_monitor.roblox_join import DEEP_LINK, deep_link, explain, parse_private_link, parse_share_link



def setUpModule():                                     # these tests check the German texts
    from astral_monitor import i18n
    i18n.set_language("de")


def tearDownModule():
    from astral_monitor import i18n
    i18n.set_language("en")

class JoinTests(unittest.TestCase):
    def test_classic_links(self):
        link = "https://www.roblox.com/games/102072869879193/CYBER-Anime-Astral?privateServerLinkCode=12345678901234567"
        self.assertEqual(parse_private_link(link), (102072869879193, "12345678901234567"))
        self.assertEqual(parse_private_link("roblox.com/games/123456/x?foo=1&privateServerLinkCode=abcDEF_12-34"),
                         (123456, "abcDEF_12-34"))
        self.assertEqual(parse_private_link("https://www.roblox.com/de/games/123456?privateServerLinkCode=987654321"),
                         (123456, "987654321"))
        self.assertIn("linkCode=987654321", DEEP_LINK.format(place=123456, code="987654321"))

    def test_share_links(self):
        code = "0123456789abcdef0123456789abcdef"
        for link in (f"https://www.roblox.com/share?code={code}&type=Server",
                     f"https://www.roblox.com/share-links?code={code}&type=Server&pid=Server&is_retargeting=false"
                     f"&deep_link_value=roblox%3A%2F%2Fnavigation%2Fshare_links%3Fcode%3D{code}%26type%3DServer"):
            self.assertEqual(parse_share_link(link), code, link)
            self.assertEqual(deep_link(link), f"roblox://navigation/share_links?code={code}&type=Server")
        self.assertEqual(parse_share_link(f"﻿  https://www.roblox.com/share?code={code}&type=Server \n"), code)
        self.assertIn("Teilen-Link", explain(f"https://www.roblox.com/share?code={code}&type=Server"))
        for bad in (f"https://www.roblox.com/share?code={code}&type=ExperienceDetails",
                    f"https://evil.example/share?code={code}&type=Server",
                    f"https://evilroblox.com/share?code={code}&type=Server",
                    "https://www.roblox.com/share?code=abc;del&type=Server"):
            self.assertIsNone(deep_link(bad), bad)

    def test_rejects_other_and_unsafe_links(self):
        for bad in ("",
                    "https://evil.example/games/123456/x?privateServerLinkCode=12345678",
                    "https://www.roblox.com/games/123456/x",
                    "https://www.roblox.com/games/123456/x?privateServerLinkCode=12;del",
                    "https://www.roblox.com/games/abc/x?privateServerLinkCode=12345678"):
            self.assertIsNone(parse_private_link(bad), bad)

    def test_explain(self):
        self.assertIn("Kein gültiger", explain("https://www.roblox.com/share?code=abc&type=Server"))
        self.assertIn("123456", explain("https://www.roblox.com/games/123456/x?privateServerLinkCode=12345678"))


class FavoriteTests(unittest.TestCase):
    def test_share_code_roundtrip(self):
        from astral_monitor.roblox_join import parse_share_code, share_code
        link = "https://www.roblox.com/share?code=0123456789abcdef0123456789abcdef&type=Server"
        code = share_code("Server von Max ✨", link)
        self.assertTrue(code.startswith("astral-server:"))
        self.assertEqual(parse_share_code(f"  {code}\n"), ("Server von Max ✨", link))
        self.assertIsNone(parse_share_code(link))                                  # normaler Link: kein Code
        self.assertIsNone(parse_share_code("astral-server:kaputt!!"))
        self.assertIsNone(parse_share_code(share_code("X", "https://evil.example/share?code=1&type=Server")))

    def test_migration_and_cleaning(self):
        from astral_monitor.settings import Settings, clean_favorites
        link = "https://www.roblox.com/share?code=0123456789abcdef0123456789abcdef&type=Server"
        s = Settings.from_dict({"private_server_link": link, "settings_version": 6})
        self.assertEqual(s.server_favorites, [{"name": "Server 1", "link": link}])     # Link aus 0.6.3 übernommen
        self.assertEqual(clean_favorites([{"name": " A  b ", "link": " x "}, {"name": "a B", "link": "y"},
                                          {"name": "", "link": "z"}, "kaputt", {"name": "C"}]),
                         [{"name": "A b", "link": "x"}])
        self.assertEqual(len(clean_favorites([{"name": f"S{i}", "link": "l"} for i in range(50)])), 20)

    def test_diagnostics_hide_links(self):
        import inspect
        from astral_monitor import diagnostics
        src = inspect.getsource(diagnostics)
        self.assertIn('"server_favorites"', src)
        self.assertIn('"link": "<entfernt>"', src)


if __name__ == "__main__":
    unittest.main()
