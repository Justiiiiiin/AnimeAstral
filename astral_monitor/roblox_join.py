"""Privatem Server beitreten, ohne Browser: aus dem Link Spielnummer und Code lesen und den Roblox-Client über seinen
eigenen Protokoll-Link starten (roblox://…). Der Client nutzt seine gespeicherte Anmeldung – das Programm braucht
weder Passwort noch Cookie. Unterstützte Links:
    https://www.roblox.com/share?code=<Code>&type=Server        (Teilen-Link, auch /share-links?…)
        -> roblox://navigation/share_links?code=<Code>&type=Server   (so steht er in Roblox' eigenem Link)
    https://www.roblox.com/games/<Spielnummer>/<Name>?privateServerLinkCode=<Code>
        -> roblox://experiences/start?placeId=<Spielnummer>&linkCode=<Code>"""
from __future__ import annotations

import os
import re
import sys
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .i18n import tr

_PLACE_RE = re.compile(r"/games/(\d{3,20})(?:/|$)")
_CODE_RE = re.compile(r"[A-Za-z0-9_-]{6,100}")
_SHARE_RE = re.compile(r"[A-Fa-f0-9]{16,64}")
DEEP_LINK = "roblox://experiences/start?placeId={place}&linkCode={code}"
SHARE_DEEP_LINK = "roblox://navigation/share_links?code={code}&type=Server"     # so steht er auch in Roblox' Teilen-Link


def _url(text: str):
    text = (text or "").strip().strip("﻿​\"'<>").strip()   # BOM, Null-Breite, Anführungszeichen beim Kopieren
    if not text:
        return None
    url = urlparse(text if "://" in text else "https://" + text)
    host = url.netloc.lower().split("@")[-1].split(":")[0]
    return url if host == "roblox.com" or host.endswith(".roblox.com") else None


def parse_private_link(text: str) -> Optional[tuple[int, str]]:
    """(Spielnummer, Code) aus einem klassischen Private-Server-Link; None = kein passender Link."""
    url = _url(text)
    if url is None:
        return None
    place = _PLACE_RE.search(url.path)
    code = (parse_qs(url.query).get("privateServerLinkCode") or [""])[0]
    if not place or not _CODE_RE.fullmatch(code):
        return None
    return int(place.group(1)), code


def parse_share_link(text: str) -> Optional[str]:
    """Code aus einem Teilen-Link (roblox.com/share?… oder /share-links?…, type=Server); None = keiner."""
    url = _url(text)
    if url is None or not url.path.rstrip("/").endswith(("/share", "/share-links")):
        return None
    query = parse_qs(url.query)
    code = (query.get("code") or [""])[0]
    if (query.get("type") or [""])[0].lower() != "server" or not _SHARE_RE.fullmatch(code):
        return None
    return code


def deep_link(text: str) -> Optional[str]:
    """roblox://-Link für den Client (klassischer oder Teilen-Link); None = kein gültiger Link."""
    classic = parse_private_link(text)
    if classic:
        return DEEP_LINK.format(place=classic[0], code=classic[1])
    share = parse_share_link(text)
    return SHARE_DEEP_LINK.format(code=share) if share else None


def explain(text: str) -> str:
    """Kurze Rückmeldung zum eingetragenen Link (für die Einstellungen)."""
    if not (text or "").strip():
        return tr("No link entered.")
    parsed = parse_private_link(text)
    if parsed:
        return tr("Game {place} · code …{tail}", place=parsed[0], tail=parsed[1][-6:])
    share = parse_share_link(text)
    if share:
        return tr("Share link · code …{tail}", tail=share[-6:])
    return tr("Not a valid private server link (expected: roblox.com/share?code=…&type=Server or "
              "roblox.com/games/…?privateServerLinkCode=…).")


def join(text: str) -> tuple[bool, str]:
    """Startet den Roblox-Client direkt im privaten Server. Rückgabe (gestartet?, Meldung)."""
    uri = deep_link(text)
    if uri is None:
        return False, explain(text)
    if sys.platform != "win32":
        return False, tr("Only possible on Windows.")
    try:
        os.startfile(uri)                              # öffnet den registrierten Roblox-Client
    except OSError as exc:
        return False, tr("Roblox could not be started ({error}). Is Roblox installed?", error=exc)
    return True, tr("Starting Roblox and joining the private server …")


# ------------------------------------------------------------------ Favoriten teilen
SHARE_PREFIX = "astral-server:"


def share_code(name: str, link: str) -> str:
    """Ein Favorit als eine Zeile zum Weitergeben (Name + Link). Kein Geheimnis – wer den Code hat, kann beitreten."""
    import base64
    import json
    raw = json.dumps({"n": name, "l": link}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return SHARE_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_share_code(text: str) -> Optional[tuple[str, str]]:
    """(Name, Link) aus einem geteilten Code; None = kein gültiger Code."""
    import base64
    import binascii
    import json
    text = (text or "").strip()
    if not text.lower().startswith(SHARE_PREFIX):
        return None
    body = text[len(SHARE_PREFIX):].strip()
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    name, link = " ".join(str(data.get("n", "")).split())[:40], str(data.get("l", "")).strip()
    return (name, link) if name and deep_link(link) else None
