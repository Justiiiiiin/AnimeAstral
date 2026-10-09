"""Explore: window classification (knowledge), local additions to the map, icon slots – without Qt/Tesseract/Roblox."""
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401
import numpy as np

from astral_monitor import knowledge, vision
from astral_monitor.uimap import UiMap, load_local, save_local


def W(*texts):
    """Words with a dummy position (one below the other)."""
    return [(t, [0.4, 0.1 + i * 0.05, 0.5, 0.13 + i * 0.05]) for i, t in enumerate(texts)]


class ClassifyTest(unittest.TestCase):
    """Word lists as read from the real screenshots (07.10.2026)."""

    def test_gacha(self):
        a = knowledge.classify("DOUJUTSU", W("Current:", "Buffs:", "Cost:", "Roll", "Auto", "Roll", "Pity"))
        self.assertEqual(a.category, "gacha")
        self.assertIn("Auto", [b for b, _ in a.buttons])

    def test_titans_not_gacha(self):
        a = knowledge.classify("Titans", W("Rare", "Epic", "Legendary", "Armored", "Titan", "ROLL", "AUTO", "ROLL",
                                           "Pity"))
        self.assertEqual(a.category, "titans")

    def test_crafting(self):
        a = knowledge.classify("Crafting", W("You", "will", "lose", "the", "selected", "Pets", "Craft", "Shiny"))
        self.assertEqual(a.category, "crafting")

    def test_fullscreen_windows(self):
        tree = W("Total", "Stats:", "Luck", "Yen", "Leveling", "Token", "Close")
        self.assertEqual(knowledge.classify("", tree).category, "upgrade_tree")
        self.assertIsNotNone(knowledge.close_word(tree))
        art = W("Craft", "Elixir", "Of", "Life", "fragments", "artifact", "Boosts", "Progress", "Level", "Exit")
        self.assertEqual(knowledge.classify("", art).category, "artefact")
        self.assertIsNotNone(knowledge.close_word(art))

    def test_shop_title_beats_stat_words(self):
        a = knowledge.classify("Trial Shop", W("Power", "Damage", "Yen", "Luck", "Drop", "XP"))
        self.assertEqual(a.category, "shop")

    def test_pets_template(self):
        self.assertEqual(knowledge.classify("", W("Open!", "Auto!"), "Pets-Roll (Vorlage)").category, "pets")

    def test_real_run_titles(self):
        """From the first real explore run: quests mention raids but are quests."""
        quests = W("Glo", "ests", "AUTO", "CLAIM", "Complete", "MaxTac", "Call", "times", "Join", "Timeless", "Raid")
        a = knowledge.classify("Global Quests", quests)
        self.assertEqual(a.category, "quests")
        self.assertEqual(len(knowledge.claimables(quests)), 1)
        self.assertEqual(knowledge.classify("Inventory", W("Rarity", "Key")).category, "inventory")
        self.assertEqual(knowledge.classify("Achievements", W("Claim", "Veteran")).category, "achievements")

    def test_second_run_titles(self):
        """From the second explore run (08.10.2026): title words only at the start of a word, new window kinds."""
        cases = {
            "Magecraft Progression": ("progression", W("Craft", "Craft", "Auto", "Roll")),
            "Street cred progression": ("progression", W("Tree", "Token")),
            "Titan Passives": ("passive", W("Index", "Roll", "Auto", "Titan")),
            "Acc. Curses": ("passive", W("Index", "Roll", "Auto")),
            "Goddess Shrine": ("shrine", W("Choose", "quantity", "coins", "offer")),
            "Fixer Gigs": ("gigs", W("CLAIM", "FINISH", "NOW")),
            "Chakra Training": ("info", W("Reset")),
            "Renaming": ("info", W("RENAME")),
            "NINJA EXAM": ("later", W("BOOSTS", "START", "EXAM")),
        }
        for title, (category, words) in cases.items():
            self.assertEqual(knowledge.classify(title, words).category, category, title)

    def test_side_tabs_without_leave(self):
        # guild: tabs on the left one below the other, “Leave” at the very bottom must never be pressed
        words = [(n, [0.12, 0.3 + i * 0.08, 0.25, 0.34 + i * 0.08]) for i, n in
                 enumerate(("Home", "Upgrades", "Members", "Missions", "Servers", "Rankings"))]
        words += [("Leave", [0.12, 0.9, 0.25, 0.94]), ("Claim", [0.85, 0.6, 0.92, 0.64]),
                  ("Personal", [0.3, 0.35, 0.45, 0.39])]
        tabs = [n for n, _b in knowledge.side_tabs(words, [0.05, 0.05, 0.95, 0.95])]
        self.assertEqual(tabs, ["Home", "Upgrades", "Members", "Missions", "Servers", "Rankings"])

    def test_raid_drops(self):
        words = [("Enemy", [0.1, 0.45, 0.2, 0.49]), ("Drops:", [0.21, 0.45, 0.3, 0.49]),
                 ("Bankai", [0.1, 0.6, 0.15, 0.62]), ("Token", [0.155, 0.6, 0.19, 0.62]),
                 ("Grail", [0.3, 0.6, 0.34, 0.62]), ("Shard", [0.345, 0.6, 0.38, 0.62]),
                 ("Yen", [0.5, 0.6, 0.53, 0.62]), ("50%", [0.1, 0.52, 0.13, 0.54]),
                 ("Create", [0.1, 0.7, 0.2, 0.74]), ("Join", [0.3, 0.7, 0.35, 0.74])]
        self.assertEqual(knowledge.raid_drops(words), ["Bankai Token", "Grail Shard"])

    def test_guild_leave_is_never_targeted(self):
        """Guild: “Leave” (also misread as “Leaves”) and the whole bottom left corner are blocked."""
        roi = [0.161, 0.149, 0.832, 0.876]
        words = [("Home", [0.263, 0.342, 0.316, 0.362]), ("Members", [0.245, 0.445, 0.33, 0.476]),
                 ("Leaves", [0.265, 0.776, 0.331, 0.805]), ("Invite", [0.56, 0.774, 0.6, 0.793])]
        zones = knowledge.forbidden_zones(words, roi, "Guild")
        self.assertTrue(knowledge.inside((0.298, 0.79), zones))        # on “Leave”
        self.assertTrue(knowledge.inside((0.3, 0.83), zones))          # just below it (margin)
        self.assertTrue(knowledge.inside((0.2, 0.86), zones))          # bottom left corner, even without text
        self.assertFalse(knowledge.inside((0.29, 0.352), zones))       # “Home” stays free
        no_text = knowledge.forbidden_zones([], roi, "Guild")          # recognition missed “Leave”
        self.assertTrue(knowledge.inside((0.298, 0.79), no_text))
        for word in ("Leave", "LEAVE!", "Leaves", "Leav", "Kick", "Delete", "Pause", "Play", "Unequip"):
            self.assertTrue(knowledge.is_forbidden(word), word)
        self.assertFalse(knowledge.is_forbidden("Members"))
        tabs = [t for t, _b in knowledge.side_tabs(words, roi)]
        self.assertNotIn("Leaves", tabs)
        self.assertEqual(knowledge.nav_buttons([("Leave", [0.2, 0.8, 0.3, 0.82]), ("Members", [0.6, 0.3, 0.7, 0.32])],
                                               []), [("Members", [0.6, 0.3, 0.7, 0.32])])

    def test_unknown_and_safety(self):
        self.assertEqual(knowledge.classify("", W("Hello")).category, "unknown")
        for word in ("Roll", "Auto", "Craft", "Buy", "Claim", "Equip"):
            self.assertFalse(knowledge.is_safe_to_click(word), word)
        self.assertTrue(knowledge.is_safe_to_click("Members"))


