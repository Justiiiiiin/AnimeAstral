"""Roblox profile via the public API (without network, with canned responses)."""
import time
import unittest

import _env  # noqa: F401
from astral_monitor import roblox_profile as rp

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50


class Resp:
    def __init__(self, code, data=None, content=b""):
        self.status_code, self._d, self.content = code, data, content

    def json(self):
        return self._d


class ProfileTests(unittest.TestCase):
    def test_lookup_and_avatar(self):
        poster = lambda url, json=None, timeout=0: Resp(200, {"data": [{"id": 42, "name": "Max_1", "displayName": "Max"}]})  # noqa: E731,E501
        prof = rp.lookup("max_1", poster=poster)
        self.assertEqual((prof.user_id, prof.name, prof.display_name), (42, "Max_1", "Max"))

        def getter(url, timeout=0):
            if "thumbnails" in url:
                return Resp(200, {"data": [{"imageUrl": "https://tr.rbxcdn.com/abc/150/150/AvatarHeadshot/Png"}]})
            return Resp(200, content=PNG)
        self.assertTrue(rp.download_avatar(42, getter=getter))
        self.assertEqual(rp.avatar_file().read_bytes(), PNG)

        evil = lambda url, timeout=0: Resp(200, {"data": [{"imageUrl": "https://evil.example/x.png"}]})  # noqa: E731
        self.assertFalse(rp.download_avatar(42, getter=evil))                 # only images from the Roblox CDN

    def test_errors_and_refresh_rule(self):
        with self.assertRaises(rp.ProfileError):
            rp.lookup("x!")                                                   # invalid, without network
        with self.assertRaises(rp.ProfileError):
            rp.lookup("Nobody", poster=lambda *a, **k: Resp(200, {"data": []}))
        rp.avatar_file().write_bytes(PNG)
        info = {"name": "Max_1", "at": time.time()}
        self.assertFalse(rp.needs_refresh("max_1", info))
        self.assertTrue(rp.needs_refresh("Other", info))                      # different name
        self.assertTrue(rp.needs_refresh("Max_1", dict(info, at=time.time() - 2 * 86400)))   # older than a day
        self.assertFalse(rp.needs_refresh("", info))


if __name__ == "__main__":
    unittest.main()
