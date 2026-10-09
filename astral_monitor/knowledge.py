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

Nachgetragen nach dem zweiten Erkunden (Eigentümer, 08.10.2026):
- Raids/Defense/Boss Rush: der eigentliche Name steht groß in Rot/Orange unter dem Banner („Holy Grail War“).
  Manche haben Schwierigkeiten oben rechts im Fenster: W17-Raid 3 Stufen; Cursed Rush → „King of Curses Rush“ erst
  wählbar, wenn man darunter 10 Finger (aus der ersten Stufe) gesammelt hat.
- Shrines (Goddess, Otsutsuki, Demon King): Währung „opfern“ (10–100 %) für Boosts.
- Passives (Pet/Titan/Shadow Passives, Acc. Curses): je ein eigenes System, Index/Roll/Auto.
- Fixer Gigs (W21): Aufträge 20 Min./1 Std./3 Std., „Claim“ → „Send Pets“ (Pets-Fenster, letzte Pets wählen).
- Nur Anzeige, für das Makro ohne Nutzen: Spirit Contract, Chakra Training, Karma, Vessel, Celestial Keys,
  Dragon Slayer, Commandments; Renaming bleibt dem Spieler überlassen.
- Später (1.5.0): Ninja Exam, Cyberdeck/Quickhacks, Sins Upgrade Tree.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .i18n import N_, tr

# Kategorie -> (Anzeige, Titel-Wörter, Text-Wörter, Gewicht je Treffer); Wörter klein, ohne Satzzeichen
CATEGORIES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "pets": (N_("Pets (roll menu)"), ("pets",), ("pity", "open", "auto", "mythical")),
    "titans": (N_("Titans"), ("titan", "titans"), ("titan", "rare", "epic", "legendary", "secret")),
    "gacha": (N_("Gacha"), (), ("roll", "autoroll", "current", "buffs", "cost", "pity")),
    "crafting": (N_("Crafting"), ("crafting", "craft"), ("craft", "lose", "selected", "shiny")),
    "upgrade_tree": (N_("Upgrade tree"), ("tree",), ("total", "stats", "leveling", "token", "close")),
    "artefact": (N_("Artifact"), ("elixir", "artifact", "artefact"), ("artifact", "artefact", "fragments", "elixir",
                                                                      "progress", "boosts", "exit")),
    "upgrades": (N_("Upgrades"), ("upgrade", "upgrades"), ("upgrade", "max", "level", "lv")),
    "progression": (N_("Progression"), ("progression",), ("progression", "rank", "next")),
    "shop": (N_("Shop / merchant"), ("shop", "merchant"), ("buy", "stock", "restock", "shop", "merchant")),
    "battlepass": (N_("Battle pass"), ("battlepass", "pass"), ("battlepass", "tier", "premium", "free")),
    "raid": (N_("Raid"), ("raid",), ("raid", "start", "difficulty", "create", "join", "enter")),
    "defense": (N_("Defense"), ("defense",), ("defense", "mode", "wave", "start")),
    "exchange": (N_("Exchange"), ("exchange",), ("exchange", "trade", "token")),
    "boosts": (N_("Boosts"), ("boosts", "boost"), ("play", "pause", "sync", "food", "potion")),
    "passive": (N_("Passive"), ("passive", "passives", "curse", "curses"), ("passive", "reroll", "lock", "index")),
    "shrine": (N_("Shrine (offerings)"), ("shrine",), ("offered", "offer", "quantity", "coins", "choose")),
    "gigs": (N_("Fixer Gigs"), ("gigs", "fixer"), ("gigs", "claim", "finish", "slots", "ready", "send")),
    "info": (N_("Display only"), ("spirit", "contract", "chakra", "karma", "vessel", "celestial", "keys", "dragon",
                                 "slayer", "commandments", "renaming"), ()),
    "later": (N_("Later (1.5.0)"), ("exam", "cyberdeck", "quickhacks"), ()),
    "equip_best": (N_("Equip Best"), ("equip",), ("equip", "best", "power", "damage", "yen", "luck", "drop")),
    "guild": (N_("Guild"), ("guild",), ("guild", "members", "claim", "rewards", "quests", "donate")),
    # aus dem ersten echten Erkunden (07.10.2026): Knöpfe am Bildschirmrand und weitere Welt-Symbole
    "quests": (N_("Quests"), ("quests", "quest"), ("claim", "complete", "times", "quests")),
    "promotion": (N_("Promotion"), ("promotion", "promotions"), ("promote", "promotion", "missions", "boost")),
    "inventory": (N_("Inventory"), ("inventory",), ("rarity", "key", "inventory", "items")),
    "achievements": (N_("Achievements"), ("achievements", "achievement"), ("claim", "achievements", "veteran")),
    "index": (N_("Index"), ("index",), ("worlds", "collections", "index", "complete")),
    "ranks": (N_("Ranks"), ("ranks", "rank"), ("rank", "max", "auto")),
    "avatars": (N_("Avatars"), ("avatars", "avatar"), ("avatar", "equip")),
    "event": (N_("Game event"), ("event", "medal"), ("event", "medal")),
}

