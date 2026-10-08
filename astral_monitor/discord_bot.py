"""Discord-Bot zur Fernsteuerung (Einstellungen → Discord-Bot, Standard aus; Wunsch des Eigentümers 08.10.2026).

Jeder Nutzer legt seinen EIGENEN Bot im Discord-Entwicklerportal an und trägt dessen Token ein – ein gemeinsamer Bot
ginge nicht (das Token wäre ein Geheimnis im öffentlichen Repo). Der Bot läuft im Programm selbst (eigener Thread mit
asyncio), nur solange das Programm offen ist, und gehorcht nur den erlaubten Discord-IDs.

Befehle sind Slash-Befehle (/status, /start …); sie werden beim Verbinden für jeden Server, in dem der Bot ist, sofort
registriert. Die eigentliche Arbeit macht `handler(befehl, argumente)` (im Hauptfenster, GUI-Thread) und liefert
`Reply(text, png)` zurück. Ohne Qt."""
# Kein „from __future__ import annotations“: discord.py liest die Typangaben der Slash-Befehle zur Laufzeit.

import asyncio
import io
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from .i18n import tr

log = logging.getLogger("bot")

PERMISSIONS = 2048 + 16384 + 32768      # Nachrichten senden, Links einbetten, Dateien anhängen
COMMANDS = ("status", "start", "stop", "pause", "screenshot", "raid", "makro", "antiafk", "autorejoin", "join", "pc",
            "hilfe")
SHUTDOWN_DELAY = 60      # /pc herunterfahren: so viele Sekunden Zeit zum Abbrechen (/pc abbrechen)


def power_command(action: str) -> list[str]:
    """Windows-Befehl für /pc (shutdown.exe): herunterfahren/neu starten mit Verzögerung, oder abbrechen."""
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
    """Einladungslink für den eigenen Bot (Bot + Slash-Befehle, nur die nötigen Rechte)."""
    return (f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands"
            f"&permissions={PERMISSIONS}")


def allowed_ids(users: str, ping_id: str) -> set[int]:
    """Erlaubte Discord-IDs: Liste aus den Einstellungen, sonst die Ping-ID aus „Meldungen“."""
    ids = set()
    for part in (users or "").replace(";", ",").replace(" ", ",").split(","):
        if part.strip().isdigit():
            ids.add(int(part.strip()))
    if not ids and (ping_id or "").strip().isdigit():
        ids.add(int(ping_id.strip()))
    return ids


