import unittest

import _env  # noqa: F401
from astral_monitor import presence
from astral_monitor.settings import Settings

SNAP = {"status": "running", "wave": 14, "total_waves": 100, "profile": "Militech Convoy", "session_ok": 1,
        "session_failed": 7, "best_wave": 29, "started_unix": 1_700_000_000}


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


class PresenceTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(presence.slug("Militech Convoy"), "militech_convoy")
        self.assertEqual(presence.slug("Größe Ä!"), "grosse_a")
        self.assertEqual(presence.slug("???"), "logo")

    def test_activity(self):
        s = Settings()
        act = presence.build_activity(s, SNAP)
        self.assertEqual(act["details"], "Welle 14/100 · Militech Convoy")
        self.assertEqual(act["large_image"], "militech_convoy")
        self.assertEqual(act["start"], 1_700_000_000)
        self.assertIn("Bestwelle 29", act["state"])
        self.assertIsNone(presence.build_activity(s, {**SNAP, "status": "stopped"}))
        idle = presence.build_activity(s, {**SNAP, "wave": None, "profile": ""})
        self.assertEqual(idle["large_image"], "logo")

    def test_updater_connects_updates_on_change_and_clears(self):
        FakeRpc.created.clear()
        s = Settings()
        s.rpc_enabled, s.rpc_client_id = True, "123456789"
        snap = dict(SNAP)
        up = presence.PresenceUpdater(lambda: s, lambda: snap, factory=FakeRpc)
        up.tick(0.0)
        up.tick(20.0)                                         # unverändert -> kein zweites Update
        snap["wave"] = 15
        up.tick(40.0)
        rpc = FakeRpc.created[0]
        self.assertEqual(len(rpc.updates), 2)
        self.assertEqual(rpc.updates[-1]["details"], "Welle 15/100 · Militech Convoy")
        snap["status"] = "stopped"
        up.tick(60.0)
        self.assertTrue(rpc.cleared and rpc.closed)

    def test_disabled_or_missing_id_does_nothing_and_connect_failure_is_quiet(self):
        FakeRpc.created.clear()
        s = Settings()
        up = presence.PresenceUpdater(lambda: s, lambda: SNAP, factory=FakeRpc)
        up.tick(0.0)
        s.rpc_enabled = True
        up.tick(1.0)                                          # keine ID
        self.assertEqual(FakeRpc.created, [])

        def failing(cid):
            raise ConnectionError("Discord läuft nicht")
        s.rpc_client_id = "42"
        up2 = presence.PresenceUpdater(lambda: s, lambda: SNAP, factory=failing)
        up2.tick(0.0)
        up2.tick(5.0)                                         # innerhalb der Wartezeit: kein neuer Versuch
        self.assertIsNone(up2._rpc)


if __name__ == "__main__":
    unittest.main()
