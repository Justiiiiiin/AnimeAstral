"""Discord-Webhook-Versand in eigenem Thread (blockiert nie die Erkennung)."""
from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
from datetime import date
from typing import Callable, Optional

import requests

from . import app_paths
from .i18n import tr
from .settings import Settings, is_valid_webhook

log = logging.getLogger("discord")


def _hook_id(url: str) -> str:
    """Kurzer Fingerabdruck des Webhooks (anderer Webhook = neuer Beitrag), ohne die URL selbst zu speichern."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


class DiscordSender(threading.Thread):
    def __init__(self, get_settings: Callable[[], Settings]) -> None:
        super().__init__(name="discord", daemon=True)
        self._get = get_settings
        self._queue: "queue.Queue[Optional[tuple]]" = queue.Queue(maxsize=100)

    def submit(self, payload: dict, files: Optional[list] = None,
               on_done: Optional[Callable[[], None]] = None, daily: bool = False) -> None:
        """daily=True: mit Forum-Webhook in den Beitrag des Tages (sonst wie immer in den Hauptkanal)."""
        try:
            self._queue.put_nowait((payload, files or [], on_done, daily))
        except queue.Full:
            log.warning("Discord-Warteschlange voll – Meldung verworfen.")

    def stop(self) -> None:
        self._queue.put(None)

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            payload, files, on_done, daily = item
            if daily and is_valid_webhook(self._get().forum_webhook_url):
                ok, info = self.send_daily(payload, files)
            else:
                ok, info = self.send_now(payload, files)
            if not ok:
                log.error("Discord-Meldung fehlgeschlagen: %s", info)
            if on_done is not None:
                try:
                    on_done()
                except Exception:
                    log.exception("Rückruf nach dem Senden fehlgeschlagen")

    # ------------------------------------------------------------ Forum: ein Beitrag pro Tag
    @staticmethod
    def _thread_file():
        return app_paths.data_dir() / "forum_thread.json"

    def _today_thread(self, url: str) -> Optional[str]:
        try:
            data = json.loads(self._thread_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        same = data.get("day") == date.today().isoformat() and data.get("hook") == _hook_id(url)
        return str(data["id"]) if same and data.get("id") else None

    def send_daily(self, payload: dict, files: Optional[list] = None) -> tuple[bool, str]:
        """Erste Meldung des Tages eröffnet einen Forum-Beitrag „Raids · TT.MM.JJJJ“, alle weiteren landen darin.
        Wurde der Beitrag gelöscht, wird ein neuer angelegt."""
        url = self._get().forum_webhook_url.rstrip("/")
        thread = self._today_thread(url)
        if thread:
            ok, info, _data = self._post(f"{url}?thread_id={thread}", payload, files)
            if ok or not info.startswith(("HTTP 404", "HTTP 400")):
                return ok, info
            log.info("Forum-Beitrag des Tages nicht mehr verfügbar (%s) – lege neuen an.", info)
        day = date.today()
        payload = dict(payload, thread_name=tr("Raids · {date}", date=day.strftime("%d.%m.%Y")))
        ok, info, data = self._post(f"{url}?wait=true", payload, files)
        if ok and isinstance(data, dict) and data.get("channel_id"):
            try:
                self._thread_file().write_text(json.dumps({"day": day.isoformat(), "id": str(data["channel_id"]),
                                                           "hook": _hook_id(url)}), encoding="utf-8")
            except OSError:
                log.warning("Forum-Beitrag konnte nicht gemerkt werden.")
        return ok, info

    def send_now(self, payload: dict, files: Optional[list] = None, retries: int = 3) -> tuple[bool, str]:
        ok, info, _data = self._post(self._get().webhook_url, payload, files, retries)
        return ok, info

    def _post(self, url: str, payload: dict, files: Optional[list] = None,
              retries: int = 3) -> tuple[bool, str, Optional[dict]]:
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
                    try:
                        data = resp.json() if resp.status_code == 200 else None
                    except ValueError:
                        data = None
                    return True, "OK", data
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
                    return False, message, None
            except requests.RequestException as exc:
                message = str(exc)
            time.sleep(2 * attempt)
        return False, message, None
