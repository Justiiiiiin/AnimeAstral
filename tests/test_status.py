import json
import time
import unittest
from pathlib import Path

import _env  # noqa: F401
from astral_monitor import status as st_mod
from astral_monitor.settings import Settings

SNAP = {"status": "running", "wave": 14, "total_waves": 100, "profile": "Militech Convoy", "session_ok": 0,
        "session_failed": 7, "total_ok": 12, "session_attempts": 7, "session_waves": 180, "total_attempts": 40,
        "waves_per_hour": 700.0, "avg_wave": 25.7, "avg_duration": 101.0, "per_hour": 0.0, "uptime": 3700,
        "best_wave": 29, "ram_mb": 2400, "quests": [], "last_event": "x"}


class Resp:
    def __init__(self, code, data=None):
        self.status_code, self._d = code, data or {}

    def json(self):
        return self._d


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.discord = [], {"exists": True, "next": 100, "id": None}
        self.orig_request, self.orig_gap = st_mod.requests.request, st_mod.MIN_GAP
        st_mod.MIN_GAP = 0.1
        st_mod.requests.request = self.fake
        self.s = Settings()
        self.s.webhook_url = "https://discord.com/api/webhooks/42/TOKEN"
        self.s.status_interval = 3600
        Path(_env.DATA, "status_message.json").unlink(missing_ok=True)
        self.pub = st_mod.StatusPublisher(lambda: self.s, lambda: SNAP)
        self.pub.start()

    def tearDown(self):
        self.pub.stop_now()
        self.pub.join(timeout=3)
        st_mod.requests.request, st_mod.MIN_GAP = self.orig_request, self.orig_gap

    def fake(self, method, url, **kw):
        self.calls.append(method)
        if method == "POST":
            self.discord["id"] = str(self.discord["next"])
            self.discord["next"] += 1
            self.discord["exists"] = True
            return Resp(200, {"id": self.discord["id"]})
        if method == "PATCH":
            return Resp(200) if self.discord["exists"] and url.endswith("/" + (self.discord["id"] or "")) else Resp(404)
        was, self.discord["exists"] = self.discord["exists"], False
        return Resp(204 if was else 404)

    def step(self, action, wait=1.0):
        n = len(self.calls)
        action()
        time.sleep(wait)
        return self.calls[n:]

    def test_create_edit_resend_recreate(self):
        self.assertEqual(self.step(self.pub.request_update), ["POST"])
        self.assertEqual(self.step(self.pub.request_update), ["PATCH"])
        self.assertEqual(self.step(self.pub.request_resend, 1.4), ["DELETE", "POST"])
        self.discord["exists"] = False                                  # Nutzer löscht die Nachricht
        self.assertEqual(self.step(self.pub.request_update), ["PATCH", "POST"])
        saved = json.loads(Path(_env.DATA, "status_message.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["id"], self.discord["id"])

    def test_embed_content(self):
        from astral_monitor import messages
        embed = messages.build_status(self.s, SNAP)["embeds"][0]
        self.assertIn("Läuft", embed["title"])
        self.assertIn("Militech Convoy", embed["title"])                  # Raid im Titel
        self.assertIn("Welle 14/100", embed["description"])
        self.assertIn("▰", embed["description"])                           # Fortschrittsbalken
        self.assertIn("14 %", embed["description"])
        names = [f["name"] for f in embed["fields"]]
        self.assertTrue(any("Versuche" in n for n in names))
        self.assertTrue(any("Wellen/Std" in n for n in names))
        self.assertEqual(len([f for f in embed["fields"] if f["inline"]]) % 3, 0)   # volle Dreierreihen
        self.assertLessEqual(len(embed["fields"]), 25)
        stopped = messages.build_status(self.s, dict(SNAP, status="stopped", wave=None))["embeds"][0]
        self.assertIn("gestoppt", stopped["description"])
        self.assertEqual(messages.progress_bar(5, 10, width=4), "▰▰▱▱")


if __name__ == "__main__":
    unittest.main()
