import unittest

import _env  # noqa: F401
from astral_monitor import presence
from astral_monitor.settings import Settings

SNAP = {"status": "running", "wave": 14, "total_waves": 100, "profile": "Militech Convoy", "session_attempts": 8,
        "session_waves": 186, "best_wave": 29, "started_unix": 1_700_000_000}
ICON = "https://tr.rbxcdn.com/abc/512/512/Image/Png"



def setUpModule():                                     # these tests check the German texts
    from astral_monitor import i18n
    i18n.set_language("de")


def tearDownModule():
    from astral_monitor import i18n
    i18n.set_language("en")

class FakeRpc:
    created = []

    def __init__(self, cid):
        self.cid, self.updates, self.cleared, self.closed = cid, [], False, False
        FakeRpc.created.append(self)

    def connect(self):
        pass

    def update(self, **kw):
        self.updates.append(kw)

    def clear(self):
        self.cleared = True

    def close(self):
        self.closed = True


class Resp:
    def __init__(self, code=200, data=None):
        self.status_code, self._d = code, data or {}

    def json(self):
        return self._d


class GameIconTests(unittest.TestCase):
    def test_parse_game_id(self):
        self.assertEqual(presence.parse_game_id("https://www.roblox.com/games/9797806474/Anime-Astral-Simulator"), 9797806474)
        self.assertEqual(presence.parse_game_id("  10502841145 "), 10502841145)
        self.assertIsNone(presence.parse_game_id("kein link"))

    def test_fetch_icon_via_universe(self):
        calls = []

        def getter(url, **kw):
            calls.append(url)
            if "universes/v1/places" in url:
                return Resp(200, {"universeId": 555})
            return Resp(200, {"data": [{"targetId": 555, "state": "Completed", "imageUrl": ICON}]})
        self.assertEqual(presence.fetch_icon_url(123456, getter), ICON)
        self.assertIn("universeIds=555", calls[1])

    def test_fetch_icon_falls_back_to_universe_id(self):
        def getter(url, **kw):
            if "universes/v1/places" in url:
                return Resp(404)
            return Resp(200, {"data": [{"state": "Completed", "imageUrl": ICON}]})
        self.assertEqual(presence.fetch_icon_url(777, getter), ICON)

    def test_fetch_icon_failures_return_none(self):
        self.assertIsNone(presence.fetch_icon_url(1, lambda *a, **k: Resp(500)))
        self.assertIsNone(presence.fetch_icon_url(1, lambda url, **k: Resp(200, {"data": [{"state": "Pending", "imageUrl": ""}]})))

        def boom(*a, **k):
            raise presence.requests.ConnectionError("offline")
        self.assertIsNone(presence.fetch_icon_url(1, boom))


class PresenceTests(unittest.TestCase):
    def test_activity_uses_game_thumbnail(self):
        act = presence.build_activity(Settings(), SNAP, ICON)
        self.assertEqual(act["details"], "Welle 14/100 · Militech Convoy")
        self.assertEqual(act["large_image"], ICON)
        self.assertEqual(act["state"], "Versuche 8 · Wellen 186 · Bestwelle 29")
        self.assertEqual(act["start"], 1_700_000_000)
        self.assertNotIn("small_image", act)
        self.assertNotIn("large_image", presence.build_activity(Settings(), SNAP, None))
        self.assertIsNone(presence.build_activity(Settings(), {**SNAP, "status": "stopped"}, ICON))

    def test_updater_flow_and_status_texts(self):
        FakeRpc.created.clear()
        s = Settings()
        s.rpc_enabled, s.rpc_client_id = True, "123456789"
        snap = dict(SNAP)
        up = presence.PresenceUpdater(lambda: s, lambda: snap, factory=FakeRpc, icon_fetcher=lambda gid: ICON)
        up.tick(1000.0)
        self.assertTrue(up.status_ok)
        up.tick(1005.0)                                       # unverändert
        snap["wave"] = 15
        up.tick(1008.0)                                       # geändert, aber < 15 s seit letztem Update -> wartet
        up.tick(1020.0)
        rpc = FakeRpc.created[0]
        self.assertEqual([u["details"] for u in rpc.updates],
                         ["Welle 14/100 · Militech Convoy", "Welle 15/100 · Militech Convoy"])
        self.assertEqual(rpc.updates[0]["large_image"], ICON)
        snap["status"] = "stopped"
        up.tick(1040.0)
        self.assertTrue(rpc.cleared and rpc.closed)
        self.assertIn("Bereit", up.status_text)

    def test_status_when_disabled_without_id_and_discord_missing(self):
        s = Settings()
        up = presence.PresenceUpdater(lambda: s, lambda: SNAP, factory=FakeRpc, icon_fetcher=lambda g: ICON)
        up.tick(0.0)
        self.assertEqual(up.status_text, "Aus")
        s.rpc_enabled = True
        up.tick(1.0)
        self.assertIn("Anwendungs-ID", up.status_text)

        class DiscordNotFound(Exception):
            pass

        def failing(cid):
            raise DiscordNotFound()
        s.rpc_client_id = "42"
        up2 = presence.PresenceUpdater(lambda: s, lambda: SNAP, factory=failing, icon_fetcher=lambda g: ICON)
        up2.tick(0.0)
        self.assertIn("Discord-Desktop-App", up2.status_text)
        self.assertFalse(up2.status_ok)
        up2.tick(5.0)                                         # Wartezeit: kein neuer Versuch
        self.assertIsNone(up2._rpc)


if __name__ == "__main__":
    unittest.main()
