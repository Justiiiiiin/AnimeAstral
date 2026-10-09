import json
import unittest
from pathlib import Path

import _env
from astral_monitor import discord_client
from astral_monitor.settings import Settings


class Resp:
    def __init__(self, code, data=None):
        self.status_code, self._d, self.text = code, data, json.dumps(data or {})

    def json(self):
        if self._d is None:
            raise ValueError
        return self._d


class ForumTests(unittest.TestCase):
    """Raid messages with a forum webhook: the first message of the day opens a post, the others go into it."""

    def setUp(self):
        Path(_env.DATA, "forum_thread.json").unlink(missing_ok=True)
        self.s = Settings()
        self.s.webhook_url = "https://discord.com/api/webhooks/1/MAIN"
        self.s.forum_webhook_url = "https://discord.com/api/webhooks/2/FORUM"
        self.sender = discord_client.DiscordSender(lambda: self.s)
        self.calls, self.threads = [], {"next": 500, "alive": set()}
        self.orig = discord_client.requests.post
        discord_client.requests.post = self.fake

    def tearDown(self):
        discord_client.requests.post = self.orig

    def fake(self, url, json=None, **kw):
        self.calls.append((url, json))
        if "thread_id=" in url:
            tid = url.split("thread_id=")[1]
            return Resp(204) if tid in self.threads["alive"] else Resp(404, {"message": "Unknown Channel"})
        if "FORUM" in url:
            if "thread_name" not in json:
                return Resp(400, {"message": "thread_name required"})
            tid = str(self.threads["next"])
            self.threads["next"] += 1
            self.threads["alive"].add(tid)
            return Resp(200, {"id": "9", "channel_id": tid})
        return Resp(204)

    def test_daily_thread(self):
        self.assertTrue(self.sender.send_daily({"embeds": []})[0])
        url, payload = self.calls[-1]
        self.assertIn("wait=true", url)
        self.assertTrue(payload["thread_name"].startswith("Raids · "))
        self.assertTrue(self.sender.send_daily({"embeds": []})[0])
        self.assertTrue(self.calls[-1][0].endswith("?thread_id=500"))          # second message: same post
        self.assertNotIn("FORUM", Path(_env.DATA, "forum_thread.json").read_text(encoding="utf-8"))  # no URL

        self.threads["alive"].clear()                                          # post deleted
        self.assertTrue(self.sender.send_daily({"embeds": []})[0])
        self.assertIn("wait=true", self.calls[-1][0])
        self.assertTrue(self.sender.send_daily({"embeds": []})[0])
        self.assertTrue(self.calls[-1][0].endswith("?thread_id=501"))

    def test_other_webhook_new_thread(self):
        self.sender.send_daily({"embeds": []})
        self.s.forum_webhook_url = "https://discord.com/api/webhooks/3/FORUM2"
        self.sender.send_daily({"embeds": []})
        self.assertIn("wait=true", self.calls[-1][0])                          # new webhook: new post

    def test_main_channel_unchanged(self):
        self.assertTrue(self.sender.send_now({"embeds": []})[0])
        self.assertEqual(self.calls[-1][0], self.s.webhook_url)


if __name__ == "__main__":
    unittest.main()
