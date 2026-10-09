"""Search in the settings (without Qt): ignores case, umlauts, hyphens and small typos – “wachter” finds
“Wächter”, “antiafk” finds “Anti-AFK”, “hotkey” finds “Hotkeys”, “discrod” finds “Discord”. Every search word must
occur (AND)."""
from __future__ import annotations

import difflib
import re

_UMLAUTS = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e", "è": "e"})


def normalize(text: str) -> str:
    """Lower case, umlauts without dots, only letters/digits and spaces."""
    text = text.casefold().translate(_UMLAUTS)
    text = text.replace("ae", "a").replace("oe", "o").replace("ue", "u")      # “Waechter” = “Wächter”
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text)).strip()


class Haystack:
    """Prepared search text of a card: the whole text (without spaces for “antiafk”) and single words."""

    def __init__(self, text: str) -> None:
        self.text = normalize(text)
        self.joined = self.text.replace(" ", "")
        self.words = set(self.text.split())


def word_matches(word: str, hay: Haystack) -> bool:
    if word in hay.text or word in hay.joined:
        return True
    if len(word) < 4:
        return False
    cutoff = 0.8 if len(word) < 7 else 0.75               # one swapped/missing letter
    return any(difflib.SequenceMatcher(None, word, w[:len(word) + 2]).ratio() >= cutoff
               for w in hay.words if abs(len(w) - len(word)) <= 3 or w.startswith(word[:3]))


def matches(query: str, hay: Haystack) -> bool:
    words = normalize(query).split()
    return bool(words) and all(word_matches(w, hay) for w in words)
