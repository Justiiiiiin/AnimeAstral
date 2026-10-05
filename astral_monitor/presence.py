"""Discord-Profilstatus („Farmt Militech Convoy · Welle 14“) über die lokale Discord-App (Rich Presence)."""
from __future__ import annotations

import logging
import re
import threading
import unicodedata
from typing import Callable, Optional

from . import build_info
from .settings import Settings

log = logging.getLogger("presence")

INTERVAL = 15.0          # Discord aktualisiert den Status höchstens alle 15 Sekunden
RETRY = 30.0             # so lange Pause nach einem Verbindungsfehler (Discord-App nicht gestartet o. Ä.)
DEFAULT_IMAGE = "logo"   # Name des Standardbilds im Discord-Entwicklerportal


def slug(name: str) -> str:
    """Asset-Name für ein Profil: „Militech Convoy“ -> „militech_convoy“ (Discord erlaubt Kleinbuchstaben/Ziffern/_)."""
    text = unicodedata.normalize("NFKD", name.replace("ß", "ss")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:32] or DEFAULT_IMAGE


def client_id(settings: Settings) -> str:
    return (settings.rpc_client_id.strip() or build_info.RPC_CLIENT_ID.strip())


def build_activity(settings: Settings, snap: dict) -> Optional[dict]:
    """Argumente für Presence.update(); None = nichts anzeigen (Überwachung gestoppt)."""
    if snap.get("status") == "stopped":
        return None
    profile = snap.get("profile") or ""
    if snap.get("wave") is not None and snap.get("total_waves"):
        details = f"Welle {snap['wave']}/{snap['total_waves']}" + (f" · {profile}" if profile else "")
    else:
        details = "Wartet auf den nächsten Raid" + (" (pausiert)" if snap.get("status") == "paused" else "")
    state = f"✓ {snap.get('session_ok', 0)} · ✗ {snap.get('session_failed', 0)}"
    if snap.get("best_wave"):
        state += f" · Bestwelle {snap['best_wave']}"
    activity = {
        "details": details[:128], "state": state[:128],
        "large_image": slug(profile) if profile else DEFAULT_IMAGE,
        "large_text": (profile or "Anime Astral Monitor")[:128],
        "small_image": DEFAULT_IMAGE, "small_text": "Anime Astral Monitor",
    }
    if snap.get("started_unix"):
        activity["start"] = int(snap["started_unix"])
    return activity


class PresenceUpdater(threading.Thread):
    def __init__(self, get_settings: Callable[[], Settings], get_snapshot: Callable[[], dict],
                 factory: Optional[Callable[[str], object]] = None) -> None:
        super().__init__(name="presence", daemon=True)
        self._get, self._snapshot = get_settings, get_snapshot
        self._factory = factory
        self._halt = threading.Event()
        self._rpc = None
        self._last: Optional[dict] = None
        self._next_try = 0.0
        self._warned = False

    def stop(self) -> None:
        self._halt.set()

    def _connect(self, cid: str):
        factory = self._factory
        if factory is None:
            from pypresence import Presence               # erst hier laden: optionales Paket
            factory = Presence
        rpc = factory(cid)
        rpc.connect()
        return rpc

    def _drop(self) -> None:
        rpc, self._rpc, self._last = self._rpc, None, None
        if rpc is not None:
            try:
                rpc.clear()
            except Exception:
                pass
            try:
                rpc.close()
            except Exception:
                pass

    def run(self) -> None:
        import time
        while not self._halt.wait(INTERVAL):
            try:
                self.tick(time.monotonic())
            except Exception:
                log.exception("Discord-Profilstatus: unerwarteter Fehler")
                self._drop()
        self._drop()

    def tick(self, now: float) -> None:
        """Ein Durchlauf (öffentlich, damit er sich testen lässt)."""
        s = self._get()
        cid = client_id(s)
        if not s.rpc_enabled or not cid:
            self._drop()
            return
        activity = build_activity(s, self._snapshot())
        if activity is None:
            self._drop()
            return
        if self._rpc is None:
            if now < self._next_try:
                return
            try:
                self._rpc = self._connect(cid)
                self._warned = False
                log.info("Discord-Profilstatus verbunden.")
            except Exception as exc:
                self._next_try = now + RETRY
                if not self._warned:
                    log.info("Discord-Profilstatus nicht möglich (läuft die Discord-App?): %s", exc.__class__.__name__)
                    self._warned = True
                return
        if activity != self._last:
            try:
                self._rpc.update(**activity)
                self._last = activity
            except Exception as exc:
                log.info("Discord-Profilstatus getrennt: %s", exc.__class__.__name__)
                self._drop()
