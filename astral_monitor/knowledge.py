"""Built-in game knowledge for exploring (without Qt): classify windows by their title and the words read,
and name buttons. Derived from the owner's real screenshots (07.10.2026):

- Gacha (e.g. Doujutsu, Races, Hakis, Family): “Roll”, “Auto Roll”, “Current:”, “Buffs:”, “Cost:”, pity bar.
  At most 2 gachas active at the same time (doesn't matter for the program).
- Titans: like a gacha (Roll/Auto Roll/pity), but its own system – rarities instead of buffs.
- Pets: roll menu with “Open!”, “Auto!”, “Mythical Pity” (template “Pets-Roll”).
- Crafting: “Craft”, “You will lose the selected Pets …”, “Shiny”.
- Upgrade tree: full screen, “Total Stats:”, “Leveling Token”, red “Close” button.
- Artifact (e.g. Elixir of Life): full screen, “fragments”, “artifact”, “Boosts”, “Progress Level”, “Exit”.
- Auto roll keeps running in the background: close the window right after “Auto”.

Added after the second explore run (owner, 08.10.2026):
- Raids/defense/boss rush: the actual name is in large red/orange letters below the banner (“Holy Grail War”).
  Some have difficulties at the top right of the window: W17 raid 3 levels; Cursed Rush → “King of Curses Rush” only
  selectable once you have collected 10 fingers (from the first level) below it.
- Shrines (Goddess, Otsutsuki, Demon King): “offer” currency (10–100 %) for boosts.
- Passives (pet/titan/shadow passives, Acc. Curses): each its own system, index/roll/auto.
- Fixer Gigs (W21): jobs of 20 min/1 h/3 h, “Claim” → “Send Pets” (pets window, choose the last pets).
- Display only, no use for the macro: Spirit Contract, Chakra Training, Karma, Vessel, Celestial Keys,
  Dragon Slayer, Commandments; renaming is left to the player.
- Later (1.5.0): Ninja Exam, Cyberdeck/Quickhacks, Sins Upgrade Tree."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .i18n import N_, tr

# category -> (display, title words, text words, weight per hit); words lower case, without punctuation
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
    # from the first real explore run (07.10.2026): buttons at the screen edge and more world icons
    "quests": (N_("Quests"), ("quests", "quest"), ("claim", "complete", "times", "quests")),
    "promotion": (N_("Promotion"), ("promotion", "promotions"), ("promote", "promotion", "missions", "boost")),
    "inventory": (N_("Inventory"), ("inventory",), ("rarity", "key", "inventory", "items")),
    "achievements": (N_("Achievements"), ("achievements", "achievement"), ("claim", "achievements", "veteran")),
    "index": (N_("Index"), ("index",), ("worlds", "collections", "index", "complete")),
    "ranks": (N_("Ranks"), ("ranks", "rank"), ("rank", "max", "auto")),
    "avatars": (N_("Avatars"), ("avatars", "avatar"), ("avatar", "equip")),
    "event": (N_("Game event"), ("event", "medal"), ("event", "medal")),
}

# Buttons that exploring only notes and never clicks (they cost something or change the game state)
ACTION_WORDS = ("roll", "auto", "craft", "buy", "claim", "equip", "upgrade", "open", "sell", "delete", "confirm",
                "yes", "use", "donate", "start", "create", "join", "enter", "trade", "exchange", "reroll", "max")
CLOSE_WORDS = ("close", "exit")
# Tabs that are NEVER pressed while clicking through (leave guild, kick members …)
NEVER_TABS = ("leave", "kick", "disband", "delete", "reset", "logout", "quit", "sell", "rebirth", "remove", "ban",
              "play", "pause", "stop", "unequip", "lock", "unlock", "activate", "invite", "accept", "decline",
              "promote", "rename", "filters", "filter", "search")
DROP_IGNORE = ("yen", "xp", "coins", "coin", "gems", "gem")       # in almost every raid – says nothing about the raid


@dataclass
class Analysis:
    category: str = "unknown"
    label: str = ""
    score: float = 0.0
    matched: list[str] = field(default_factory=list)
    buttons: list[tuple[str, list[float]]] = field(default_factory=list)   # (word, position in the Roblox window)
    title: str = ""
    mode: str = ""                                    # banner title if there is a name of its own below (“Raid”)
    words: list = field(default_factory=list, repr=False)   # words read (not in the report)
    drops: list = field(default_factory=list)                # raid window: “Enemy Drops”
    tabs: list = field(default_factory=list)                 # tabs on the left (clicked through): name, classification

    def as_dict(self) -> dict:
        return {"category": self.category, "label": self.label, "score": round(self.score, 2),
                "matched": self.matched, "buttons": [{"text": t, "roi": [round(v, 4) for v in r]}
                                                     for t, r in self.buttons], "title": self.title,
                **({"mode": self.mode} if self.mode else {}), **({"drops": self.drops} if self.drops else {}),
                **({"tabs": self.tabs} if self.tabs else {})}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def classify(title: str, words: list[tuple[str, list[float]]], template: str = "") -> Analysis:
    """Classify a window. words = (word, position) from text recognition; template = name of a recognized template."""
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
            # title words only at the start of a word (“Magecraft” isn't crafting, “Street” isn't a tree)
            hit_title = [w for w in title_words if any(t.startswith(w) for t in title_tokens)]
            hit_text = sorted({w for w in text_words if w in tokens or (len(w) > 4 and w in joined)})
            score = 6.0 * len(hit_title) + len(hit_text)       # the title counts much more than words in the window
            if key in ("equip_best", "guild") and not hit_title:
                continue                                  # only with a matching title (shops show power, yen … too)
            if key == "titans" and "buffs" in tokens:
                score -= 2                                 # gachas have buffs, titans don't
            if key in ("titans", "pets") and {"passive", "passives"} & title_tokens:
                score -= 6                                 # “Titan Passives” is a passive window
            if key == "progression" and hit_title:
                score += 1                                 # “… Progression” in the title beats words in the window
            if key == "gacha" and ("titan" in joined or "pets" in title_tokens):
                score -= 3
            if score > best.score:
                best = Analysis(key, tr(label), score, hit_title + hit_text, title=title)
        if best.score < 2.0:
            best = Analysis("unknown", tr("Unknown"), best.score, best.matched, title=title)
    best.buttons = [(w, r) for w, r in words if _norm(w) in ACTION_WORDS or _norm(w) in CLOSE_WORDS]
    return best


def claimables(words: list[tuple[str, list[float]]]) -> list[list[float]]:
    """Positions of all “Claim” buttons (quests, achievements, guild) – only noted, never clicked."""
    return [r for w, r in words if _norm(w) == "claim"]


def close_word(words: list[tuple[str, list[float]]]) -> list[float] | None:
    """Position of a “Close”/“Exit” button (full screens without the pink X), otherwise None."""
    hits = [r for w, r in words if _norm(w) in CLOSE_WORDS]
    return max(hits, key=lambda r: r[1]) if hits else None     # the lowest one (buttons sit at the bottom)


def _rows(cands: list[tuple[str, list[float]]], axis: int) -> list[tuple[str, list[float]]]:
    """Merge words of the same row (axis=1) or column (axis=0) into one entry (“Guild Weekly”)."""
    out: list[list] = []
    for w, b in sorted(cands, key=lambda c: (c[1][1], c[1][0]) if axis == 1 else (c[1][0], c[1][1])):
        if out and axis == 1 and abs(out[-1][1][1] - b[1]) < 0.6 * (b[3] - b[1]) and -0.005 <= b[0] - out[-1][1][2] < 0.03:
            out[-1][0] += " " + w
            out[-1][1] = [out[-1][1][0], min(out[-1][1][1], b[1]), b[2], max(out[-1][1][3], b[3])]
        else:
            out.append([w, list(b)])
    return [(w, b) for w, b in out]


def _dedupe(items: list[tuple[str, list[float]]]) -> list[tuple[str, list[float]]]:
    """Two reading passes often find the same word twice (slightly offset) – keep it only once."""
    out: list[tuple[str, list[float]]] = []
    for t, b in items:
        if any(min(b[2], o[2]) - max(b[0], o[0]) > 0.5 * (b[2] - b[0]) and min(b[3], o[3]) - max(b[1], o[1]) > 0
               for _w, o in out):
            continue
        out.append((t, b))
    return out


def _longest_regular(col: list) -> list:
    """Longest sequence with even spacing (a separate button like “Leave” at the very bottom doesn't belong to it)."""
    best: list = []
    for i in range(len(col)):
        for j in range(len(col), i + 3, -1):
            run = col[i:j]
            if len(run) > len(best) and _regular([c[1][1] for c in run]):
                best = run
                break
    return best


def is_forbidden(word: str) -> bool:
    """Dangerous button (Leave, Kick, Delete …) – also with misreads (“Leaves”, “Leav”)."""
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
    """Tabs of a window (strict, so game buttons like “Play”/“Pause” or pets are never clicked):
    - left: at least 4 entries one below the other, left-aligned, same text height, even spacing
      (guild: Home, Upgrades, Members, Missions, Servers, Rankings);
    - bottom: at least 4 entries side by side in a row at the very bottom (achievements: Normal, Gamemode …).
    Never action or danger words (Leave, Kick, Play, Pause, Claim, Buy …)."""
    x0, y0, x1, y1 = roi
    w, h = x1 - x0, y1 - y0
    ok = _dedupe([(t, b) for t, b in words if len(re.sub(r"[^A-Za-z]", "", t)) >= 3 and is_safe_to_click(t)
                  and not is_forbidden(t)])
    # left
    left = _rows([(t, b) for t, b in ok if b[2] <= x0 + 0.42 * w], axis=1)    # large windows: position estimated
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
    # bottom: group the rows at the very bottom by height; the lowest with ≥ 4 evenly spaced entries
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
                continue                                  # overlaps: second reading of the same tab
            row.append((t, b))
        if len(row) >= 4 and _regular([(b[0] + b[2]) / 2 for _t, b in row]):
            return row
    return []


def _list_rows(col: list, words: list, right_of: float) -> bool:
    """Are the “tabs” actually list rows? (upgrades: Yen … +5.00x … MAX in the same row)"""
    hits = 0
    for _t, b in col:
        cy, hh = (b[1] + b[3]) / 2, b[3] - b[1]
        if any(o[0] > right_of and abs((o[1] + o[3]) / 2 - cy) < 0.35 * hh for _w, o in words):
            hits += 1
    return hits >= 0.75 * len(col)


FORBID_MARGIN = 0.03      # this much margin (share of the window) stays free around blocked buttons – no hover either
# Buttons exploring may press for testing: pure view/page switches (list kept small on purpose)
NAV_WORDS = ("info", "index", "help", "details", "stats", "members", "personal", "weekly", "daily", "global",
             "online", "all", "rewards", "missions", "upgrades", "rankings", "servers", "home", "quests", "normal",
             "gamemode", "raid", "collection", "guild", "page", "next", "prev", "back", "overview", "list")


def forbidden_zones(words: list[tuple[str, list[float]]], roi: list[float], title: str = "") -> list[list[float]]:
    """Areas the macro must never go to (click, mouse wheel, hover): dangerous buttons (Leave, Kick …) with a
    margin – and in the guild always the bottom left corner where “Leave” sits (even if text recognition misses it)."""
    x0, y0, x1, y1 = roi
    w, h = x1 - x0, y1 - y0
    zones = []
    for t, b in words:
        if is_forbidden(t):
            zones.append([b[0] - FORBID_MARGIN, b[1] - FORBID_MARGIN, b[2] + FORBID_MARGIN, b[3] + FORBID_MARGIN])
    if "guild" in _norm(title) or any(_norm(t).startswith("leave") for t, _b in words):
        zones.append([x0 - 0.01, y0 + 0.78 * h, x0 + 0.36 * w, y1 + 0.01])     # guild: “Leave” at the bottom left
    return zones


def inside(pos: tuple[float, float], zones: list[list[float]]) -> bool:
    return any(z[0] <= pos[0] <= z[2] and z[1] <= pos[1] <= z[3] for z in zones)


def nav_buttons(words: list[tuple[str, list[float]]], skip: list[tuple[str, list[float]]]) -> list:
    """Buttons exploring may press for testing: only words from NAV_WORDS, nothing blocked, no tabs
    (they are clicked through separately)."""
    taken = [b for _t, b in skip]
    out = []
    for t, b in _dedupe(words):
        n = _norm(t)
        if n in NAV_WORDS and is_safe_to_click(t) and not is_forbidden(t) and not any(
                abs(b[0] - o[0]) < 0.01 and abs(b[1] - o[1]) < 0.01 for o in taken):
            out.append((t, b))
    return out[:6]


def lines_of(words: list[tuple[str, list[float]]]) -> list[str]:
    """Put read words together into text lines (readable report instead of single words); parts of one height far
    apart (columns) are separated with “ · ”."""
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
                    text += " "                            # “514δU / MAX” belongs together
                else:
                    text += " · " if gap > max(0.04, 2.5 * hh) else " "
            text += t
            last, prev = b[2], t
        out.append(text)
    return out


def raid_drops(words: list[tuple[str, list[float]]]) -> list[str]:
    """“Enemy Drops” of a raid window: labels below the icons between “Enemy Drops:” and the buttons
    Create/Join/Start. Words of one tile are merged (“Grail Shard”). Yen/XP are dropped."""
    head = next((b for w, b in words if _norm(w) in ("drops", "enemydrops")), None)
    foot = min((b[1] for w, b in words if _norm(w) in ("create", "join", "start")), default=None)
    if head is None or foot is None or foot <= head[3]:
        return []
    band = [(w, b) for w, b in words if head[3] < b[1] < foot and "%" not in w and len(_norm(w)) >= 3]
    # one column per tile: group words by their center (a label can have two lines)
    band.sort(key=lambda c: (c[1][0] + c[1][2]) / 2)
    cols: list[list] = []
    for w, b in band:
        cx = (b[0] + b[2]) / 2
        if cols and cx - cols[-1][0] < 0.05:
            cols[-1][1].append((w, b))
            cols[-1][0] = cx                                # chain: next word of the same label
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
    """Never click action buttons while exploring (Roll, Craft, Buy, Claim …)."""
    return _norm(word) not in ACTION_WORDS


# ------------------------------------------------------------------ Correct window titles
# Words that occur in the game's window titles – misreads are pulled to them (“Cratt” -> “Craft”).
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
    """Known name without world, “Fenster”, “(2)” – and with corrected game words (earlier misreads like
    “Kagune Upgraid” shouldn't serve as a model)."""
    name = re.sub(r"^W\d+\s+|\s*·.*$|\s*\(\d+\)$|\s+Fenster$", "", name or "").strip()
    if name.lower() in _NOT_TITLE:
        return ""
    out = []
    for word in name.split():
        match = difflib.get_close_matches(word, GAME_WORDS, n=1, cutoff=0.85)
        out.append(match[0] if match and word.lower() != match[0].lower() else word)
    return " ".join(out)


def _fix_word(word: str, vocab: list[str], last: bool) -> tuple[str, bool]:
    """Correct one word. Returns (word, known). Only real misreads: similar (≥ 0.8) and almost the same length –
    “Cratt” -> “Craft”, “Worsutsuki” -> “Otsutsuki”; at the end of a line also cut-off words (“Shrin” -> “Shrine”).
    Correct words stay, also singular/plural (“Pet”, “Fruit”) and case (“NINJA EXAM”)."""
    core = re.sub(r"[^A-Za-z']", "", word)
    low = core.lower()
    lows = {v.lower() for v in vocab}
    if len(core) < 3 or low in lows:
        return word, low in lows
    best, score = "", 0.0
    for v in vocab:                                       # game words first: they win a tie
        vl = v.lower()
        if vl in (low + "s", low + "es") or low in (vl + "s", vl + "es"):
            continue                                      # a plural is not a misread
        r = difflib.SequenceMatcher(None, low, vl).ratio()
        ok = r >= 0.8 and abs(len(vl) - len(low)) <= max(1, len(low) // 5)
        if last and len(low) >= 4 and vl.startswith(low) and len(vl) - len(low) <= 3:
            ok, r = True, r + 0.15                         # cut off: prefer the complete word
        if ok and r > score:
            best, score = v, r
    if not best:
        return word, False
    return (best.upper() if core.isupper() and len(core) > 1 else best), True


def fix_title(text: str, names) -> str:
    """Correct a read title so windows are named as in the game (owner 08.10.2026): pull it word by word to known
    words (“Worsutsuki Shrin” -> “Otsutsuki Shrine”, “Cratt Genos” -> “Craft Genos”), drop short leftovers at the
    edge (“AK Kagune Upgra” -> “Kagune Upgrade”). Whole names are not replaced (otherwise “Fire Progression”
    would become “Ki Progression”). names: known window names (map, reports, check findings)."""
    text = (text or "").strip()
    if not text:
        return ""
    known = [n for n in (_clean_name(n) for n in names) if n]
    vocab = _title_words(known)
    lows = {v.lower() for v in vocab}
    words = text.split()
    while len(words) > 1 and re.fullmatch(r"[A-Za-z]{1,2}", words[0]) and words[0].lower() not in lows:
        words.pop(0)                                      # leftover from the banner edge (“AK”)
    while len(words) > 1 and re.fullmatch(r"[A-Za-z]{1,2}", words[-1]) and words[-1].lower() not in lows:
        words.pop()
    fixed = [_fix_word(word, vocab, i == len(words) - 1)[0] for i, word in enumerate(words)]
    out = " ".join(fixed)
    return out[:1].upper() + out[1:]