# Knöpfe, die beim Erkunden nur gemerkt, nie geklickt werden (kosten etwas oder ändern den Spielstand)
ACTION_WORDS = ("roll", "auto", "craft", "buy", "claim", "equip", "upgrade", "open", "sell", "delete", "confirm",
                "yes", "use", "donate", "start", "create", "join", "enter", "trade", "exchange", "reroll", "max")
CLOSE_WORDS = ("close", "exit")
# Reiter, die beim Durchklicken NIE gedrückt werden (Gilde verlassen, Mitglieder rauswerfen …)
NEVER_TABS = ("leave", "kick", "disband", "delete", "reset", "logout", "quit", "sell", "rebirth", "remove", "ban",
              "play", "pause", "stop", "unequip", "lock", "unlock", "activate", "invite", "accept", "decline",
              "promote", "rename", "filters", "filter", "search")
DROP_IGNORE = ("yen", "xp", "coins", "coin", "gems", "gem")       # in fast jedem Raid – sagt nichts über den Raid


@dataclass
class Analysis:
    category: str = "unknown"
    label: str = ""
    score: float = 0.0
    matched: list[str] = field(default_factory=list)
    buttons: list[tuple[str, list[float]]] = field(default_factory=list)   # (Wort, Lage im Roblox-Fenster)
    title: str = ""
    mode: str = ""                                    # Banner-Titel, wenn darunter ein eigener Name steht („Raid“)
    words: list = field(default_factory=list, repr=False)   # gelesene Wörter (nicht im Bericht)
    drops: list = field(default_factory=list)                # Raid-Fenster: „Enemy Drops“
    tabs: list = field(default_factory=list)                 # Reiter links (durchgeklickt): Name, Einordnung

    def as_dict(self) -> dict:
        return {"category": self.category, "label": self.label, "score": round(self.score, 2),
                "matched": self.matched, "buttons": [{"text": t, "roi": [round(v, 4) for v in r]}
                                                     for t, r in self.buttons], "title": self.title,
                **({"mode": self.mode} if self.mode else {}), **({"drops": self.drops} if self.drops else {}),
                **({"tabs": self.tabs} if self.tabs else {})}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def classify(title: str, words: list[tuple[str, list[float]]], template: str = "") -> Analysis:
    """Fenster einordnen. words = (Wort, Lage) aus der Texterkennung; template = Name einer erkannten Vorlage."""
    tokens = [_norm(w) for w, _r in words if _norm(w)]
    joined = " ".join(tokens)
    if "auto" in tokens and "roll" in tokens:
        tokens.append("autoroll")
    title_tokens = {_norm(t) for t in re.split(r"[\s/]+", title) if _norm(t)}
    best = Analysis(title=title)
    if template and "pets" in template.lower():
        best = Analysis("pets", tr(CATEGORIES["pets"][0]), 10.0, ["template"], title=title)
    else:
        for key, (label, title_words, text_words) in CATEGORIES.items():
            # Titel-Wörter nur am Wortanfang („Magecraft“ ist kein Crafting, „Street“ kein Tree)
            hit_title = [w for w in title_words if any(t.startswith(w) for t in title_tokens)]
            hit_text = sorted({w for w in text_words if w in tokens or (len(w) > 4 and w in joined)})
            score = 6.0 * len(hit_title) + len(hit_text)       # der Titel zählt viel mehr als Wörter im Fenster
            if key in ("equip_best", "guild") and not hit_title:
                continue                                  # nur mit passendem Titel (Shops zeigen auch Power, Yen …)
            if key == "titans" and "buffs" in tokens:
                score -= 2                                 # Gachas haben Buffs, Titans nicht
            if key in ("titans", "pets") and {"passive", "passives"} & title_tokens:
                score -= 6                                 # „Titan Passives“ ist ein Passiv-Fenster
            if key == "progression" and hit_title:
                score += 1                                 # „… Progression“ im Titel geht vor Wörtern im Fenster
            if key == "gacha" and ("titan" in joined or "pets" in title_tokens):
                score -= 3
            if score > best.score:
                best = Analysis(key, tr(label), score, hit_title + hit_text, title=title)
        if best.score < 2.0:
            best = Analysis("unknown", tr("Unknown"), best.score, best.matched, title=title)
    best.buttons = [(w, r) for w, r in words if _norm(w) in ACTION_WORDS or _norm(w) in CLOSE_WORDS]
    return best


