"""Connection guard and auto-rejoin (optional, off by default): rejoin the server after a disconnect, kick or
crash. Runs while auto-rejoin or the guard is on; the guard gets its disconnect alarm here (formerly via text
recognition in the middle of the window – the log is more precise and needs no screen capture).

Detection via the log of the Roblox client (%LOCALAPPDATA%\\Roblox\\logs) instead of image recognition: every few
seconds only the newly written lines are read – practically no CPU, no screen access.
    “! Joining game … place <number>”                  -> in game
    “Sending disconnect with reason: 285” etc.           -> left yourself (menu, window closed, server change)
    “Disconnection Notification. Reason: 277” etc.       -> connection lost / kicked -> rejoin
    Roblox process gone without leaving                  -> crash -> rejoin
Joining uses the link from “Private server” (roblox_join.py); without a link publicly into the same game.
The hanging client is ended before joining. Several attempts with a growing pause, then giving up until the
next successful join."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import messages, roblox_join
from .i18n import tr

log = logging.getLogger("rejoin")

POLL_LOG_EVERY = 3.0          # seconds between two looks into the log
POLL_PROCESS_EVERY = 5.0
GRACE = 15.0                  # handle a disconnect only after this time (server changes/teleports rejoin by themselves)
CRASH_AFTER = 8.0             # process gone this long (without “left” in the log) = crash
JOIN_TIMEOUT = 150.0          # wait this long for “Joining game” after an attempt
MAX_ATTEMPTS = 5
BACKOFF = (0, 30, 60, 120, 300)       # pause before attempt 1, 2, …
BOOTSTRAP_BYTES = 512 * 1024  # when switching on: read this much from the end of the current log (current state)
READ_LIMIT = 2 * 1024 * 1024  # at most this much new data per file and pass

# Reasons where we do NOT rejoin: left yourself (285), joined on another device (264/273/276)
INTENTIONAL_REASONS = {264, 273, 276, 285}
_JOIN_RE = re.compile(r"! Joining game '[^']*' place (\d+)")
_REASON_RE = re.compile(r"(?:Disconnection Notification\. Reason|Disconnect reason received|"
                        r"Sending disconnect with reason): ?(\d+)")
PUBLIC_DEEP_LINK = "roblox://experiences/start?placeId={place}"


def classify(line: str) -> Optional[tuple[str, int]]:
    """Classify a log line: ("join", game) | ("left", reason) | ("lost", reason) | None. Reason 0 = unknown."""
    if "Joining game" in line:
        m = _JOIN_RE.search(line)
        return ("join", int(m.group(1))) if m else None
    if "isconnect" in line:
        m = _REASON_RE.search(line)
        if m:
            code = int(m.group(1))
            return ("left" if code in INTENTIONAL_REASONS else "lost", code)
    if "Lost connection with reason" in line:
        return ("left" if "another device" in line else "lost", 0)
    if "Connection lost: connectMode: Peer Disconnected" in line:
        return ("lost", 0)
    return None


def log_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Roblox" / "logs"


class LogTail:
    """Reads only newly written lines of all client logs. Several files at once because a launcher log and the
    log of the actual client briefly grow in parallel when joining."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._offsets: dict[str, int] = {}
        self._rest: dict[str, bytes] = {}
        self._started = False

    def _files(self) -> list[tuple[str, int, float]]:
        out = []
        try:
            with os.scandir(self.folder) as it:
                for e in it:
                    if e.name.endswith(".log") and "_Player_" in e.name and "CrashHandler" not in e.name:
                        st = e.stat()
                        out.append((e.path, st.st_size, st.st_mtime))
        except OSError:
            pass
        return out

    def poll(self) -> list[str]:
        files = self._files()
        lines: list[str] = []
        if not self._started:                       # first look: only the end of the newest file (current state)
            self._started = True
            for path, size, _m in files:
                self._offsets[path] = size
            if files:
                path, size, _m = max(files, key=lambda f: f[2])
                lines = self._read(path, max(0, size - BOOTSTRAP_BYTES), size, skip_partial=True)
            return lines
        alive = set()
        for path, size, _m in sorted(files, key=lambda f: f[2]):
            alive.add(path)
            start = self._offsets.get(path, 0)      # new file: from the start
            if size < start:
                start = 0                           # the file was recreated
            if size > start:
                lines += self._read(path, start, size)
        for gone in set(self._offsets) - alive:
            self._offsets.pop(gone, None)
            self._rest.pop(gone, None)
        return lines

    def _read(self, path: str, start: int, size: int, skip_partial: bool = False) -> list[str]:
        start = max(start, size - READ_LIMIT)
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                data = fh.read(size - start)
        except OSError:
            return []
        self._offsets[path] = start + len(data)
        data = self._rest.pop(path, b"") + data
        parts = data.split(b"\n")
        if parts and parts[-1]:
            self._rest[path] = parts[-1][-65536:]   # complete an unfinished last line next time
        parts = parts[:-1]
        if skip_partial and start > 0:
            parts = parts[1:]
        return [p.decode("utf-8", "replace") for p in parts]


