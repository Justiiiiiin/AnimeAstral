"""Welcher Raid läuft? (ohne Qt, Wunsch des Eigentümers 08.10.2026) – unabhängig von der Kamera:

1. **Raid-Fenster mitlesen:** Bevor man einem Raid beitritt (selbst oder per Makro), ist das Raid-Fenster offen, der
   Name steht groß in Rot/Orange unter dem Banner („Holy Grail War“). Die Überwachung schaut alle paar Sekunden, ob so
   ein Fenster offen ist, und merkt sich den Namen. Beginnt danach ein neuer Lauf – und war der Wellenzähler
   zwischendurch weg (Teleport) –, gehört er zu diesem Raid. Nur angeschaut und im selben Raid geblieben (Auto Retry)
   zählt nicht.
2. (geplant) **Drops:** eindeutige Drops je Raid aus den „Enemy Drops“-Listen (lernt das Erkunden) – für Auto-Join
   wie MaxTac Call, wo es kein Raid-Fenster gibt.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Optional

import numpy as np

from . import vision

log = logging.getLogger("raid")

RAID_TITLES = ("raid", "boss rush", "defense mode", "tower")   # Banner-Titel von Fenstern mit Create/Join
SEEN_TWICE = 2          # gleicher Name so oft gelesen = sicher (Lesefehler erzeugen sonst falsche Raids)
VALID_FOR = 300.0       # so lange nach dem Fenster darf der Lauf beginnen (Lobby, Countdown)
ABSENT_MIN = 2.0        # so lange muss der Wellenzähler dazwischen weg gewesen sein (Teleport in den Raid)


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def match_name(read: str, known: list[str]) -> Optional[str]:
    """Gelesenen Namen einem bekannten Raid zuordnen (Lesefehler: „Het Grail War“ ≈ „Holy Grail War“)."""
    key = norm(read)
    if not key:
        return None
    best, score = None, 0.0
    for name in known:
        k = norm(name)
        s = 1.0 if k == key else difflib.SequenceMatcher(None, key, k).ratio()
        if s > score:
            best, score = name, s
    return best if score >= 0.8 else None


class RaidSense:
    def __init__(self) -> None:
        self.pending: Optional[str] = None                 # zuletzt sicher gelesener Raid-Name
        self.pending_ts = 0.0
        self._candidate: Optional[str] = None
        self._count = 0
        self._absent_since: Optional[float] = None
        self._teleported = False                          # Zähler war nach dem Fenster lange genug weg

    # ------------------------------------------------------------------ 1. Raid-Fenster
    def seen_name(self, name: str, known: list[str], now: float) -> None:
        """Name aus einem offenen Raid-Fenster (bereits gelesen). Bekannte Raids werden zugeordnet."""
        name = match_name(name, known) or name.strip()
        if not norm(name):
            return
        if self._candidate and (norm(self._candidate) == norm(name) or difflib.SequenceMatcher(
                None, norm(self._candidate), norm(name)).ratio() >= 0.85):
            self._count += 1                              # kleine Lesefehler zählen als derselbe Name –
            if name not in known:                         # bekannter Name gewinnt, sonst die erste Lesung
                name = self._candidate
        else:
            self._candidate, self._count = name, 1
        if self._count >= SEEN_TWICE and (self.pending != name or now - self.pending_ts > 5):
            if self.pending != name:
                log.info("Raid-Fenster: %s", name)
            self.pending, self.pending_ts, self._teleported = name, now, False

    def wave_visible(self, visible: bool, now: float) -> None:
        """Vom Wellenzähler: ist er weg (Teleport/Lobby), darf der nächste Lauf dem gelesenen Raid gehören."""
        if visible:
            if self._absent_since is not None and now - self._absent_since >= ABSENT_MIN \
                    and self.pending and now > self.pending_ts:
                self._teleported = True                   # Zähler kam nach dem Raid-Fenster (wieder) ins Bild
            self._absent_since = None
        elif self._absent_since is None:
            self._absent_since = now

    def take(self, now: float) -> Optional[str]:
        """Beim Beginn eines neuen Laufs: Raid-Name, falls ein Raid-Fenster kurz vorher offen war und man seither
        teleportiert ist – sonst None (z. B. nur angeschaut, Auto Retry im selben Raid)."""
        if not self.pending or now - self.pending_ts > VALID_FOR:
            return None
        if not (self._teleported or self._absent_since is not None):
            return None
        name, self.pending = self.pending, None
        self._candidate, self._count, self._teleported = None, 0, False
        return name


def read_raid_window(frame: np.ndarray, menu: "vision.MenuFrame", ocr) -> Optional[str]:
    """Ist ein Raid-Fenster offen? Dann dessen Namen (rot/orange unter dem Banner), sonst None."""
    state = menu.state(frame, ocr)
    if state is None:
        return None
    roi, title, _x = state
    t = title.lower().strip(" !")
    if not any(t.startswith(r) for r in RAID_TITLES):
        return None
    fh, fw = frame.shape[:2]
    crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
    name = vision.read_name_below_banner(crop, ocr) if crop.size else ""
    return name or None
