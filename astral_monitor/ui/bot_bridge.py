"""Link Discord bot ↔ program: starts/stops the user's own bot (discord_bot.py) according to the settings and
runs its commands. The commands come from the bot thread; everything that touches the UI runs via MainWindow.post
in the GUI thread (gui())."""
from __future__ import annotations

import logging
import subprocess
import threading
from typing import Callable, Optional

from .. import messages
from ..discord_bot import COMMANDS, ControlBot, Reply, allowed_ids, power_command
from ..i18n import tr

log = logging.getLogger("bot")


class BotBridge:
    def __init__(self, main) -> None:
        self.main = main
        self.bot: Optional[ControlBot] = None
        self.state = tr("off")
        self.app_id = ""
        self._key: tuple = ()
        self.listeners: list[Callable[[str, str], None]] = []    # the settings tab shows the state

    # ------------------------------------------------------------------ Start/stop according to the settings
    def apply_settings(self) -> None:
        s = self.main.engine.settings
        key = (bool(s.bot_enabled), s.bot_token.strip(), s.bot_users, s.ping_user_id)
        if key == self._key:
            return
        self._key = key
        self.stop()
        if s.bot_enabled and s.bot_token.strip():
            self.bot = ControlBot(s.bot_token, allowed_ids(s.bot_users, s.ping_user_id), self.handle,
                                  self.choices, self._state)
            self.bot.start()

    def stop(self) -> None:
        if self.bot is not None:
            bot, self.bot = self.bot, None
            threading.Thread(target=bot.stop, daemon=True).start()      # don't wait in the GUI thread
        self._state(tr("off"), self.app_id)

    def _state(self, text: str, app_id: str) -> None:
        self.state, self.app_id = text, app_id or self.app_id
        for fn in list(self.listeners):
            self.main.post(lambda fn=fn: fn(self.state, self.app_id))

    # ------------------------------------------------------------------ Helpers
    def gui(self, fn: Callable, timeout: float = 20.0):
        """Run fn in the GUI thread and wait for the result (from the bot thread)."""
        box: dict = {}
        done = threading.Event()

        def call() -> None:
            try:
                box["value"] = fn()
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc
            done.set()

        self.main.post(call)
        if not done.wait(timeout):
            raise TimeoutError(tr("The program did not answer in time."))
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def choices(self, kind: str) -> list[str]:
        s = self.main.engine.settings
        if kind == "raid":
            return self.main.engine.profile_store.names()
        if kind == "server":
            return [f["name"] for f in s.server_favorites]
        return []

    # ------------------------------------------------------------------ Commands
    def handle(self, name: str, args: dict) -> Reply:
        main, engine = self.main, self.main.engine
        if name == "status":
            return Reply(self._status_text())
        if name == "start":
            if engine.running:
                return Reply(tr("Monitoring is already running."))
            self.gui(main.toggle_monitoring)
            return Reply(tr("Monitoring started.") if engine.running else tr("Cannot start – see the program."))
        if name == "stop":
            if not engine.running:
                return Reply(tr("Monitoring is already off."))
            self.gui(main.toggle_monitoring)
            return Reply(tr("Monitoring stopped."))
        if name == "pause":
            if not engine.running:
                return Reply(tr("Monitoring is off."))
            self.gui(main.toggle_pause)
            return Reply(tr("Paused.") if engine.state.paused else tr("Running again."))
        if name == "screenshot":
            return self._screenshot()
        if name == "raid":
            wanted = (args.get("name") or "").strip()
            match = next((n for n in engine.profile_store.names() if n.lower() == wanted.lower()), None)
            if match is None:
                return Reply(tr("There is no raid “{name}”.", name=wanted))
            self.gui(lambda: main.select_raid(match))
            return Reply(tr("Current raid: {name}", name=match))
        if name == "makro":
            return self._macro(args.get("action", ""))
        if name == "antiafk":
            self.gui(lambda: main.set_anti_afk(bool(args.get("on"))))
            return Reply(tr("Anti-AFK on") if args.get("on") else tr("Anti-AFK off"))
        if name == "autorejoin":
            self.gui(lambda: main.set_auto_rejoin(bool(args.get("on"))))
            return Reply(tr("Auto-rejoin on") if args.get("on") else tr("Auto-rejoin off"))
        if name == "join":
            return self._join(args.get("server", ""))
        if name == "pc":
            return self._power(args.get("action", ""))
        if name == "hilfe":
            return Reply(tr("Commands: {commands}", commands=", ".join("/" + c for c in COMMANDS)))
        return Reply(tr("Unknown command."))

    def _status_text(self) -> str:
        engine = self.main.engine
        snap = engine.status_snapshot()
        state = {"running": tr("running"), "paused": tr("paused"), "stopped": tr("off")}[snap["status"]]
        lines = [tr("**Monitoring:** {state}", state=state)]
        if snap["wave"] is not None:
            lines[0] += " · " + tr("Wave {wave}", wave=messages.fmt_wave(snap["wave"], snap["total_waves"]))
        if snap["profile"]:
            lines[0] += " · " + tr("Raid: {name}", name=snap["profile"])
        lines.append(tr("Attempts: {session} (session) · {total} total", session=snap["session_attempts"],
                        total=messages.fmt_k(snap["total_attempts"])))
        try:
            from ..automation import macro_running
            macro = tr("running") if macro_running() else tr("off")
        except Exception:  # noqa: BLE001
            macro = "?"
        s = engine.settings
        lines.append(tr("Macro: {macro} · Anti-AFK: {afk} · Auto-rejoin: {rejoin}", macro=macro,
                        afk=tr("on") if s.anti_afk_enabled else tr("off"),
                        rejoin=tr("on") if s.auto_rejoin_enabled else tr("off")))
        return "\n".join(lines)

    def _screenshot(self) -> Reply:
        import cv2
        engine = self.main.engine
        frame = engine._grab_full() if engine.running else None
        if frame is None:
            res = engine.grab_for_ui(full=True)
            frame = res.full if res is not None else None
        if frame is None:
            return Reply(tr("No image from the Roblox window (is Roblox running?)."))
        h, w = frame.shape[:2]
        if w > 1280:
            frame = cv2.resize(frame, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_AREA)
        ok, png = cv2.imencode(".png", frame)
        return Reply(tr("Roblox window:"), png.tobytes() if ok else None)

    def _macro(self, action: str) -> Reply:
        macro = self.main.macro
        if not macro.enabled:
            return Reply(tr("The macro is not allowed in the program (“Allow macro”)."))
        nav = self.gui(macro.ensure_navigator)
        if action == "stop":
            nav.stop()
            return Reply(tr("Macro stopped."))
        if nav.busy:
            return Reply(tr("The macro is already running – first /makro Stop."))
        if action == "queue":
            self.gui(self.main.pages[0].queue._start)
            return Reply(tr("Farm routine started."))
        if action == "progression":
            nav.progression()
            return Reply(tr("Progressions: Auto All started."))
        if action == "close":
            nav.close_menu()
            return Reply(tr("Closing the menu."))
        return Reply(tr("Unknown action."))

    def _join(self, server: str) -> Reply:
        s = self.main.engine.settings
        if server:
            names = [f["name"] for f in s.server_favorites]
            if server not in names:
                return Reply(tr("There is no server “{name}”.", name=server))
            self.gui(lambda: self.main.join_favorite(names.index(server)))
            return Reply(tr("Joining “{name}” …", name=server))
        if not s.private_server_link:
            return Reply(tr("No private server set."))
        self.gui(self.main.join_private_server)
        return Reply(tr("Joining the marked server …"))

    def _power(self, action: str) -> Reply:
        if not self.main.engine.settings.bot_power:
            return Reply(tr("Shutting down via bot is off (Settings → Discord bot)."))
        try:
            subprocess.run(power_command(action), check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, ValueError) as exc:
            return Reply(tr("Error: {error}", error=exc))
        log.warning("Discord-Bot: /pc %s", action)
        if action == "abort":
            return Reply(tr("Shutdown cancelled."))
        return Reply(tr("The PC shuts down in 60 s – cancel with /pc Cancel.") if action == "shutdown"
                     else tr("The PC restarts in 60 s – cancel with /pc Cancel."))