def claimables(words: list[tuple[str, list[float]]]) -> list[list[float]]:
    """Lagen aller „Claim“-Knöpfe (Quests, Achievements, Gilde) – nur gemerkt, nie geklickt."""
    return [r for w, r in words if _norm(w) == "claim"]


def close_word(words: list[tuple[str, list[float]]]) -> list[float] | None:
    """Lage eines „Close“/„Exit“-Knopfs (ganze Bildschirme ohne rosa X), sonst None."""
    hits = [r for w, r in words if _norm(w) in CLOSE_WORDS]
    return max(hits, key=lambda r: r[1]) if hits else None     # der unterste (Knöpfe sitzen unten)


def _rows(cands: list[tuple[str, list[float]]], axis: int) -> list[tuple[str, list[float]]]:
    """Wörter derselben Zeile (axis=1) bzw. Spalte (axis=0) zu einem Eintrag zusammenfassen („Guild Weekly“)."""
    out: list[list] = []
    for w, b in sorted(cands, key=lambda c: (c[1][1], c[1][0]) if axis == 1 else (c[1][0], c[1][1])):
        if out and axis == 1 and abs(out[-1][1][1] - b[1]) < 0.6 * (b[3] - b[1]) and -0.005 <= b[0] - out[-1][1][2] < 0.03:
            out[-1][0] += " " + w
            out[-1][1] = [out[-1][1][0], min(out[-1][1][1], b[1]), b[2], max(out[-1][1][3], b[3])]
        else:
            out.append([w, list(b)])
    return [(w, b) for w, b in out]


def _dedupe(items: list[tuple[str, list[float]]]) -> list[tuple[str, list[float]]]:
    """Zwei Lesedurchgänge finden dasselbe Wort oft zweimal (leicht versetzt) – nur einmal behalten."""
    out: list[tuple[str, list[float]]] = []
    for t, b in items:
        if any(min(b[2], o[2]) - max(b[0], o[0]) > 0.5 * (b[2] - b[0]) and min(b[3], o[3]) - max(b[1], o[1]) > 0
               for _w, o in out):
            continue
        out.append((t, b))
    return out


def _longest_regular(col: list) -> list:
    """Längste Folge mit gleichmäßigem Abstand (ein abgesetzter Knopf wie „Leave“ ganz unten gehört nicht dazu)."""
    best: list = []
    for i in range(len(col)):
        for j in range(len(col), i + 3, -1):
            run = col[i:j]
            if len(run) > len(best) and _regular([c[1][1] for c in run]):
                best = run
                break
    return best


def is_forbidden(word: str) -> bool:
    """Gefährlicher Knopf (Leave, Kick, Delete …) – auch bei Lesefehlern („Leaves“, „Leav“)."""
    import difflib
    n = _norm(word)
    if len(n) < 3:
        return False
    return any(n.startswith(k) or k.startswith(n) and len(n) >= 4
               or difflib.SequenceMatcher(None, n, k).ratio() >= 0.8 for k in NEVER_TABS)


def _regular(values: list[float]) -> bool:
    diffs = [b - a for a, b in zip(values, values[1:])]
    return bool(diffs) and min(diffs) > 0 and max(diffs) / min(diffs) <= 1.5