class LocalMapTest(unittest.TestCase):
    def test_local_entries_are_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "uimap_local.json"
            base = UiMap.load(local=local)
            lw = base.list_windows()[0]
            row = {"name": "W99 Testwelt", "kind": "Zeile (Vorlage)", "parent": lw["name"], "file": "local:row:W99",
                   "roi": [0.26, 0.4, 0.74, 0.5]}
            btn = {"name": "W99 · Platz 1", "kind": "Knopf", "parent": "W99 Testwelt", "rel": [0.13, 0.48, 0.18, 0.88],
                   "roi": [0.32, 0.45, 0.35, 0.49], "file": "local:btn:W99:0"}
            win = {"name": "W99 Crafting", "kind": "Fenster / Bereich", "roi": [0.2, 0.2, 0.8, 0.8],
                   "opened_by_id": "local:btn:W99:0", "file": "local:win:W99:0"}
            save_local(local, [row, btn, win])
            save_local(local, [dict(win, roi=[0.21, 0.2, 0.8, 0.8])])        # same ID: replace
            self.assertEqual(len(load_local(local)), 3)
            m = UiMap.load(local=local)
            self.assertEqual(len(m.entries), len(base.entries) + 3)
            self.assertIn("W99 Crafting", [w["name"] for w in m.targets()])
            self.assertEqual(m.opener_of(m.container("W99 Crafting"))["name"], "W99 · Platz 1")
            self.assertIs(m.window_for(m.by_id("local:btn:W99:0")), m.container("W99 Crafting"))

    def test_bundled_wins_over_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "uimap_local.json"
            base = UiMap.load(local=local)
            first = base.entries[0]
            save_local(local, [dict(first, name="Überschrieben")])
            m = UiMap.load(local=local)
            self.assertEqual(m.by_id(first["file"])["name"], first["name"])


