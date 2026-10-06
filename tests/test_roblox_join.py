"""Private-Server-Link lesen (ohne Roblox zu starten)."""
import unittest

import _env  # noqa: F401
from astral_monitor.roblox_join import DEEP_LINK, deep_link, explain, parse_private_link, parse_share_link


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


if __name__ == "__main__":
    unittest.main()
