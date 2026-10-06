"""Privatem Server beitreten, ohne Browser: aus dem Link Spielnummer und Code lesen und den Roblox-Client über seinen
eigenen Protokoll-Link starten (roblox://…). Der Client nutzt seine gespeicherte Anmeldung – das Programm braucht
weder Passwort noch Cookie. Unterstützt wird das klassische Format
    https://www.roblox.com/games/<Spielnummer>/<Name>?privateServerLinkCode=<Code>
(Teilen-Links „roblox.com/share?code=…“ lassen sich ohne Anmeldung nicht auflösen: einmal im Browser öffnen, dann
steht der klassische Link in der Adresszeile)."""
from __future__ import annotations

import os
import re
import sys
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .i18n import tr

_PLACE_RE = re.compile(r"/games/(\d{3,20})(?:/|$)")
_CODE_RE = re.compile(r"[A-Za-z0-9_-]{6,100}")
DEEP_LINK = "roblox://experiences/start?placeId={place}&linkCode={code}"


def parse_private_link(text: str) -> Optional[tuple[int, str]]:
    """(Spielnummer, Code) aus einem Private-Server-Link; None = kein passender Link."""
    text = (text or "").strip()
    if not text:
        return None
    url = urlparse(text if "://" in text else "https://" + text)
    if not url.netloc.lower().endswith("roblox.com"):
        return None
    place = _PLACE_RE.search(url.path)
    code = (parse_qs(url.query).get("privateServerLinkCode") or [""])[0]
    if not place or not _CODE_RE.fullmatch(code):
        return None
    return int(place.group(1)), code


def explain(text: str) -> str:
    """Kurze Rückmeldung zum eingetragenen Link (für die Einstellungen)."""
    if not (text or "").strip():
        return tr("Kein Link eingetragen.")
    if "share?" in text and "privateServerLinkCode" not in text:
        return tr("Teilen-Link erkannt – bitte einmal im Browser öffnen und dann den Link aus der Adresszeile "
                  "kopieren (enthält „privateServerLinkCode“).")
    parsed = parse_private_link(text)
    if parsed is None:
        return tr("Kein gültiger Private-Server-Link (erwartet: roblox.com/games/…?privateServerLinkCode=…).")
    return tr("Spiel {place} · Code …{tail}", place=parsed[0], tail=parsed[1][-6:])


def join(text: str) -> tuple[bool, str]:
    """Startet den Roblox-Client direkt im privaten Server. Rückgabe (gestartet?, Meldung)."""
    parsed = parse_private_link(text)
    if parsed is None:
        return False, explain(text)
    uri = DEEP_LINK.format(place=parsed[0], code=parsed[1])
    if sys.platform != "win32":
        return False, tr("Nur unter Windows möglich.")
    try:
        os.startfile(uri)                              # öffnet den registrierten Roblox-Client
    except OSError as exc:
        return False, tr("Roblox konnte nicht gestartet werden ({error}). Ist Roblox installiert?", error=exc)
    return True, tr("Roblox wird gestartet und tritt dem privaten Server bei …")
