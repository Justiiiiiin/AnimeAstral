"""Discord bot for remote control (Settings → Discord bot, off by default; owner's wish 08.10.2026).

Every user creates their OWN bot in the Discord developer portal and enters its token – a shared bot wouldn't
work (the token would be a secret in the public repo). The bot runs inside the program itself (own thread with
asyncio), only while the program is open, and obeys only the allowed Discord IDs.

Commands are slash commands (/status, /start …); they are registered right away for every server the bot is in
when connecting. The actual work is done by `handler(command, arguments)` (in the main window, GUI thread), which
returns `Reply(text, png)`. Without Qt."""
# No “from __future__ import annotations”: discord.py reads the type hints of the slash commands at runtime.

import asyncio
import io
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from .i18n import tr

log = logging.getLogger("bot")

PERMISSIONS = 2048 + 16384 + 32768      # send messages, embed links, attach files
COMMANDS = ("status", "start", "stop", "pause", "screenshot", "raid", "makro", "antiafk", "autorejoin", "join", "pc",
            "hilfe")
SHUTDOWN_DELAY = 60      # /pc shutdown: this many seconds to cancel (/pc cancel)


def power_command(action: str) -> list[str]:
    """Windows command for /pc (shutdown.exe): shut down/restart with a delay, or cancel."""
    if action == "shutdown":
        return ["shutdown", "/s", "/t", str(SHUTDOWN_DELAY), "/c", "Anime Astral Monitor: Discord-Befehl /pc"]
    if action == "restart":
        return ["shutdown", "/r", "/t", str(SHUTDOWN_DELAY), "/c", "Anime Astral Monitor: Discord-Befehl /pc"]
    if action == "abort":
        return ["shutdown", "/a"]
    raise ValueError(action)


@dataclass
class Reply:
    text: str
    png: Optional[bytes] = None


def invite_url(app_id: str) -> str:
    """Invite link for the own bot (bot + slash commands, only the needed permissions)."""
    return (f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands"
            f"&permissions={PERMISSIONS}")


def allowed_ids(users: str, ping_id: str) -> set[int]:
    """Allowed Discord IDs: list from the settings, otherwise the ping ID from “Alerts”."""
    ids = set()
    for part in (users or "").replace(";", ",").replace(" ", ",").split(","):
        if part.strip().isdigit():
            ids.add(int(part.strip()))
    if not ids and (ping_id or "").strip().isdigit():
        ids.add(int(ping_id.strip()))
    return ids


