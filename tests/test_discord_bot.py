"""Discord-Bot: Berechtigungen, Einladungslink, /pc-Befehle, Aufbau der Slash-Befehle (ohne Netz)."""
import asyncio
import unittest

import _env  # noqa: F401

from astral_monitor.discord_bot import COMMANDS, ControlBot, Reply, allowed_ids, invite_url, power_command



def setUpModule():                                     # these tests check the German texts
    from astral_monitor import i18n
    i18n.set_language("de")


def tearDownModule():
    from astral_monitor import i18n
    i18n.set_language("en")

class BotTest(unittest.TestCase):
    def test_allowed_ids(self):
        self.assertEqual(allowed_ids("123, 456;789", "999"), {123, 456, 789})
        self.assertEqual(allowed_ids("", "999"), {999})            # Standard: Ping-ID aus „Meldungen“
        self.assertEqual(allowed_ids("abc", ""), set())             # niemand -> alle Befehle abgelehnt

    def test_invite_and_power(self):
        self.assertIn("client_id=42", invite_url("42"))
        self.assertIn("applications.commands", invite_url("42"))
        self.assertEqual(power_command("shutdown")[:4], ["shutdown", "/s", "/t", "60"])
        self.assertEqual(power_command("restart")[:2], ["shutdown", "/r"])
        self.assertEqual(power_command("abort"), ["shutdown", "/a"])
        with self.assertRaises(ValueError):
            power_command("format c:")

    def test_slash_commands_are_valid(self):
        try:
            import discord
            from discord import app_commands
        except ImportError:
            self.skipTest("discord.py fehlt")

        async def build():
            client = discord.Client(intents=discord.Intents.none())
            tree = app_commands.CommandTree(client)
            bot = ControlBot("x", {1}, lambda n, a: Reply("ok"), lambda k: [], lambda s, a: None)
            bot._register(tree, app_commands, discord)
            cmds = {c.name: c for c in tree.get_commands()}
            for c in cmds.values():                               # Discord-Grenzen: Beschreibung 1–100 Zeichen
                self.assertTrue(1 <= len(c.description) <= 100, c.name)
                c.to_dict(tree)                                   # wirft bei ungültigen Optionen/Auswahlen
            await client.close()
            return set(cmds)

        names = asyncio.run(build())
        self.assertEqual(names, set(COMMANDS))


    def test_bridge_commands_without_gui(self):
        """Befehle, die ohne Oberfläche beantwortet werden: Status, /pc gesperrt, unbekannter Raid, Hilfe."""
        from types import SimpleNamespace

        from astral_monitor.settings import Settings
        from astral_monitor.ui.bot_bridge import BotBridge
        snap = {"status": "running", "wave": 37, "total_waves": 100, "profile": "Alvarez War",
                "session_attempts": 3, "total_attempts": 551}
        engine = SimpleNamespace(settings=Settings(), status_snapshot=lambda: snap,
                                 profile_store=SimpleNamespace(names=lambda: ["Alvarez War"]))
        bridge = BotBridge(SimpleNamespace(engine=engine))
        text = bridge.handle("status", {}).text
        self.assertIn("37/100", text)
        self.assertIn("Alvarez War", text)
        self.assertIn("aus", bridge.handle("pc", {"action": "shutdown"}).text)   # Standard: /pc gesperrt
        self.assertIn("gibt es nicht", bridge.handle("raid", {"name": "Holy Grail War"}).text)
        self.assertIn("/status", bridge.handle("hilfe", {}).text)


if __name__ == "__main__":
    unittest.main()
