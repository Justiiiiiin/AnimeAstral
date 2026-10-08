"""Erkunden: Fenster-Einordnung (knowledge), lokale Ergänzung der Karte, Symbol-Plätze – ohne Qt/Tesseract/Roblox."""
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401
import numpy as np

from astral_monitor import knowledge, vision
from astral_monitor.uimap import UiMap, load_local, save_local


def W(*texts):
    """Wörter mit Dummy-Lage (untereinander)."""
    return [(t, [0.4, 0.1 + i * 0.05, 0.5, 0.13 + i * 0.05]) for i, t in enumerate(texts)]


class ClassifyTest(unittest.TestCase):
    """Wortlisten wie an den echten Aufnahmen gelesen (07.10.2026)."""

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
        """Aus dem ersten echten Erkunden: Quests erwähnen Raids, sind aber Quests."""
        quests = W("Glo", "ests", "AUTO", "CLAIM", "Complete", "MaxTac", "Call", "times", "Join", "Timeless", "Raid")
        a = knowledge.classify("Global Quests", quests)
        self.assertEqual(a.category, "quests")
        self.assertEqual(len(knowledge.claimables(quests)), 1)
        self.assertEqual(knowledge.classify("Inventory", W("Rarity", "Key")).category, "inventory")
        self.assertEqual(knowledge.classify("Achievements", W("Claim", "Veteran")).category, "achievements")

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
            save_local(local, [dict(win, roi=[0.21, 0.2, 0.8, 0.8])])        # gleiche Kennung: ersetzen
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
        """Zeitbasierte Modi (Gates, Totenkopf W21) – nicht drücken; untereinander nicht verwechseln."""
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
        self.assertIsNone(lay.index_of([0.78, 0.4, 0.98, 0.8]))             # breiter Knopf (TELEPORT!)
        row = next(r for r in m.rows(m.list_windows()[0]) if m.image(r) is not None)
        filled = lay.slots(m.image(row))
        self.assertGreaterEqual(len(filled), 8)                             # Lobby: 11 Symbole
        self.assertEqual(lay.slots(np.full_like(m.image(row), 30)), [])     # leere Zeile: keine Plätze


if __name__ == "__main__":
    unittest.main()
