"""Discord-Profilstatus („Farmt … · Welle 14“) mit dem Spiel-Thumbnail von Roblox – über die lokale Discord-App."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Callable, Optional

import requests

from . import app_paths, build_info
from .i18n import tr
from .settings import Settings

log = logging.getLogger("presence")

INTERVAL = 15.0           # Discord aktualisiert den Status höchstens alle 15 Sekunden
RETRY = 30.0              # Pause nach einem Verbindungsfehler (Discord-App nicht gestartet o. Ä.)
ICON_TTL = 24 * 3600      # Thumbnail höchstens einmal am Tag neu laden
ICON_RETRY = 600          # bei Fehlschlag nach 10 Minuten erneut versuchen
GAME_NAME = "Anime Astral"
UNIVERSE_API = "https://apis.roblox.com/universes/v1/places/{id}/universe"
ICON_API = ("https://thumbnails.roblox.com/v1/games/icons?universeIds={id}&returnPolicy=PlaceHolder"
            "&size=512x512&format=Png&isCircular=false")


def client_id(settings: Settings) -> str:
    return settings.rpc_client_id.strip() or build_info.RPC_CLIENT_ID.strip()


# ------------------------------------------------------------------------ Spiel-Thumbnail
def parse_game_id(text: str) -> Optional[int]:
    """Aus einem Roblox-Link („…/games/12345/Name“) oder einer reinen Zahl die Spiel-Nummer lesen."""
    match = re.search(r"(?:games|experiences)/(\d+)", text) or re.fullmatch(r"\s*(\d{5,})\s*", text)
    return int(match.group(1)) if match else None


def fetch_icon_url(game_id: int, getter: Callable = requests.get, timeout: float = 10.0) -> Optional[str]:
    """Öffentliche Roblox-Schnittstellen: Spiel-/Place-Nummer -> Universe -> Thumbnail-Adresse."""
    headers = {"User-Agent": "AnimeAstralMonitor"}
    universe = game_id                                     # falls die Nummer schon eine Universe-Nummer ist
    try:
        resp = getter(UNIVERSE_API.format(id=game_id), timeout=timeout, headers=headers)
        if resp.status_code == 200:
            universe = int(resp.json().get("universeId") or game_id)
        resp = getter(ICON_API.format(id=universe), timeout=timeout, headers=headers)
        if resp.status_code != 200:
            return None
        for entry in resp.json().get("data", []):
            url = str(entry.get("imageUrl") or "")
            if entry.get("state") == "Completed" and url.startswith("https://"):
                return url
    except (requests.RequestException, ValueError, TypeError):
        log.debug("Thumbnail konnte nicht geladen werden", exc_info=True)
    return None


def _icon_cache_file():
    return app_paths.data_dir() / "rpc_icon.json"


def load_cached_icon(game_id: int, now: Optional[float] = None) -> Optional[str]:
    try:
        data = json.loads(_icon_cache_file().read_text(encoding="utf-8"))
        if data.get("id") == game_id and ((now or time.time()) - data.get("ts", 0)) < ICON_TTL:
            return data.get("url") or None
    except (OSError, ValueError):
        pass
    return None


def save_cached_icon(game_id: int, url: str) -> None:
    try:
        _icon_cache_file().write_text(json.dumps({"id": game_id, "url": url, "ts": time.time()}), encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------------------ Aktivität
def build_activity(settings: Settings, snap: dict, icon_url: Optional[str] = None) -> Optional[dict]:
    """Argumente für Presence.update(); None = nichts anzeigen (Überwachung gestoppt)."""
    if snap.get("status") == "stopped":
        return None
    profile = snap.get("profile") or ""
    if snap.get("wave") is not None and snap.get("total_waves"):
        details = tr("Welle {wave}/{total}", wave=snap["wave"], total=snap["total_waves"]) + (f" · {profile}" if profile else "")
    else:
        details = tr("Wartet auf den nächsten Raid") + (tr(" (pausiert)") if snap.get("status") == "paused" else "")
    state = tr("Versuche {attempts} · Wellen {waves}", attempts=snap.get("session_attempts", 0),
                   waves=snap.get("session_waves", 0))
    if snap.get("best_wave"):
        state += " · " + tr("Bestwelle {wave}", wave=snap["best_wave"])
    activity = {"details": details[:128], "state": state[:128]}
    if icon_url:
        activity["large_image"] = icon_url
        activity["large_text"] = (f"{GAME_NAME} · {profile}" if profile else GAME_NAME)[:128]
    if snap.get("started_unix"):
        activity["start"] = int(snap["started_unix"])
    return activity


def explain_error(exc: BaseException) -> str:
    name = exc.__class__.__name__
    if isinstance(exc, ImportError):
        return tr("Das Paket „pypresence“ fehlt in dieser Programmversion.")
    if name == "DiscordNotFound":
        return tr("Die Discord-Desktop-App wurde nicht gefunden – bitte Discord am PC starten (nicht im Browser).")
    if name in ("InvalidID", "InvalidPipe"):
        return tr("Discord akzeptiert die Anwendungs-ID nicht.")
    return tr("Verbindung zu Discord nicht möglich ({error}).", error=name)


class PresenceUpdater(threading.Thread):
    def __init__(self, get_settings: Callable[[], Settings], get_snapshot: Callable[[], dict],
                 factory: Optional[Callable[[str], object]] = None,
                 icon_fetcher: Callable[[int], Optional[str]] = fetch_icon_url) -> None:
        super().__init__(name="presence", daemon=True)
        self._get, self._snapshot = get_settings, get_snapshot
        self._factory, self._icon_fetcher = factory, icon_fetcher
        self._halt, self._poke = threading.Event(), threading.Event()
        self._rpc = None
        self._last: Optional[dict] = None
        self._last_update_at = -1e9
        self._next_try = 0.0
        self._icon: tuple[Optional[int], Optional[str], float] = (None, None, -1e9)
        self.status_text = tr("Aus")
        self.status_ok = False

    def stop(self) -> None:
        self._halt.set()
        self._poke.set()

    def poke(self) -> None:
        """Einstellungen haben sich geändert: sofort neu prüfen (statt bis zu 15 s zu warten)."""
        self._poke.set()

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
            for method in ("clear", "close"):
                try:
                    getattr(rpc, method)()
                except Exception:
                    pass

    def _icon_url(self, settings: Settings, now: float) -> Optional[str]:
        game_id = parse_game_id(settings.rpc_game_link)
        if game_id is None:
            return None
        cached_id, url, at = self._icon
        if cached_id == game_id and (now - at) < (ICON_TTL if url else ICON_RETRY):
            return url
        url = load_cached_icon(game_id) or self._icon_fetcher(game_id)
        if url:
            save_cached_icon(game_id, url)
        self._icon = (game_id, url, now)
        return url

    def run(self) -> None:
        while not self._halt.is_set():
            self._poke.wait(INTERVAL)
            self._poke.clear()
            if self._halt.is_set():
                break
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
        if not s.rpc_enabled:
            self._drop()
            self.status_text, self.status_ok = tr("Aus"), False
            return
        if not cid:
            self._drop()
            self.status_text, self.status_ok = tr("Bitte unten deine eigene Discord-Anwendungs-ID eintragen."), False
            return
        snap = self._snapshot()
        activity = build_activity(s, snap, self._icon_url(s, now) if snap.get("status") != "stopped" else None)
        if activity is None:
            self._drop()
            self.status_text, self.status_ok = tr("Bereit – wird angezeigt, sobald die Überwachung läuft."), True
            return
        if self._rpc is None:
            if now < self._next_try:
                return
            try:
                self._rpc = self._connect(cid)
                log.info("Discord-Profilstatus verbunden.")
            except Exception as exc:
                self._next_try = now + RETRY
                self.status_text, self.status_ok = explain_error(exc), False
                log.info("Discord-Profilstatus nicht möglich: %s", exc.__class__.__name__)
                return
        if activity != self._last and (now - self._last_update_at) >= INTERVAL - 0.5:
            try:
                self._rpc.update(**activity)
                self._last, self._last_update_at = activity, now
            except Exception as exc:
                self.status_text, self.status_ok = explain_error(exc), False
                log.info("Discord-Profilstatus getrennt: %s", exc.__class__.__name__)
                self._drop()
                return
        self.status_text, self.status_ok = tr("Verbunden ✓ – wird in deinem Discord-Profil angezeigt."), True
