"""Live-Statusnachricht: EINE Discord-Nachricht, die sich selbst aktualisiert (Bearbeiten statt neu senden).

Per Knopf/Hotkey kann sie gelöscht und ganz unten im Chat neu gesendet werden."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Callable, Optional

import requests

from . import app_paths, messages
from .settings import Settings, is_valid_webhook

log = logging.getLogger("status")

MIN_GAP = 5.0       # Sekunden zwischen zwei Sendungen (Discord-Limits schonen)


class StatusPublisher(threading.Thread):
    def __init__(self, get_settings: Callable[[], Settings], get_snapshot: Callable[[], dict]) -> None:
        super().__init__(name="status", daemon=True)
        self._get = get_settings
        self._snapshot = get_snapshot
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._halt = False
        self._resend = False
        self._resend_at = 0.0
        self._dirty = False
        self._final = False
        self._last_sent = 0.0
        self._state_file = app_paths.data_dir() / "status_message.json"

    # ------------------------------------------------------------------ Aufrufe von außen
    def request_update(self) -> None:
        with self._lock:
            self._dirty = True
        self._wake.set()

    def request_resend(self, delay: float = 0.0) -> None:
        """Alte Nachricht löschen und neu (ganz unten) senden."""
        with self._lock:
            self._resend = True
            self._resend_at = max(self._resend_at, time.monotonic() + delay)
        self._wake.set()

    def finish(self) -> None:
        """Letzte Aktualisierung (z. B. „Gestoppt“) senden und beenden."""
        with self._lock:
            self._final, self._halt = True, True
        self._wake.set()

    def stop_now(self) -> None:
        with self._lock:
            self._halt = True
        self._wake.set()

    # ------------------------------------------------------------------ Schleife
    def run(self) -> None:
        while True:
            s = self._get()
            self._wake.wait(timeout=max(20, s.status_interval))
            self._wake.clear()
            with self._lock:
                halt, final = self._halt, self._final
                resend = self._resend and time.monotonic() >= self._resend_at
                due_resend = self._resend and not resend
            if halt and not final:
                return
            if not s.status_enabled or not is_valid_webhook(s.webhook_url):
                if halt:
                    return
                continue
            gap = time.monotonic() - self._last_sent
            if gap < MIN_GAP and not final:
                time.sleep(MIN_GAP - gap)
            if due_resend:
                self._wake.set()                      # später erneut prüfen
                time.sleep(0.5)
                continue
            try:
                self._send(s, resend=resend)
                with self._lock:
                    if resend:
                        self._resend = False
                    self._dirty = False
            except Exception:
                log.exception("Statusnachricht konnte nicht gesendet werden")
            self._last_sent = time.monotonic()
            if halt:
                return

    # ------------------------------------------------------------------ Senden
    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    def _load_id(self, url: str) -> Optional[str]:
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            return data.get("id") if data.get("key") == self._key(url) else None
        except (OSError, ValueError):
            return None

    def _save_id(self, url: str, message_id: Optional[str]) -> None:
        try:
            if message_id:
                self._state_file.write_text(json.dumps({"key": self._key(url), "id": message_id}), encoding="utf-8")
            else:
                self._state_file.unlink(missing_ok=True)
        except OSError:
            log.debug("Status-ID konnte nicht gespeichert werden", exc_info=True)

    @staticmethod
    def _request(method: str, url: str, **kwargs):
        """HTTP mit Behandlung des Rate-Limits (einmal wiederholen)."""
        for _attempt in range(2):
            resp = requests.request(method, url, timeout=15, **kwargs)
            if resp.status_code != 429:
                return resp
            try:
                wait = float(resp.json().get("retry_after", 2))
            except ValueError:
                wait = 2.0
            time.sleep(min(wait, 20))
        return resp

    def _send(self, s: Settings, resend: bool) -> None:
        url = s.webhook_url.rstrip("/")
        payload = messages.build_status(s, self._snapshot())
        edit_payload = {k: v for k, v in payload.items() if k not in ("username", "avatar_url")}
        message_id = self._load_id(url)

        if resend and message_id:
            resp = self._request("DELETE", f"{url}/messages/{message_id}")
            if resp.status_code not in (200, 204, 404):
                log.warning("Alte Statusnachricht konnte nicht gelöscht werden (HTTP %s)", resp.status_code)
            message_id = None
            self._save_id(url, None)

        if message_id:
            resp = self._request("PATCH", f"{url}/messages/{message_id}", json=edit_payload)
            if resp.status_code in (200, 204):
                return
            if resp.status_code != 404:                # 404 = Nachricht wurde gelöscht -> neu anlegen
                log.warning("Statusnachricht bearbeiten fehlgeschlagen (HTTP %s)", resp.status_code)
                return
            self._save_id(url, None)

        resp = self._request("POST", f"{url}?wait=true", json=payload)
        if resp.status_code in (200, 204):
            try:
                self._save_id(url, str(resp.json()["id"]))
            except (ValueError, KeyError):
                log.warning("Antwort ohne Nachrichten-ID – Bearbeiten nicht möglich")
        else:
            log.warning("Statusnachricht senden fehlgeschlagen (HTTP %s)", resp.status_code)