def side_tabs(words: list[tuple[str, list[float]]], roi: list[float]) -> list[tuple[str, list[float]]]:
    """Reiter eines Fensters (streng, damit nie Spielknöpfe wie „Play“/„Pause“ oder Pets geklickt werden):
    - links: mindestens 4 Einträge untereinander, linksbündig, gleiche Schrifthöhe, gleichmäßiger Abstand
      (Gilde: Home, Upgrades, Members, Missions, Servers, Rankings);
    - unten: mindestens 4 Einträge nebeneinander in einer Zeile ganz unten (Achievements: Normal, Gamemode …).
    Nie Aktions- und Gefahren-Wörter (Leave, Kick, Play, Pause, Claim, Buy …)."""
    x0, y0, x1, y1 = roi
    w, h = x1 - x0, y1 - y0
    ok = _dedupe([(t, b) for t, b in words if len(re.sub(r"[^A-Za-z]", "", t)) >= 3 and is_safe_to_click(t)
                  and not is_forbidden(t)])
    # links
    left = _rows([(t, b) for t, b in ok if b[2] <= x0 + 0.42 * w], axis=1)    # große Fenster: Lage geschätzt
    best: list[tuple[str, list[float]]] = []
    for anchor in left:
        ax = (anchor[1][0] + anchor[1][2]) / 2
        col = [(t, b) for t, b in left if (abs(b[0] - anchor[1][0]) < 0.025 * w or abs((b[0] + b[2]) / 2 - ax) < 0.02 * w)
               and 0.7 < (b[3] - b[1]) / max(1e-6, anchor[1][3] - anchor[1][1]) < 1.4]
        col = _longest_regular(sorted(col, key=lambda c: c[1][1]))
        if len(col) >= 4 and len(col) > len(best) and not _list_rows(col, words, x0 + 0.35 * w):
            best = col
    if best:
        return best
    # unten: Zeilen ganz unten nach Höhe gruppieren; die unterste mit ≥ 4 gleichmäßig verteilten Einträgen
    bottom = sorted([(t, b) for t, b in ok if b[1] >= y0 + 0.88 * h], key=lambda c: (c[1][1] + c[1][3]) / 2)
    groups: list[list] = []
    for t, b in bottom:
        cy = (b[1] + b[3]) / 2
        if groups and cy - groups[-1][0] < 0.025:
            groups[-1][1].append((t, b))
        else:
            groups.append([cy, [(t, b)]])
    for _cy, items in reversed(groups):
        row = []
        for t, b in sorted(items, key=lambda c: c[1][0]):
            if row and b[0] < row[-1][1][2] - 0.005:
                continue                                  # überlappt: zweite Lesung desselben Reiters
            row.append((t, b))
        if len(row) >= 4 and _regular([(b[0] + b[2]) / 2 for _t, b in row]):
            return row
    return []


def _list_rows(col: list, words: list, right_of: float) -> bool:
    """Sind die „Reiter“ in Wahrheit Listenzeilen? (Upgrades: Yen … +5.00x … MAX in derselben Zeile)"""
    hits = 0
    for _t, b in col:
        cy, hh = (b[1] + b[3]) / 2, b[3] - b[1]
        if any(o[0] > right_of and abs((o[1] + o[3]) / 2 - cy) < 0.35 * hh for _w, o in words):
            hits += 1
    return hits >= 0.75 * len(col)


FORBID_MARGIN = 0.03      # so viel Abstand (Anteil des Fensters) bleibt um gesperrte Knöpfe frei – auch kein Hover
# Knöpfe, die das Erkunden zum Testen drücken darf: reine Ansichts-/Seitenwechsel (Liste bewusst klein)
NAV_WORDS = ("info", "index", "help", "details", "stats", "members", "personal", "weekly", "daily", "global",
             "online", "all", "rewards", "missions", "upgrades", "rankings", "servers", "home", "quests", "normal",
             "gamemode", "raid", "collection", "guild", "page", "next", "prev", "back", "overview", "list")


def forbidden_zones(words: list[tuple[str, list[float]]], roi: list[float], title: str = "") -> list[list[float]]:
    """Bereiche, die das Makro nie ansteuern darf (Klick, Mausrad, Hover): gefährliche Knöpfe (Leave, Kick …) mit
    Rand – und in der Gilde immer die Ecke unten links, wo „Leave“ sitzt (auch wenn die Texterkennung es übersieht)."""
    x0, y0, x1, y1 = roi
    w, h = x1 - x0, y1 - y0
    zones = []
    for t, b in words:
        if is_forbidden(t):
            zones.append([b[0] - FORBID_MARGIN, b[1] - FORBID_MARGIN, b[2] + FORBID_MARGIN, b[3] + FORBID_MARGIN])
    if "guild" in _norm(title) or any(_norm(t).startswith("leave") for t, _b in words):
        zones.append([x0 - 0.01, y0 + 0.78 * h, x0 + 0.36 * w, y1 + 0.01])     # Gilde: „Leave“ unten links
    return zones


def inside(pos: tuple[float, float], zones: list[list[float]]) -> bool:
    return any(z[0] <= pos[0] <= z[2] and z[1] <= pos[1] <= z[3] for z in zones)