def _default_alive() -> Callable[[], bool]:
    from .guard import _default_finder
    find = _default_finder()
    return lambda: find() is not None


def kill_roblox(timeout: float = 10.0) -> int:
    """Ends hanging Roblox clients (RobloxPlayerBeta only). Returns the count."""
    import psutil

    from .guard import PROCESS_NAMES
    procs = [p for p in psutil.process_iter(["name"]) if (p.info.get("name") or "").lower() in PROCESS_NAMES]
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _gone, alive = psutil.wait_procs(procs, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    return len(procs)


def launch(uri: str) -> None:
    os.startfile(uri)                               # opens the registered Roblox client


class AutoRejoin(threading.Thread):
    def __init__(self, get_settings: Callable, event: Callable[[str, str], None], notify: Callable,
                 tail: Optional[LogTail] = None, alive: Optional[Callable[[], bool]] = None,
                 kill: Callable[[], int] = kill_roblox, start: Callable[[str], None] = launch,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        super().__init__(name="rejoin", daemon=True)
        self._get, self._event, self._notify = get_settings, event, notify
        self._tail_given = tail
        self._alive = alive
        self._kill, self._start, self._clock, self._sleep = kill, start, clock, sleep
        self._halt = threading.Event()
        self._reset()

    def _reset(self) -> None:
        self.tail: Optional[LogTail] = None
        self.status = "off"         # off | idle | in_game | left | lost | rejoining | gave_up | down (reported only)
        self.place: Optional[int] = None
        self.attempt = 0
        self.next_try = 0.0
        self.launched_at = 0.0
        self._next_log = 0.0
        self._next_proc = 0.0
        self._gone_since: Optional[float] = None
        self._reason = 0
        self._alerted = False

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        while not self._halt.wait(1.0):
            try:
                self.tick(self._clock())
            except Exception:
                log.exception("Auto-Rejoin: unerwarteter Fehler")

    def info(self, now: Optional[float] = None) -> str:
        """Short state for the header ("" = nothing special)."""
        now = self._clock() if now is None else now
        if self.status == "lost":
            return tr("Rejoin in {time}", time=messages.fmt_duration(max(0.0, self.next_try - now)))
        if self.status == "rejoining":
            return tr("joining … ({n}/{max})", n=self.attempt, max=MAX_ATTEMPTS)
        if self.status == "gave_up":
            return tr("Rejoin gave up")
        return ""

    # ------------------------------------------------------------------ Flow
    def tick(self, now: float) -> None:
        """One pass (public for tests)."""
        s = self._get()
        if not (s.auto_rejoin_enabled or s.guard_enabled or getattr(s, "auto_monitor", False)):
            if self.status != "off":
                self._reset()                       # everything off: read nothing, remember nothing
            return
        if self.status == "off":
            self.status = "idle"
            self.tail = self._tail_given or LogTail(log_dir())
            self._next_log = 0.0
        if now >= self._next_log:
            self._next_log = now + POLL_LOG_EVERY
            for line in self.tail.poll():
                self._on_line(line, now)
        if self.status == "in_game" and now >= self._next_proc:
            self._next_proc = now + POLL_PROCESS_EVERY
            self._check_process(now)
        if not s.auto_rejoin_enabled and self.status in ("lost", "rejoining", "gave_up") and now >= self.next_try:
            self._alert(s)
            self.status = "down"                    # reported only; back to “in game” at the next join
            return
        if self.status == "lost" and now >= self.next_try:
            self._alert(s)
            self._rejoin(now, s)
        elif self.status == "rejoining" and now - self.launched_at >= JOIN_TIMEOUT:
            self._failed(now, tr("no join within {seconds} s", seconds=int(JOIN_TIMEOUT)))

    def _on_line(self, line: str, now: float) -> None:
        kind = classify(line)
        if kind is None:
            return
        what, value = kind
        if what == "join":
            if self.status == "rejoining":
                log.info("Auto-Rejoin: wieder im Spiel (Versuch %d)", self.attempt)
                self._event(tr("Auto-rejoin: back in the game"), "ok")
                self._notify("rejoin", tr("Back in the game"), messages.COLOR_OK,
                             description=tr("Auto-rejoin worked (attempt {n}).", n=self.attempt))
            self.status, self.place, self.attempt, self._gone_since = "in_game", value, 0, None
        elif what == "left" and self.status in ("in_game", "lost"):
            self.status = "left"                    # left yourself: don't go back (even if “lost” shortly before)
            log.info("Auto-rejoin: left the game (reason %s) – no rejoin", value or "?")
        elif what == "lost" and self.status == "in_game":
            self._lost(now, value, GRACE)

    def _check_process(self, now: float) -> None:
        alive = (self._alive or _default_alive_cached(self))()
        if alive:
            self._gone_since = None
            return
        if self._gone_since is None:
            self._gone_since = now
        elif now - self._gone_since >= CRASH_AFTER:
            for line in self.tail.poll():          # last lines: did you leave yourself after all?
                self._on_line(line, now)
            if self.status == "in_game":
                self._lost(now, -1, 0.0)

    def _reason_text(self) -> str:
        reason = self._reason
        return (tr("Roblox crashed") if reason == -1 else
                tr("Connection lost (error {code})", code=reason) if reason else tr("Connection lost"))

    def _lost(self, now: float, reason: int, grace: float) -> None:
        self.status, self._reason, self._alerted = "lost", reason, False
        self.next_try = now + grace
        text = self._reason_text()
        log.info("Verbindung: %s", text)
        if self._get().auto_rejoin_enabled:
            self._event(tr("Auto-rejoin: {reason} – rejoining shortly", reason=text), "warn")

    def _alert(self, s) -> None:
        """Guard alarm “disconnect” (once per disconnect, only after the waiting time – teleports don't trigger it).
        Crashes are reported by the monitoring's guard itself via the process."""
        if self._alerted or not s.guard_enabled or self._reason == -1:
            return
        self._alerted = True
        text = self._reason_text()
        self._event(tr("Disconnect detected: {reason}", reason=text), "error")
        self._notify("roblox_down", tr("Disconnect detected"), messages.COLOR_ERROR,
                     description=text + (" – " + tr("Auto-rejoin is rejoining.") if s.auto_rejoin_enabled else ""))

    def target(self, s) -> tuple[Optional[str], str]:
        """(roblox:// link, description) for joining."""
        uri = roblox_join.deep_link(s.private_server_link)
        if uri:
            return uri, tr("private server")
        if self.place:
            return PUBLIC_DEEP_LINK.format(place=self.place), tr("public server")
        return None, ""

    def _rejoin(self, now: float, s) -> None:
        uri, where = self.target(s)
        if uri is None:
            self._give_up(tr("No private server link set and the game is unknown."))
            return
        self.attempt += 1
        self.status, self.launched_at = "rejoining", now
        log.info("Auto-Rejoin: Versuch %d/%d (%s)", self.attempt, MAX_ATTEMPTS, where)
        self._event(tr("Auto-rejoin: attempt {n}/{max} ({where})", n=self.attempt, max=MAX_ATTEMPTS, where=where), "info")
        if self.attempt == 1:
            self._notify("rejoin", tr("Connection lost – auto-rejoin"), messages.COLOR_WARN,
                         description=tr("Rejoining ({where}).", where=where))
        try:
            if self._kill():
                self._sleep(2.0)                    # let Roblox release the windows/files
            self._start(uri)
        except Exception as exc:
            log.warning("Auto-Rejoin: Start fehlgeschlagen: %s", exc)
            self._failed(self._clock(), str(exc))
            return
        self.launched_at = self._clock()            # waiting time from the actual start

    def _failed(self, now: float, why: str) -> None:
        log.info("Auto-Rejoin: Versuch %d fehlgeschlagen: %s", self.attempt, why)
        if self.attempt >= MAX_ATTEMPTS:
            self._give_up(why)
            return
        self.status = "lost"
        self.next_try = now + BACKOFF[min(self.attempt, len(BACKOFF) - 1)]
        self._event(tr("Auto-rejoin: attempt {n} failed ({why})", n=self.attempt, why=why), "warn")

    def _give_up(self, why: str) -> None:
        self.status = "gave_up"
        text = tr("Auto-rejoin gave up: {why}", why=why)
        log.warning(text)
        self._event(text, "error")
        self._notify("rejoin", tr("Auto-rejoin gave up"), messages.COLOR_ERROR, description=why)


def _default_alive_cached(obj: AutoRejoin) -> Callable[[], bool]:
    obj._alive = _default_alive()
    return obj._alive
