"""Macro part “guild missions”: once per PC day claim “Personal” and “Guild Weekly”; never near “Leave”. Without Qt."""

from __future__ import annotations

import time

from . import vision
from .i18n import tr
from .macro_base import OPEN_TIMEOUT, STEP_WAIT, Stop, UserStop

GUILD_RETRY = 3 * 3600    # guild missions: nothing to claim yet today -> try again this much later (owner 09.10.2026)
GUILD_TAB_WAIT = 0.6      # after switching a guild tab, before reading (was 1 s – owner: too slow)


def guild_next_time(done_day: str, retry: float, now: float) -> float:
    """Guild missions once per PC day: claimed today (done_day = today's local date) -> next local midnight; on a
    new day right away – unless “nothing to claim yet” set a retry time today."""
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    if done_day == today:
        t = time.localtime(now)
        return time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 0, 0, 0, 0, -1))
    return retry


class GuildMixin:
    """Part of the Navigator (automation.Navigator) – uses its input, image and log methods."""

    @property
    def guild_next(self) -> float:
        """Next guild visit: done today (PC date) -> local midnight, otherwise the retry time (0 = right away)."""
        return guild_next_time(self.guild_day, self.guild_retry, time.time())

    def _guild_claim(self) -> int:
        """Open the guild (button at the bottom left) → “Missions” → claim “Personal” and “Guild Weekly” → close.
        Returns the number of claims."""
        button = next((e for e in self.map.hud() if e["name"] == "Guild"), None)
        if button is None:
            raise Stop(tr("The guild button is unknown yet."))
        self._close_any()
        self.log(tr("Clicking “{button}”.", button="Guild"))
        self._click_roi(self.hud_roi(button))
        end = time.monotonic() + OPEN_TIMEOUT
        while self._screen(self._frame())[0] == "none":
            if time.monotonic() > end:
                raise Stop(tr("The guild did not open."))
            time.sleep(STEP_WAIT)
        time.sleep(0.6)
        guild = {"name": "Guild"}
        roi, frame = self._window_area(guild)                # block “Leave” at the bottom left before anything is clicked
        from .knowledge import forbidden_zones
        self.forbidden = forbidden_zones(vision.words_in(frame, roi, self._ocr), roi, "Guild")
        try:
            total = self._guild_pages(guild)
        finally:
            self.forbidden = []
        self._close_any()
        return total

    def _guild_forbidden(self) -> list:
        """Recompute the no-go zones for the guild page visible right now. Otherwise the zones of the home page (Kick,
        Leave …) lay over “Personal” after switching to “Missions” – the tab counted as blocked. Returns the words
        read (reused for the “Claim” search – one text recognition per page instead of two)."""
        from .knowledge import forbidden_zones
        roi, frame = self._window_area({"name": "Guild"})
        words = vision.words_in(frame, roi, self._ocr)
        self.forbidden = forbidden_zones(words, roi, "Guild")
        return words

    def _guild_pages(self, guild: dict) -> int:
        self._press(guild, ("missions",))
        time.sleep(GUILD_TAB_WAIT)
        self._guild_forbidden()
        total = 0
        for tab, label in ((("personal",), "Personal"), (("guild", "weekly"), "Guild Weekly")):
            try:
                self._press(guild, tab)
            except UserStop:
                raise
            except Stop as exc:
                self.log(tr("Tab “{tab}”: {reason}", tab=label, reason=exc))
                continue
            time.sleep(GUILD_TAB_WAIT)
            total += self._claim_all(label, self._guild_forbidden())
        if not total:
            self._snap("gilde")
        return total