def nav_buttons(words: list[tuple[str, list[float]]], skip: list[tuple[str, list[float]]]) -> list:
    """Knöpfe, die das Erkunden testweise drücken darf: nur Wörter aus NAV_WORDS, nichts Gesperrtes, keine Reiter
    (die werden extra durchgeklickt)."""
    taken = [b for _t, b in skip]
    out = []
    for t, b in _dedupe(words):
        n = _norm(t)
        if n in NAV_WORDS and is_safe_to_click(t) and not is_forbidden(t) and not any(
                abs(b[0] - o[0]) < 0.01 and abs(b[1] - o[1]) < 0.01 for o in taken):
            out.append((t, b))
    return out[:6]


def lines_of(words: list[tuple[str, list[float]]]) -> list[str]:
    """Gelesene Wörter zu Textzeilen zusammensetzen (Bericht lesbar statt einzelner Wörter); weit auseinander
    stehende Teile einer Höhe (Spalten) werden mit „ · “ getrennt."""
    rows: list[list] = []
    for t, b in sorted(_dedupe(words), key=lambda c: ((c[1][1] + c[1][3]) / 2, c[1][0])):
        cy, hgt = (b[1] + b[3]) / 2, b[3] - b[1]
        if rows and abs(rows[-1][0] - cy) < 0.5 * max(hgt, rows[-1][1]):
            rows[-1][2].append((t, b))
        else:
            rows.append([cy, hgt, [(t, b)]])
    out = []
    for _cy, _h, items in rows:
        items.sort(key=lambda c: c[1][0])
        text, last, prev = "", None, ""
        for t, b in items:
            if last is not None:
                gap, hh = b[0] - last, max(1e-6, b[3] - b[1])
                if prev.endswith("/") or t.startswith("/"):
                    text += " "                            # „514δU / MAX“ gehört zusammen
                else:
                    text += " · " if gap > max(0.04, 2.5 * hh) else " "
            text += t
            last, prev = b[2], t
        out.append(text)
    return out


def raid_drops(words: list[tuple[str, list[float]]]) -> list[str]:
    """„Enemy Drops“ eines Raid-Fensters: Beschriftungen unter den Symbolen zwischen „Enemy Drops:“ und den Knöpfen
    Create/Join/Start. Wörter einer Kachel werden zusammengefasst („Grail Shard“). Yen/XP fallen weg."""
    head = next((b for w, b in words if _norm(w) in ("drops", "enemydrops")), None)
    foot = min((b[1] for w, b in words if _norm(w) in ("create", "join", "start")), default=None)
    if head is None or foot is None or foot <= head[3]:
        return []
    band = [(w, b) for w, b in words if head[3] < b[1] < foot and "%" not in w and len(_norm(w)) >= 3]
    # je Kachel eine Spalte: Wörter nach ihrer Mitte gruppieren (Beschriftung kann zwei Zeilen haben)
    band.sort(key=lambda c: (c[1][0] + c[1][2]) / 2)
    cols: list[list] = []
    for w, b in band:
        cx = (b[0] + b[2]) / 2
        if cols and cx - cols[-1][0] < 0.05:
            cols[-1][1].append((w, b))
            cols[-1][0] = cx                                # Kette: nächstes Wort derselben Beschriftung
        else:
            cols.append([cx, [(w, b)]])
    names = [[" ".join(w for w, _b in sorted(ws, key=lambda c: (int(c[1][1] / 0.015), c[1][0]))), None]
             for _cx, ws in cols]
    out = []
    for text, _b in names:
        clean = re.sub(r"[^A-Za-z0-9' ]", "", text).strip()
        if len(clean) >= 3 and _norm(clean) not in DROP_IGNORE and clean not in out:
            out.append(clean)
    return out


def is_safe_to_click(word: str) -> bool:
    """Beim Erkunden nie auf Aktions-Knöpfe klicken (Roll, Craft, Buy, Claim …)."""
    return _norm(word) not in ACTION_WORDS


# ------------------------------------------------------------------ Fenstertitel berichtigen
# Wörter, die in Fenstertiteln des Spiels vorkommen – Lesefehler werden auf sie gezogen („Cratt“ -> „Craft“).
GAME_WORDS = ("Craft", "Crafting", "Shrine", "Upgrade", "Upgrades", "Tree", "Raid", "Progression", "Defense", "Mode",
              "Shop", "Merchant", "Passive", "Passives", "Index", "Battlepass", "Pets", "Roll", "Exchange",
              "Achievements", "Promotions", "Boosts", "Quests", "Global", "Inventory", "Guild", "Equip", "Best",
              "Rush", "Boss", "War", "Tower", "Gigs", "Fixer", "Trial", "Upgrade", "Awakening", "Specialization",
              "Ranks", "Avatars", "Offerings", "Swords", "Sword", "Banner", "Holy", "Grail", "Spirit", "Contract")
