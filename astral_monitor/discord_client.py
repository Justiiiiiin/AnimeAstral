"""Discord-Webhook-Versand in eigenem Thread (blockiert nie die Erkennung)."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Callable, Optional

import requests

from .settings import Settings

log = logging.getLogger("discord")


class DiscordSender(threading.Thread):
    def __init__(self, get_settings: Callable[[], Settings]) -> None:
        super().__init__(name="discord", daemon=True)
        self._get = get_settings
        self._queue: "queue.Queue[Optional[tuple]]" = queue.Queue(maxsize=100)

    def submit(self, payload: dict, files: Optional[list] = None,
               on_done: Optional[Callable[[], None]] = None) -> None:
        try:
            self._queue.put_nowait((payload, files or [], on_done))
        except queue.Full:
            log.warning("Discord-Warteschlange voll – Meldung verworfen.")

    def stop(self) -> None:
        self._queue.put(None)

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            payload, files, on_done = item
            ok, info = self.send_now(payload, files)
            if not ok:
                log.error("Discord-Meldung fehlgeschlagen: %s", info)
            if on_done is not None:
                try:
                    on_done()
                except Exception:
                    log.exception("Rückruf nach dem Senden fehlgeschlagen")

    def send_now(self, payload: dict, files: Optional[list] = None, retries: int = 3) -> tuple[bool, str]:
        url = self._get().webhook_url
        message = "Unbekannter Fehler"
        for attempt in range(1, retries + 1):
            try:
                if files:
                    multipart = {f"files[{i}]": (name, data, ctype)
                                 for i, (name, data, ctype) in enumerate(files)}
                    resp = requests.post(url, data={"payload_json": json.dumps(payload)},
                                         files=multipart, timeout=30)
                else:
                    resp = requests.post(url, json=payload, timeout=15)
                if resp.status_code in (200, 204):
                    return True, "OK"
                if resp.status_code == 429:                 # Rate-Limit
                    try:
                        wait = float(resp.json().get("retry_after", 2))
                    except ValueError:
                        wait = 2.0
                    time.sleep(min(wait, 30))
                    message = "Rate-Limit"
                    continue
                message = f"HTTP {resp.status_code}: {resp.text[:150]}"
                if 400 <= resp.status_code < 500:           # falsche URL o. Ä.: nicht wiederholen
                    return False, message
            except requests.RequestException as exc:
                message = str(exc)
            time.sleep(2 * attempt)
        return False, message