class ControlBot:
    """Startet/stoppt den Bot in einem eigenen Thread. state: „aus“, „verbinde …“, „verbunden als …“, Fehlertext."""

    def __init__(self, token: str, allowed: set[int], handler: Callable[[str, dict], Reply],
                 choices: Callable[[str], list[str]], on_state: Callable[[str, str], None]) -> None:
        self.token = token.strip()
        self.allowed = allowed
        self.handler = handler                     # (befehl, argumente) -> Reply   (darf blockieren, max. ~20 s)
        self.choices = choices                     # (art) -> Auswahl für Autovervollständigung („raid“, „server“)
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
            except Exception:  # noqa: BLE001 – beim Beenden egal
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self.on_state(tr("aus"), self.app_id)

    # ------------------------------------------------------------------ Thread
    def _run(self) -> None:
        try:
            import discord  # noqa: F401 – schwere Abhängigkeit erst hier laden
        except ImportError:
            self.on_state(tr("Fehler: discord.py fehlt"), "")
            return
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.on_state(tr("verbinde …"), "")
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            if "Improper token" in text or "401" in text:
                text = tr("Token ungültig")
            log.warning("Discord-Bot: %s", text)
            self.on_state(tr("Fehler: {error}", error=text), self.app_id)
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
                    await tree.sync(guild=guild)          # je Server: sofort sichtbar (global dauert bis 1 Std.)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Befehle für %s nicht registriert: %s", guild, exc)

        @client.event
        async def on_ready() -> None:
            self.app_id = str(client.application_id or "")
            await sync_all()
            names = ", ".join(g.name for g in client.guilds) or tr("in keinem Server – Einladungslink nutzen")
            self.on_state(tr("verbunden als {name} ({servers})", name=str(client.user), servers=names), self.app_id)
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
                await interaction.response.send_message(tr("Kein Zugriff – deine Discord-ID ist im Programm nicht "
                                                           "freigegeben."), ephemeral=True)
                log.info("Discord-Bot: Befehl /%s von nicht erlaubter ID %s abgelehnt", name, interaction.user.id)
                return
            await interaction.response.defer(thinking=True)
            log.info("Discord-Bot: /%s %s", name, args or "")
            loop = asyncio.get_running_loop()
            try:
                reply = await loop.run_in_executor(None, bot.handler, name, args)
            except Exception as exc:  # noqa: BLE001
                reply = Reply(tr("Fehler: {error}", error=exc))
            files = [discord.File(io.BytesIO(reply.png), filename="roblox.png")] if reply.png else []
            await interaction.followup.send(reply.text[:1900] or "✔", files=files)

        async def complete(kind: str, current: str):
            names = [n for n in bot.choices(kind) if current.lower() in n.lower()][:25]
            return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names]

        @tree.command(name="status", description=tr("Zustand: Überwachung, Welle, Raid, Makro"))
        async def status(interaction):
            await run(interaction, "status", {})

        @tree.command(name="start", description=tr("Überwachung starten"))
        async def start(interaction):
            await run(interaction, "start", {})

        @tree.command(name="stop", description=tr("Überwachung stoppen"))
        async def stop(interaction):
            await run(interaction, "stop", {})

        @tree.command(name="pause", description=tr("Überwachung pausieren / fortsetzen"))
        async def pause(interaction):
            await run(interaction, "pause", {})

        @tree.command(name="screenshot", description=tr("Bild vom Roblox-Fenster"))
        async def screenshot(interaction):
            await run(interaction, "screenshot", {})

        @tree.command(name="raid", description=tr("Raid wählen, zu dem gezählt wird"))
        @app_commands.describe(name=tr("Name des Raids"))
        async def raid(interaction, name: str):
            await run(interaction, "raid", {"name": name})

        @raid.autocomplete("name")
        async def raid_names(interaction, current: str):
            return await complete("raid", current)

        @tree.command(name="makro", description=tr("Makro: Farm-Routine starten, stoppen, Progressions …"))
        @app_commands.describe(aktion=tr("Was soll das Makro tun?"))
        @app_commands.choices(aktion=[app_commands.Choice(name=tr("Farm-Routine starten"), value="queue"),
                                      app_commands.Choice(name=tr("Stopp"), value="stop"),
                                      app_commands.Choice(name=tr("Progressions: Roll All"), value="progression"),
                                      app_commands.Choice(name=tr("Menü schließen"), value="close")])
        async def makro(interaction, aktion: app_commands.Choice[str]):
            await run(interaction, "makro", {"action": aktion.value})

        @tree.command(name="antiafk", description=tr("Anti-AFK an/aus"))
        async def antiafk(interaction, an: bool):
            await run(interaction, "antiafk", {"on": an})

        @tree.command(name="autorejoin", description=tr("Auto-Rejoin an/aus"))
        async def autorejoin(interaction, an: bool):
            await run(interaction, "autorejoin", {"on": an})

        @tree.command(name="join", description=tr("Privatem Server beitreten (Favorit)"))
        @app_commands.describe(server=tr("Favorit (leer = markierter)"))
        async def join(interaction, server: Optional[str] = None):
            await run(interaction, "join", {"server": server or ""})

        @join.autocomplete("server")
        async def server_names(interaction, current: str):
            return await complete("server", current)

        @tree.command(name="pc", description=tr("PC herunterfahren / neu starten (60 s Verzögerung) oder abbrechen"))
        @app_commands.describe(aktion=tr("Was soll der PC tun?"))
        @app_commands.choices(aktion=[app_commands.Choice(name=tr("Herunterfahren"), value="shutdown"),
                                      app_commands.Choice(name=tr("Neu starten"), value="restart"),
                                      app_commands.Choice(name=tr("Abbrechen"), value="abort")])
        async def pc(interaction, aktion: app_commands.Choice[str]):
            await run(interaction, "pc", {"action": aktion.value})

        @tree.command(name="hilfe", description=tr("Alle Befehle"))
        async def hilfe(interaction):
            await run(interaction, "hilfe", {})
