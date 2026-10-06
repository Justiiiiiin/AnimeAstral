"""Wächter: Roblox-Prozess, Stillstand, Speicher. Disconnects erkennt rejoin.py über das Roblox-Protokoll."""
from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np

from . import messages
from .i18n import tr
from .settings import Settings

log = logging.getLogger("guard")

PROCESS_NAMES = ("robloxplayerbeta.exe", "robloxplayerbeta")

POLL_PROCESS_EVERY = 5.0          # Sekunden
PROCESS_DOWN_AFTER = 6.0
NO_FRAMES_AFTER = 30.0
RAM_REPEAT_SECONDS = 1800.0


def _default_finder():
    """Sucht den Roblox-Prozess (mit Zwischenspeicher)."""
    import psutil
    cache: dict = {"proc": None}

    def find():
        proc = cache["proc"]
        if proc is not None:
            try:
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    return proc
            except psutil.Error:
                pass
            cache["proc"] = None
        for candidate in psutil.process_iter(["name"]):
            if (candidate.info.get("name") or "").lower() in PROCESS_NAMES:
                candidate.cpu_percent(None)                     # Messung beginnen
                cache["proc"] = candidate
                return candidate
        return None

    return find


class Guard:
    def __init__(self, get_settings: Callable[[], Settings], state,
                 notify: Callable, event: Callable[[str, str], None],
                 grab_full: Callable[[], Optional[np.ndarray]], process_finder=None) -> None:
        self._get = get_settings
        self._state = state
        self._notify, self._event = notify, event
        self._grab_full = grab_full
        self._find = process_finder or _default_finder()
        self._cpu_count = 1
        try:
            import psutil
            self._cpu_count = psutil.cpu_count() or 1
        except Exception:
            pass
        self.reset(0.0)

    # ------------------------------------------------------------------ Zustand
    def reset(self, now: float) -> None:
        self._seen_proc = False
        self._down_since: Optional[float] = None
        self._down_alerted = False
        self._next_poll = 0.0
        self._next_ram = 0.0
        self._wave_value: Optional[int] = None
        self._last_change = now
        self._stall_alerted = False
        self._missing_since: Optional[float] = None
        self._missing_alerted = False
        self._ref_raid = now
        self._noraid_alerted = False
        self._started = now

    @property
    def enabled(self) -> bool:
        return self._get().guard_enabled

    # ------------------------------------------------------------ Eingaben der Engine
    def on_frame(self) -> None:
        if self._missing_alerted:
            self._event(tr("Bilder vom Roblox-Fenster kommen wieder an"), "ok")
        self._missing_since, self._missing_alerted = None, False

    def on_missing(self, now: float) -> None:
        if not self.enabled:
            return
        if self._missing_since is None:
            self._missing_since = now
        if (now - self._missing_since >= NO_FRAMES_AFTER and not self._missing_alerted
                and not self._down_alerted):
            self._missing_alerted = True
            self._event(tr("Keine Bilder vom Roblox-Fenster"), "error")
            self._notify("roblox_down", tr("Keine Bilder vom Roblox-Fenster"), messages.COLOR_ERROR,
                         description=tr("Das Fenster ist minimiert, geschlossen oder eingefroren."))

    def on_wave(self, value: Optional[int], now: float) -> None:
        if value is None:
            self._wave_value = None          # ohne sichtbaren Zähler gibt es keinen Stillstand
            return
        if value != self._wave_value:
            self._wave_value = value
            self._last_change = now
            if self._stall_alerted:
                self._stall_alerted = False
                self._event(tr("Zähler läuft wieder"), "ok")
                self._notify("stall", tr("Zähler läuft wieder"), messages.COLOR_OK,
                             description=tr("Aktuell Welle {wave}.", wave=value))

    def on_raid_end(self, now: float) -> None:
        self._ref_raid = now
        if self._noraid_alerted:
            self._noraid_alerted = False
            self._event(tr("Raids laufen wieder"), "ok")

    # ------------------------------------------------------------------ Prozess
    def poll_process(self, now: float) -> None:
        if now < self._next_poll:
            return
        self._next_poll = now + POLL_PROCESS_EVERY
        st, s = self._state, self._get()
        proc = None
        try:
            proc = self._find()
        except Exception:
            log.debug("Prozesssuche fehlgeschlagen", exc_info=True)

        if proc is None:
            st.roblox_alive, st.roblox_ram_mb, st.roblox_cpu = (False if self._seen_proc else None), None, None
            if self._seen_proc and s.guard_enabled:
                if self._down_since is None:
                    self._down_since = now
                elif now - self._down_since >= PROCESS_DOWN_AFTER and not self._down_alerted:
                    self._down_alerted = True
                    self._event(tr("Roblox wurde beendet oder ist abgestürzt"), "error")
                    self._notify("roblox_down", tr("Roblox wurde beendet"), messages.COLOR_ERROR,
                                 description=tr("Der Roblox-Prozess läuft nicht mehr (Absturz oder geschlossen)."))
            return

        self._seen_proc = True
        st.roblox_alive = True
        try:
            st.roblox_ram_mb = proc.memory_info().rss / 1048576
            st.roblox_cpu = proc.cpu_percent(None) / self._cpu_count
        except Exception:
            st.roblox_ram_mb = st.roblox_cpu = None
        if self._down_alerted:
            self._event(tr("Roblox läuft wieder"), "ok")
            self._notify("roblox_down", tr("Roblox läuft wieder"), messages.COLOR_OK)
        self._down_since, self._down_alerted = None, False

        limit = s.ram_alert_gb * 1024
        if (s.guard_enabled and limit > 0 and st.roblox_ram_mb and st.roblox_ram_mb >= limit
                and now >= self._next_ram):
            self._next_ram = now + RAM_REPEAT_SECONDS
            gb = st.roblox_ram_mb / 1024
            self._event(tr("Roblox belegt {gb} GB Arbeitsspeicher", gb=f"{gb:.1f}"), "warn")
            self._notify("health", tr("Hoher Speicherverbrauch"), messages.COLOR_WARN,
                         [(tr("Roblox RAM"), f"{gb:.1f} GB", True), (tr("Grenze"), f"{s.ram_alert_gb:g} GB", True)],
                         tr("Bei sehr langen Sitzungen hilft ein Neustart von Roblox."))

    # ---------------------------------------------------------------- Stillstand
    def check_stall(self, now: float, in_raid: bool) -> None:
        s = self._get()
        if not s.guard_enabled:
            return
        if in_raid and self._wave_value is not None and not self._stall_alerted \
                and now - self._last_change >= s.stall_minutes * 60:
            self._stall_alerted = True
            minutes = (now - self._last_change) / 60
            text = tr("Der Zähler steht seit {minutes} Min. bei Welle {wave}.", minutes=f"{minutes:.0f}", wave=self._wave_value)
            self._event(text, "error")
            self._notify("stall", tr("Stillstand erkannt"), messages.COLOR_WARN,
                         [(tr("Welle"), str(self._wave_value), True), (tr("Dauer"), tr("{minutes} Min.", minutes=f"{minutes:.0f}"), True)],
                         text, self._screenshot())
        if s.no_raid_minutes > 0 and not self._noraid_alerted and self._state.roblox_alive is not False \
                and now - self._ref_raid >= s.no_raid_minutes * 60:
            self._noraid_alerted = True
            text = tr("Seit {minutes} Min. wurde kein Raid beendet.", minutes=s.no_raid_minutes)
            self._event(text, "warn")
            self._notify("stall", tr("Kein Raid-Fortschritt"), messages.COLOR_WARN, description=text,
                         image=self._screenshot())

    def _screenshot(self):
        try:
            from .imaging import encode_jpeg
            frame = self._grab_full()
            return ("alarm.jpg", encode_jpeg(frame)) if frame is not None else None
        except Exception:
            log.debug("Alarm-Screenshot fehlgeschlagen", exc_info=True)
            return None

