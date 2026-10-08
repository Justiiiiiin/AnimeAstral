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


# ---------------------------------------------------------------------- 2. Drops (Feld links über der Leiste unten)
DROP_REGION = [0.0, 0.30, 0.85, 0.86]   # Drop-Kacheln (bis zu 4 Zeilen) über den Knöpfen unten links
DROP_SCALE = 3                          # Beschriftungen sind winzig: vergrößert lesen
DROP_HIT = 0.8                          # unscharfer Vergleich (Lesefehler „Sreet Cred“)
DROP_CONFIRM = 2                        # so oft hintereinander vorne = Raid übernehmen


def _partial(name: str, text: str) -> float:
    """Wie gut kommt name (normalisiert) irgendwo in text vor? 0..1 (Fenster gleicher Länge, difflib)."""
    if not name or len(text) < len(name) - 2:
        return 0.0
    if name in text:
        return 1.0
    n = len(name)
    best = 0.0
    for i in range(0, max(1, len(text) - n + 1)):
        r = difflib.SequenceMatcher(None, name, text[i:i + n]).ratio()
        if r > best:
            best = r
            if best >= 0.95:
                break
    return best


class DropIndex:
    """Welche Drops gibt es nur in genau einem Raid? (aus den „Enemy Drops“-Listen, die das Erkunden liest)"""

    def __init__(self, drops_by_raid: dict[str, list[str]]) -> None:
        owners: dict[str, set[str]] = {}
        for raid, drops in drops_by_raid.items():
            for d in drops:
                key = norm(d)
                if len(key) >= 5:
                    owners.setdefault(key, set()).add(raid)
        self.unique = {key: next(iter(r)) for key, r in owners.items() if len(r) == 1}

    @classmethod
    def from_map(cls, umap) -> "DropIndex":
        table: dict[str, list[str]] = {}
        for e in umap.entries:
            extra = e.get("extra") or {}
            if extra.get("drops") and extra.get("raid_name"):
                table.setdefault(extra["raid_name"], []).extend(extra["drops"])
        return cls(table)

    def votes(self, words: list[str]) -> dict[str, int]:
        """Treffer je Raid für die gelesenen Wörter des Drop-Felds (nur eindeutige Drops zählen)."""
        text = norm(" ".join(words))
        out: dict[str, int] = {}
        for key, raid in self.unique.items():
            if _partial(key, text) >= DROP_HIT:
                out[raid] = out.get(raid, 0) + 1
        return out


class DropWatcher:
    """Entscheidet über mehrere Lesungen: derselbe Raid DROP_CONFIRM-mal hintereinander klar vorne -> Raid."""

    def __init__(self) -> None:
        self._leader: Optional[str] = None
        self._streak = 0

    def feed(self, votes: dict[str, int]) -> Optional[str]:
        if not votes:
            return None
        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        leader, score = ranked[0]
        if len(ranked) > 1 and ranked[1][1] >= score:
            self._leader, self._streak = None, 0          # Gleichstand: nichts sagen
            return None
        if leader == self._leader:
            self._streak += 1
        else:
            self._leader, self._streak = leader, 1
        return leader if self._streak >= DROP_CONFIRM else None

    def reset(self) -> None:
        self._leader, self._streak = None, 0


def read_drop_words(frame: np.ndarray, ocr) -> list[str]:
    """Wörter im Drop-Feld (vergrößert gelesen; ~250 ms – darum nur selten aufrufen)."""
    import cv2
    fh, fw = frame.shape[:2]
    x0, y0, x1, y1 = DROP_REGION
    crop = frame[int(y0 * fh):int(y1 * fh), int(x0 * fw):int(x1 * fw)]
    if crop.size == 0:
        return []
    f = max(1.5, min(DROP_SCALE, DROP_SCALE * 1280 / fw))     # großes Fenster: weniger vergrößern (Rechenzeit)
    big = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return [w for w, _b in vision.words_in(big, [0.0, 0.0, 1.0, 1.0], ocr)
            if len(re.sub(r"[^A-Za-z]", "", w)) >= 3]
