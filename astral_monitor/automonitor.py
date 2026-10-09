"""Auto-start (optional, off by default): monitoring starts as soon as Anime Astral is entered, pauses on a
disconnect/kick/crash and stops when leaving. It is based on the game state from the Roblox log (rejoin.py) –
no image recognition, no input.

Only transitions trigger something (not the state itself): whoever stops while in the game stays stopped until the
next time they enter; whoever starts without being in the game is not stopped. `AutoMonitor.tick` makes the
decisions (pure logic, testable), the main window carries them out."""
from __future__ import annotations

from typing import Optional

from .i18n import tr

GAME_PLACE = 102072869879193      # Anime Astral (one place for the lobby and all raids, checked in the log 06.10.2026)
START_DELAY = 5.0                 # after entering wait briefly until the window is there
STOP_GRACE = 20.0                 # leaving only after this time (server change/join via link rejoin right away)
TROUBLE_STOP = 180.0              # without auto-rejoin: stop after a disruption this long
RETRY_START = 30.0                # start failed (window not there yet …): try again

IN_GAME, TROUBLE, GONE, ELSEWHERE = "in_game", "trouble", "gone", "elsewhere"


def phase_of(status: str, place: Optional[int]) -> str:
    """Spielzustand aus rejoin.AutoRejoin (status, place)."""
    if status == "in_game":
        return IN_GAME if place == GAME_PLACE else ELSEWHERE
    if status in ("lost", "rejoining", "down", "gave_up"):
        return TROUBLE
    return GONE


class AutoMonitor:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.prev: Optional[str] = None
        self.start_at: Optional[float] = None
        self.stop_at: Optional[float] = None
        self.trouble_since: Optional[float] = None
        self.override = False               # stopped yourself while in the game: do nothing until the next time you enter
        self.auto_paused = False            # only pauses set by us are lifted automatically

    # ------------------------------------------------------------------ User actions
    def user_stopped(self) -> None:
        if self.prev in (IN_GAME, TROUBLE):
            self.override = True
        self.start_at = self.stop_at = None
        self.auto_paused = False

    def user_paused(self) -> None:
        self.auto_paused = False            # pause/resume by hand takes precedence

    def start_failed(self, now: float) -> None:
        self.start_at = now + RETRY_START

    # ------------------------------------------------------------------ Entscheidung
    def tick(self, now: float, phase: str, running: bool, paused: bool, rejoin_on: bool,
             gave_up: bool = False) -> list[str]:
        """Returns: actions in order ("start", "pause", "resume", "stop")."""
        acts: list[str] = []
        if phase != self.prev:
            if phase == IN_GAME:
                if self.prev in (None, GONE, ELSEWHERE):
                    self.override = False   # entered anew: your own earlier decision no longer applies
                self.start_at = now + START_DELAY
                self.stop_at = self.trouble_since = None
            elif phase == TROUBLE:
                self.trouble_since, self.stop_at = now, None
                if running and not paused:
                    acts.append("pause")
                    self.auto_paused = True
            elif self.prev in (IN_GAME, TROUBLE) and running:
                self.stop_at, self.start_at = now + STOP_GRACE, None
            self.prev = phase

        if phase == IN_GAME:
            if not running and not self.override and self.start_at is not None and now >= self.start_at:
                acts.append("start")
                self.start_at = None
            elif running and paused and self.auto_paused:
                acts.append("resume")
                self.auto_paused = False
        elif phase == TROUBLE and running and self.trouble_since is not None and (
                gave_up or (not rejoin_on and now - self.trouble_since >= TROUBLE_STOP)):
            acts.append("stop")
            self.trouble_since = None
            self.auto_paused = False
        if self.stop_at is not None and now >= self.stop_at:
            if running and phase != IN_GAME:
                acts.append("stop")
                self.auto_paused = False
            self.stop_at = None
        return acts

    def info(self, now: float, phase: str, running: bool) -> str:
        """Short hint for the header ("" = nothing special)."""
        if phase == IN_GAME and not running and self.override:
            return tr("stopped manually")
        if phase == IN_GAME and not running and self.start_at is not None:
            return tr("starts in {s} s", s=max(0, int(self.start_at - now + 0.99)))
        if phase == TROUBLE and running and self.auto_paused:
            return tr("paused (connection)")
        if self.stop_at is not None and running:
            return tr("stops in {s} s", s=max(0, int(self.stop_at - now + 0.99)))
        if phase in (GONE, ELSEWHERE) and not running:
            return tr("waiting for Anime Astral")
        return ""
