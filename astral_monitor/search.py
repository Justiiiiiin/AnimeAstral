"""Suche in den Einstellungen (ohne Qt): unempfindlich gegen Groß-/Kleinschreibung, Umlaute, Bindestriche und kleine
Tippfehler – „wachter“ findet „Wächter“, „antiafk“ findet „Anti-AFK“, „hotkey“ findet „Hotkeys“, „discrod“ findet
„Discord“. Jedes Suchwort muss vorkommen (UND)."""
from __future__ import annotations

import difflib
import re

_UMLAUTS = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e", "è": "e"})


def normalize(text: str) -> str:
    """Kleinbuchstaben, Umlaute ohne Punkte, nur Buchstaben/Ziffern und Leerzeichen."""
    text = text.casefold().translate(_UMLAUTS)
    text = text.replace("ae", "a").replace("oe", "o").replace("ue", "u")      # „Waechter“ = „Wächter“
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text)).strip()


class Haystack:
    """Vorbereiteter Suchtext einer Karte: ganzer Text (ohne Leerzeichen für „antiafk“) und einzelne Wörter."""

    def __init__(self, text: str) -> None:
        self.text = normalize(text)
        self.joined = self.text.replace(" ", "")
        self.words = set(self.text.split())


def word_matches(word: str, hay: Haystack) -> bool:
    if word in hay.text or word in hay.joined:
        return True
    if len(word) < 4:
        return False
    cutoff = 0.8 if len(word) < 7 else 0.75               # ein vertauschter/fehlender Buchstabe
    return any(difflib.SequenceMatcher(None, word, w[:len(word) + 2]).ratio() >= cutoff
               for w in hay.words if abs(len(w) - len(word)) <= 3 or w.startswith(word[:3]))


def matches(query: str, hay: Haystack) -> bool:
    words = normalize(query).split()
    return bool(words) and all(word_matches(w, hay) for w in words)