_NOT_TITLE = {"fenster", "platz", "lobby", "vorlage", "knopf"}


def _title_words(names) -> list[str]:
    out: dict[str, str] = {w.lower(): w for w in GAME_WORDS}
    for name in names:
        for word in re.findall(r"[A-Za-z][A-Za-z']{2,}", name or ""):
            if word.lower() not in _NOT_TITLE:
                out.setdefault(word.lower(), word)
    return list(out.values())


def _clean_name(name: str) -> str:
    """Bekannter Name ohne Welt, „Fenster“, „(2)“ – und mit berichtigten Spiel-Wörtern (frühere Lesefehler wie
    „Kagune Upgraid“ sollen nicht als Vorbild dienen)."""
    name = re.sub(r"^W\d+\s+|\s*·.*$|\s*\(\d+\)$|\s+Fenster$", "", name or "").strip()
    if name.lower() in _NOT_TITLE:
        return ""
    out = []
    for word in name.split():
        match = difflib.get_close_matches(word, GAME_WORDS, n=1, cutoff=0.85)
        out.append(match[0] if match and word.lower() != match[0].lower() else word)
    return " ".join(out)


def _fix_word(word: str, vocab: list[str], last: bool) -> tuple[str, bool]:
    """Ein Wort berichtigen. Rückgabe: (Wort, bekannt). Nur echte Lesefehler: ähnlich (≥ 0,8) und fast gleich lang –
    „Cratt“ -> „Craft“, „Worsutsuki“ -> „Otsutsuki“; am Zeilenende auch abgeschnittene Wörter („Shrin“ -> „Shrine“).
    Richtige Wörter bleiben, auch Einzahl/Mehrzahl („Pet“, „Fruit“) und Großschreibung („NINJA EXAM“)."""
    core = re.sub(r"[^A-Za-z']", "", word)
    low = core.lower()
    lows = {v.lower() for v in vocab}
    if len(core) < 3 or low in lows:
        return word, low in lows
    best, score = "", 0.0
    for v in vocab:                                       # Spiel-Wörter zuerst: bei Gleichstand gewinnen sie
        vl = v.lower()
        if vl in (low + "s", low + "es") or low in (vl + "s", vl + "es"):
            continue                                      # Mehrzahl ist kein Lesefehler
        r = difflib.SequenceMatcher(None, low, vl).ratio()
        ok = r >= 0.8 and abs(len(vl) - len(low)) <= max(1, len(low) // 5)
        if last and len(low) >= 4 and vl.startswith(low) and len(vl) - len(low) <= 3:
            ok, r = True, r + 0.15                         # abgeschnitten: das vollständige Wort bevorzugen
        if ok and r > score:
            best, score = v, r
    if not best:
        return word, False
    return (best.upper() if core.isupper() and len(core) > 1 else best), True


def fix_title(text: str, names) -> str:
    """Gelesenen Titel berichtigen, damit Fenster so heißen wie im Spiel (Eigentümer 08.10.2026): Wort für Wort auf
    bekannte Wörter ziehen („Worsutsuki Shrin“ -> „Otsutsuki Shrine“, „Cratt Genos“ -> „Craft Genos“), kurze Reste
    am Rand weglassen („AK Kagune Upgra“ -> „Kagune Upgrade“). Ganze Namen werden nicht ersetzt (sonst würde aus
    „Fire Progression“ „Ki Progression“). names: bekannte Fensternamen (Karte, Berichte, Funde prüfen)."""
    text = (text or "").strip()
    if not text:
        return ""
    known = [n for n in (_clean_name(n) for n in names) if n]
    vocab = _title_words(known)
    lows = {v.lower() for v in vocab}
    words = text.split()
    while len(words) > 1 and re.fullmatch(r"[A-Za-z]{1,2}", words[0]) and words[0].lower() not in lows:
        words.pop(0)                                      # Rest vom Banner-Rand („AK“)
    while len(words) > 1 and re.fullmatch(r"[A-Za-z]{1,2}", words[-1]) and words[-1].lower() not in lows:
        words.pop()
    fixed = [_fix_word(word, vocab, i == len(words) - 1)[0] for i, word in enumerate(words)]
    out = " ".join(fixed)
    return out[:1].upper() + out[1:]
