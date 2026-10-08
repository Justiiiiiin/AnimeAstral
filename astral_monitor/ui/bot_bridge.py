"""Verbindung Discord-Bot ↔ Programm: startet/stoppt den eigenen Bot des Nutzers (discord_bot.py) nach den
Einstellungen und führt seine Befehle aus. Die Befehle kommen aus dem Bot-Thread; alles, was die Oberfläche anfasst,
läuft über MainWindow.post im GUI-Thread (gui())."""
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
        self.state = tr("aus")
        self.app_id = ""
        self._key: tuple = ()
        self.listeners: list[Callable[[str, str], None]] = []    # Einstellungs-Reiter zeigt den Zustand an

    # ------------------------------------------------------------------ Start/Stopp nach den Einstellungen
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
            threading.Thread(target=bot.stop, daemon=True).start()      # nicht im GUI-Thread warten
        self._state(tr("aus"), self.app_id)

    def _state(self, text: str, app_id: str) -> None:
        self.state, self.app_id = text, app_id or self.app_id
        for fn in list(self.listeners):
            self.main.post(lambda fn=fn: fn(self.state, self.app_id))

    # ------------------------------------------------------------------ Hilfen
    def gui(self, fn: Callable, timeout: float = 20.0):
        """fn im GUI-Thread ausführen und auf das Ergebnis warten (aus dem Bot-Thread)."""
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
            raise TimeoutError(tr("Das Programm hat nicht rechtzeitig geantwortet."))
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

    # ------------------------------------------------------------------ Befehle
    def handle(self, name: str, args: dict) -> Reply:
        main, engine = self.main, self.main.engine
        if name == "status":
            return Reply(self._status_text())
        if name == "start":
            if engine.running:
                return Reply(tr("Die Überwachung läuft schon."))
            self.gui(main.toggle_monitoring)
            return Reply(tr("Überwachung gestartet.") if engine.running else tr("Start nicht möglich – siehe Programm."))
        if name == "stop":
            if not engine.running:
                return Reply(tr("Die Überwachung ist schon aus."))
            self.gui(main.toggle_monitoring)
            return Reply(tr("Überwachung gestoppt."))
        if name == "pause":
            if not engine.running:
                return Reply(tr("Die Überwachung ist aus."))
            self.gui(main.toggle_pause)
            return Reply(tr("Pausiert.") if engine.state.paused else tr("Läuft weiter."))
        if name == "screenshot":
            return self._screenshot()
        if name == "raid":
            wanted = (args.get("name") or "").strip()
            match = next((n for n in engine.profile_store.names() if n.lower() == wanted.lower()), None)
            if match is None:
                return Reply(tr("Raid „{name}“ gibt es nicht.", name=wanted))
            self.gui(lambda: main.select_raid(match))
            return Reply(tr("Aktueller Raid: {name}", name=match))
        if name == "makro":
            return self._macro(args.get("action", ""))
        if name == "antiafk":
            self.gui(lambda: main.set_anti_afk(bool(args.get("on"))))
            return Reply(tr("Anti-AFK an") if args.get("on") else tr("Anti-AFK aus"))
        if name == "autorejoin":
            self.gui(lambda: main.set_auto_rejoin(bool(args.get("on"))))
            return Reply(tr("Auto-Rejoin an") if args.get("on") else tr("Auto-Rejoin aus"))
        if name == "join":
            return self._join(args.get("server", ""))
        if name == "pc":
            return self._power(args.get("action", ""))
        if name == "hilfe":
            return Reply(tr("Befehle: {commands}", commands=", ".join("/" + c for c in COMMANDS)))
        return Reply(tr("Unbekannter Befehl."))

    def _status_text(self) -> str:
        engine = self.main.engine
        snap = engine.status_snapshot()
        state = {"running": tr("läuft"), "paused": tr("pausiert"), "stopped": tr("aus")}[snap["status"]]
        lines = [tr("**Überwachung:** {state}", state=state)]
        if snap["wave"] is not None:
            lines[0] += " · " + tr("Welle {wave}", wave=messages.fmt_wave(snap["wave"], snap["total_waves"]))
        if snap["profile"]:
            lines[0] += " · " + tr("Raid: {name}", name=snap["profile"])
        lines.append(tr("Versuche: {session} (Session) · {total} gesamt", session=snap["session_attempts"],
                        total=messages.fmt_k(snap["total_attempts"])))
        try:
            from ..automation import macro_running
            macro = tr("läuft") if macro_running() else tr("aus")
        except Exception:  # noqa: BLE001
            macro = "?"
        s = engine.settings
        lines.append(tr("Makro: {macro} · Anti-AFK: {afk} · Auto-Rejoin: {rejoin}", macro=macro,
                        afk=tr("an") if s.anti_afk_enabled else tr("aus"),
                        rejoin=tr("an") if s.auto_rejoin_enabled else tr("aus")))
        return "\n".join(lines)

    def _screenshot(self) -> Reply:
        import cv2
        engine = self.main.engine
        frame = engine._grab_full() if engine.running else None
        if frame is None:
            res = engine.grab_for_ui(full=True)
            frame = res.full if res is not None else None
        if frame is None:
            return Reply(tr("Kein Bild vom Roblox-Fenster (läuft Roblox?)."))
        h, w = frame.shape[:2]
        if w > 1280:
            frame = cv2.resize(frame, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_AREA)
        ok, png = cv2.imencode(".png", frame)
        return Reply(tr("Roblox-Fenster:"), png.tobytes() if ok else None)

    def _macro(self, action: str) -> Reply:
        macro = self.main.macro
        if not macro.enabled:
            return Reply(tr("Das Makro ist im Programm nicht erlaubt („Makro erlauben“)."))
        nav = self.gui(macro.ensure_navigator)
        if action == "stop":
            nav.stop()
            return Reply(tr("Makro gestoppt."))
        if nav.busy:
            return Reply(tr("Das Makro läuft schon – erst /makro Stopp."))
        if action == "queue":
            self.gui(self.main.pages[0].queue._start)
            return Reply(tr("Farm-Routine gestartet."))
        if action == "progression":
            nav.progression()
            return Reply(tr("Progressions: Auto All gestartet."))
        if action == "close":
            nav.close_menu()
            return Reply(tr("Menü wird geschlossen."))
        return Reply(tr("Unbekannte Aktion."))

    def _join(self, server: str) -> Reply:
        s = self.main.engine.settings
        if server:
            names = [f["name"] for f in s.server_favorites]
            if server not in names:
                return Reply(tr("Server „{name}“ gibt es nicht.", name=server))
            self.gui(lambda: self.main.join_favorite(names.index(server)))
            return Reply(tr("Trete „{name}“ bei …", name=server))
        if not s.private_server_link:
            return Reply(tr("Kein privater Server eingetragen."))
        self.gui(self.main.join_private_server)
        return Reply(tr("Trete dem markierten Server bei …"))

    def _power(self, action: str) -> Reply:
        if not self.main.engine.settings.bot_power:
            return Reply(tr("Herunterfahren per Bot ist aus (Einstellungen → Discord-Bot)."))
        try:
            subprocess.run(power_command(action), check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, ValueError) as exc:
            return Reply(tr("Fehler: {error}", error=exc))
        log.warning("Discord-Bot: /pc %s", action)
        if action == "abort":
            return Reply(tr("Herunterfahren abgebrochen."))
        return Reply(tr("Der PC fährt in 60 s herunter – abbrechen mit /pc Abbrechen.") if action == "shutdown"
                     else tr("Der PC startet in 60 s neu – abbrechen mit /pc Abbrechen."))
