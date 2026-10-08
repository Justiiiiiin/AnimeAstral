"""Eingebautes Spielwissen für das Erkunden (ohne Qt): Fenster anhand von Titel und gelesenen Wörtern einordnen
und Knöpfe benennen. Abgeleitet aus echten Aufnahmen des Eigentümers (07.10.2026):

- Gacha (z. B. Doujutsu, Races, Hakis, Family): „Roll“, „Auto Roll“, „Current:“, „Buffs:“, „Cost:“, Pity-Leiste.
  Höchstens 2 Gachas gleichzeitig aktiv (für das Programm egal).
- Titans: wie Gacha (Roll/Auto Roll/Pity), aber eigenes System – Seltenheiten statt Buffs.
- Pets: Roll-Menü mit „Open!“, „Auto!“, „Mythical Pity“ (Vorlage „Pets-Roll“).
- Crafting: „Craft“, „You will lose the selected Pets …“, „Shiny“.
- Upgrade Tree: ganzer Bildschirm, „Total Stats:“, „Leveling Token“, roter „Close“-Knopf.
- Artefakt (z. B. Elixir of Life): ganzer Bildschirm, „fragments“, „artifact“, „Boosts“, „Progress Level“, „Exit“.
- Auto-Roll läuft im Hintergrund weiter: Fenster nach „Auto“ sofort schließen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .i18n import N_, tr

# Kategorie -> (Anzeige, Titel-Wörter, Text-Wörter, Gewicht je Treffer); Wörter klein, ohne Satzzeichen
CATEGORIES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "pets": (N_("Pets (Roll-Menü)"), ("pets",), ("pity", "open", "auto", "mythical")),
    "titans": (N_("Titans"), ("titan", "titans"), ("titan", "rare", "epic", "legendary", "secret")),
    "gacha": (N_("Gacha"), (), ("roll", "autoroll", "current", "buffs", "cost", "pity")),
    "crafting": (N_("Crafting"), ("crafting", "craft"), ("craft", "lose", "selected", "shiny")),
    "upgrade_tree": (N_("Upgrade Tree"), ("tree",), ("total", "stats", "leveling", "token", "close")),
    "artefact": (N_("Artefakt"), ("elixir", "artifact", "artefact"), ("artifact", "artefact", "fragments", "elixir",
                                                                      "progress", "boosts", "exit")),
    "upgrades": (N_("Upgrades"), ("upgrade", "upgrades"), ("upgrade", "max", "level", "lv")),
    "progression": (N_("Progression"), ("progression",), ("progression", "rank", "next")),
    "shop": (N_("Shop / Händler"), ("shop", "merchant"), ("buy", "stock", "restock", "shop", "merchant")),
    "battlepass": (N_("Battlepass"), ("battlepass", "pass"), ("battlepass", "tier", "premium", "free")),
    "raid": (N_("Raid"), ("raid",), ("raid", "start", "difficulty", "create", "join", "enter")),
    "defense": (N_("Defense"), ("defense",), ("defense", "mode", "wave", "start")),
    "exchange": (N_("Tausch"), ("exchange",), ("exchange", "trade", "token")),
    "passive": (N_("Passiv"), ("passive", "passives"), ("passive", "reroll", "lock")),
    "equip_best": (N_("Equip Best"), ("equip",), ("equip", "best", "power", "damage", "yen", "luck", "drop")),
    "guild": (N_("Gilde"), ("guild",), ("guild", "members", "claim", "rewards", "quests", "donate")),
    # aus dem ersten echten Erkunden (07.10.2026): Knöpfe am Bildschirmrand und weitere Welt-Symbole
    "quests": (N_("Quests"), ("quests", "quest"), ("claim", "complete", "times", "quests")),
    "promotion": (N_("Promotion"), ("promotion", "promotions"), ("promote", "promotion", "missions", "boost")),
    "inventory": (N_("Inventar"), ("inventory",), ("rarity", "key", "inventory", "items")),
    "achievements": (N_("Achievements"), ("achievements", "achievement"), ("claim", "achievements", "veteran")),
    "index": (N_("Index"), ("index",), ("worlds", "collections", "index", "complete")),
    "ranks": (N_("Ranks"), ("ranks", "rank"), ("rank", "max", "auto")),
    "avatars": (N_("Avatare"), ("avatars", "avatar"), ("avatar", "equip")),
    "event": (N_("Event"), ("event", "medal"), ("event", "medal")),
}

# Knöpfe, die beim Erkunden nur gemerkt, nie geklickt werden (kosten etwas oder ändern den Spielstand)
ACTION_WORDS = ("roll", "auto", "craft", "buy", "claim", "equip", "upgrade", "open", "sell", "delete", "confirm",
                "yes", "use", "donate", "start", "create", "join", "enter", "trade", "exchange", "reroll", "max")
CLOSE_WORDS = ("close", "exit")


@dataclass
class Analysis:
    category: str = "unknown"
    label: str = ""
    score: float = 0.0
    matched: list[str] = field(default_factory=list)
    buttons: list[tuple[str, list[float]]] = field(default_factory=list)   # (Wort, Lage im Roblox-Fenster)
    title: str = ""

    def as_dict(self) -> dict:
        return {"category": self.category, "label": self.label, "score": round(self.score, 2),
                "matched": self.matched, "buttons": [{"text": t, "roi": [round(v, 4) for v in r]}
                                                     for t, r in self.buttons], "title": self.title}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def classify(title: str, words: list[tuple[str, list[float]]], template: str = "") -> Analysis:
    """Fenster einordnen. words = (Wort, Lage) aus der Texterkennung; template = Name einer erkannten Vorlage."""
    tokens = [_norm(w) for w, _r in words if _norm(w)]
    joined = " ".join(tokens)
    if "auto" in tokens and "roll" in tokens:
        tokens.append("autoroll")
    title_tokens = {_norm(t) for t in re.split(r"\s+", title) if _norm(t)}
    best = Analysis(title=title)
    if template and "pets" in template.lower():
        best = Analysis("pets", tr(CATEGORIES["pets"][0]), 10.0, ["template"], title=title)
    else:
        for key, (label, title_words, text_words) in CATEGORIES.items():
            hit_title = [w for w in title_words if any(w in t for t in title_tokens)]
            hit_text = sorted({w for w in text_words if w in tokens or (len(w) > 4 and w in joined)})
            score = 6.0 * len(hit_title) + len(hit_text)       # der Titel zählt viel mehr als Wörter im Fenster
            if key in ("equip_best", "guild") and not hit_title:
                continue                                  # nur mit passendem Titel (Shops zeigen auch Power, Yen …)
            if key == "titans" and "buffs" in tokens:
                score -= 2                                 # Gachas haben Buffs, Titans nicht
            if key == "gacha" and ("titan" in joined or "pets" in title_tokens):
                score -= 3
            if score > best.score:
                best = Analysis(key, tr(label), score, hit_title + hit_text, title=title)
        if best.score < 2.0:
            best = Analysis("unknown", tr("Unbekannt"), best.score, best.matched, title=title)
    best.buttons = [(w, r) for w, r in words if _norm(w) in ACTION_WORDS or _norm(w) in CLOSE_WORDS]
    return best


def claimables(words: list[tuple[str, list[float]]]) -> list[list[float]]:
    """Lagen aller „Claim“-Knöpfe (Quests, Achievements, Gilde) – nur gemerkt, nie geklickt."""
    return [r for w, r in words if _norm(w) == "claim"]


def close_word(words: list[tuple[str, list[float]]]) -> list[float] | None:
    """Lage eines „Close“/„Exit“-Knopfs (ganze Bildschirme ohne rosa X), sonst None."""
    hits = [r for w, r in words if _norm(w) in CLOSE_WORDS]
    return max(hits, key=lambda r: r[1]) if hits else None     # der unterste (Knöpfe sitzen unten)


def is_safe_to_click(word: str) -> bool:
    """Beim Erkunden nie auf Aktions-Knöpfe klicken (Roll, Craft, Buy, Claim …)."""
    return _norm(word) not in ACTION_WORDS