class AvoidTest(unittest.TestCase):
    def test_avoid_icons(self):
        """Time-based modes (gates, skull W21) – don't press; don't mix them up with each other."""
        m = UiMap.load(local=Path(tempfile.gettempdir()) / "gibt_es_nicht.json")
        imgs = [m.image(e) for e in m.entries if (e.get("extra") or {}).get("avoid")]
        self.assertEqual(len(imgs), 2)
        self.assertGreater(vision.same_icon(imgs[0], imgs[0]), 0.98)
        self.assertLess(vision.same_icon(imgs[0], imgs[1]), 0.9)


class SlotLayoutTest(unittest.TestCase):
    def test_layout_from_bundled_map(self):
        m = UiMap.load(local=Path(tempfile.gettempdir()) / "gibt_es_nicht.json")
        lay = vision.SlotLayout(m, m.list_windows()[0])
        self.assertGreaterEqual(lay.count, 10)
        self.assertGreater(lay.pitch, 0.03)
        self.assertEqual(lay.index_of([lay.x0, 0.5, lay.x0 + lay.w, 0.9]), 0)
        self.assertIsNone(lay.index_of([0.78, 0.4, 0.98, 0.8]))             # wide button (TELEPORT!)
        row = next(r for r in m.rows(m.list_windows()[0]) if m.image(r) is not None)
        filled = lay.slots(m.image(row))
        self.assertGreaterEqual(len(filled), 8)                             # lobby: 11 icons
        self.assertEqual(lay.slots(np.full_like(m.image(row), 30)), [])     # empty row: no slots


if __name__ == "__main__":
    unittest.main()


class FixTitleTest(unittest.TestCase):
    def test_fix_title(self):
        from astral_monitor.knowledge import fix_title
        names = ["Otsutsuki Shrine", "Kagune Upgraid Fenster", "W13 Genos", "Index Fenster", "Fire Progression",
                 "Ki Evolution", "Flame Core", "Pets Passives"]
        self.assertEqual(fix_title("Worsutsuki Shrin", names), "Otsutsuki Shrine")
        self.assertEqual(fix_title("Cratt Genos", names), "Craft Genos")
        self.assertEqual(fix_title("AK Kagune Upgra", names), "Kagune Upgrade")
        self.assertEqual(fix_title("Ndex", names), "Index")
        # correct titles stay as they are (singular/plural, case, similar names)
        self.assertEqual(fix_title("Fire Progression", names), "Fire Progression")
        self.assertEqual(fix_title("Lion Progression", names), "Lion Progression")
        self.assertEqual(fix_title("FLAME CORES", names), "FLAME CORES")
        self.assertEqual(fix_title("Pet Passives", names), "Pet Passives")
        self.assertEqual(fix_title("Sword Banner 3", names), "Sword Banner 3")