class ControlBot:
    """Starts/stops the bot in its own thread. state: “off”, “connecting …”, “connected as …”, error text."""

    def __init__(self, token: str, allowed: set[int], handler: Callable[[str, dict], Reply],
                 choices: Callable[[str], list[str]], on_state: Callable[[str, str], None]) -> None:
        self.token = token.strip()
        self.allowed = allowed
        self.handler = handler                     # (befehl, argumente) -> Reply   (darf blockieren, max. ~20 s)
        self.choices = choices                     # (kind) -> choices for autocomplete (“raid”, “server”)
        self.on_state = on_state                   # (zustand, app_id)
        self.app_id = ""
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._client = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running or not self.token:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="DiscordBot")
        self._thread.start()

    def stop(self) -> None:
        loop, client = self._loop, self._client
        if loop is not None and client is not None and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(client.close(), loop).result(timeout=5)
            except Exception:  # noqa: BLE001 – doesn't matter when quitting
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self.on_state(tr("off"), self.app_id)

    # ------------------------------------------------------------------ Thread
    def _run(self) -> None:
        try:
            import discord  # noqa: F401 – load the heavy dependency only here
        except ImportError:
            self.on_state(tr("Error: discord.py missing"), "")
            return
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.on_state(tr("connecting …"), "")
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            if "Improper token" in text or "401" in text:
                text = tr("Invalid token")
            log.warning("Discord-Bot: %s", text)
            self.on_state(tr("Error: {error}", error=text), self.app_id)
        finally:
            try:
                self._loop.close()
            except Exception:  # noqa: BLE001
                pass

    async def _main(self) -> None:
        import discord
        from discord import app_commands

        client = discord.Client(intents=discord.Intents.none() | discord.Intents(guilds=True))
        tree = app_commands.CommandTree(client)
        self._client = client
        self._register(tree, app_commands, discord)

        async def sync_all() -> None:
            for guild in client.guilds:
                try:
                    tree.copy_global_to(guild=guild)
                    await tree.sync(guild=guild)          # per server: visible right away (global takes up to 1 h)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Commands for %s not registered: %s", guild, exc)

        @client.event
        async def on_ready() -> None:
            self.app_id = str(client.application_id or "")
            await sync_all()
            names = ", ".join(g.name for g in client.guilds) or tr("in no server – use the invite link")
            self.on_state(tr("connected as {name} ({servers})", name=str(client.user), servers=names), self.app_id)
            log.info("Discord-Bot verbunden als %s", client.user)

        @client.event
        async def on_guild_join(guild) -> None:
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)

        await client.start(self.token)

    def _register(self, tree, app_commands, discord) -> None:
        bot = self

        async def run(interaction, name: str, args: dict) -> None:
            if interaction.user.id not in bot.allowed:
                await interaction.response.send_message(tr("No access – your Discord ID is not allowed in the "
                                                           "program."), ephemeral=True)
                log.info("Discord bot: command /%s from a non-allowed ID %s rejected", name, interaction.user.id)
                return
            await interaction.response.defer(thinking=True)
            log.info("Discord-Bot: /%s %s", name, args or "")
            loop = asyncio.get_running_loop()
            try:
                reply = await loop.run_in_executor(None, bot.handler, name, args)
            except Exception as exc:  # noqa: BLE001
                reply = Reply(tr("Error: {error}", error=exc))
            files = [discord.File(io.BytesIO(reply.png), filename="roblox.png")] if reply.png else []
            await interaction.followup.send(reply.text[:1900] or "✔", files=files)

        async def complete(kind: str, current: str):
            names = [n for n in bot.choices(kind) if current.lower() in n.lower()][:25]
            return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names]

        @tree.command(name="status", description=tr("State: monitoring, wave, raid, macro"))
        async def status(interaction):
            await run(interaction, "status", {})

        @tree.command(name="start", description=tr("Start monitoring"))
        async def start(interaction):
            await run(interaction, "start", {})

        @tree.command(name="stop", description=tr("Stop the monitoring"))
        async def stop(interaction):
            await run(interaction, "stop", {})

        @tree.command(name="pause", description=tr("Pause / resume monitoring"))
        async def pause(interaction):
            await run(interaction, "pause", {})

        @tree.command(name="screenshot", description=tr("Image of the Roblox window"))
        async def screenshot(interaction):
            await run(interaction, "screenshot", {})

        @tree.command(name="raid", description=tr("Choose the raid attempts count for"))
        @app_commands.describe(name=tr("Raid name"))
        async def raid(interaction, name: str):
            await run(interaction, "raid", {"name": name})

        @raid.autocomplete("name")
        async def raid_names(interaction, current: str):
            return await complete("raid", current)

        @tree.command(name="makro", description=tr("Macro: start the farm routine, stop, progressions …"))
        @app_commands.describe(aktion=tr("What should the macro do?"))
        @app_commands.choices(aktion=[app_commands.Choice(name=tr("Start farm routine"), value="queue"),
                                      app_commands.Choice(name=tr("Stop"), value="stop"),
                                      app_commands.Choice(name=tr("Progressions: Auto All"), value="progression"),
                                      app_commands.Choice(name=tr("Close menu"), value="close")])
        async def makro(interaction, aktion: app_commands.Choice[str]):
            await run(interaction, "makro", {"action": aktion.value})

        @tree.command(name="antiafk", description=tr("Anti-AFK on/off"))
        async def antiafk(interaction, an: bool):
            await run(interaction, "antiafk", {"on": an})

        @tree.command(name="autorejoin", description=tr("Auto-rejoin on/off"))
        async def autorejoin(interaction, an: bool):
            await run(interaction, "autorejoin", {"on": an})

        @tree.command(name="join", description=tr("Join private server (favourite)"))
        @app_commands.describe(server=tr("Favourite (empty = marked one)"))
        async def join(interaction, server: Optional[str] = None):
            await run(interaction, "join", {"server": server or ""})

        @join.autocomplete("server")
        async def server_names(interaction, current: str):
            return await complete("server", current)

        @tree.command(name="pc", description=tr("Shut down / restart the PC (60 s delay) or cancel"))
        @app_commands.describe(aktion=tr("What should the PC do?"))
        @app_commands.choices(aktion=[app_commands.Choice(name=tr("Shut down"), value="shutdown"),
                                      app_commands.Choice(name=tr("Restart"), value="restart"),
                                      app_commands.Choice(name=tr("Cancel"), value="abort")])
        async def pc(interaction, aktion: app_commands.Choice[str]):
            await run(interaction, "pc", {"action": aktion.value})

        @tree.command(name="hilfe", description=tr("All commands"))
        async def hilfe(interaction):
            await run(interaction, "hilfe", {})
