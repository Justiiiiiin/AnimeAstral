"""Shared building blocks of the macro (automation.py and its parts): errors, timing, small helpers. Without Qt."""

from __future__ import annotations

import logging
import re
import threading
from typing import Optional

from .i18n import tr

_log = logging.getLogger("macro")

STEP_WAIT = 0.15          # spacing of the checks after a click
OPEN_TIMEOUT = 5.0        # a menu may take this long to open
SCROLL_NOTCHES = 4        # mouse wheel notches per step
BAR_STEP = 0.15           # drag the scroll bar by this share of the track per step
MAX_SCROLLS = 60
USER_MOVE_PX = 25         # mouse this far from the set spot = the user intervenes -> stop
AUTO_SETTLE = 0.8         # after “Auto!” wait briefly, then close (auto roll keeps running in the background)
_ACTIVE = threading.Event()    # a macro run is going on right now (Anti-AFK waits then)
CLAIM_LIMIT = 8           # at most this many “Claim” per page (protection against endless loops)
CLAIM_GAP = 0.35          # between two “Claim” clicks of one reading
CLAIM_SETTLE = 0.5        # after the clicks of one reading, before reading again
EXTRA_RETRY = 15 * 60     # after a failure try again this much later at the earliest


def macro_running() -> bool:
    return _ACTIVE.is_set()


class Stop(Exception):
    """Stop (user, timeout, not found) – text = reason for the log."""


class UserStop(Stop):
    """Stopped by the user (stop, Esc, mouse, Roblox not in front) – the routine ends right away."""


def fmt_wait(seconds: float) -> str:
    """Short waiting time: “45 s”, “18 min”, “1 h 36 min”, “23 h”."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return tr("{n} s", n=seconds)
    minutes = (seconds + 59) // 60
    if minutes < 60:
        return tr("{n} min", n=minutes)
    hours, rest = divmod(minutes, 60)
    return tr("{h} h {m} min", h=hours, m=rest) if rest and hours < 10 else tr("{h} h", h=hours)


def parse_timer(text: str) -> Optional[int]:
    """“1:20:40” / “33:57” -> seconds (Fixer Gigs times), otherwise None."""
    m = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})", text.strip())
    if not m:
        return None
    h, mnt, s = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    return h * 3600 + mnt * 60 + s if mnt < 60 and s < 60 else None


def task_label(task: dict) -> str:
    """Display of a routine task."""
    kind = task.get("kind")
    if kind == "autoroll":
        return tr("Auto Roll · {target}", target=task.get("target", "?"))
    if kind == "raid":
        until = task.get("until", "runs")
        text = tr("Farm · {target}", target=task.get("target", "?"))
        if until == "runs":
            text += " · " + tr("{runs} raids", runs=int(task.get("runs", 1)))
        elif until == "minutes":
            text += " · " + tr("{minutes} min.", minutes=int(task.get("minutes", 30)))
        else:
            text += " · " + tr("until stopped")
        if int(task.get("leave_wave", 0)):
            text += " · " + tr("leave from wave {wave}", wave=int(task["leave_wave"]))
        return text + (" · " + tr("join") if task.get("join") else "")
    if kind == "progression":
        return tr("Progressions: Auto All")
    if kind == "wait":
        seconds = int(task.get("seconds", 60))
        return tr("Pause · {minutes} min", minutes=seconds // 60) if seconds % 60 == 0 and seconds >= 60 else \
            tr("Pause · {seconds} s", seconds=seconds)
    return str(kind)
