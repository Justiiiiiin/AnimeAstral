"""Bundled UI map (uimap) and image recognition of the automation – without Qt, Tesseract and Roblox."""
import unittest

import _env  # noqa: F401
import numpy as np

from astral_monitor import vision
from astral_monitor.uimap import ROW, UiMap, match_row, natural, world_number


class UiMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map = UiMap.load()

    def test_map_is_bundled(self):
        self.assertTrue(self.map.entries, "astral_monitor/uimap/index.json fehlt")
        self.assertTrue(self.map.list_windows(), "no window with world rows")

    def test_every_target_has_opener(self):
        for window in self.map.targets():
            button = self.map.opener_of(window)
            self.assertIsNotNone(button, window["name"])
            self.assertNotEqual(button.get("parent"), window["name"], f"Knopf liegt im eigenen Fenster: {button}")

    def test_buttons_in_rows_have_position(self):
        for window in self.map.targets():
            button = self.map.opener_of(window)
            holder = self.map.parent(button)
            if holder is not None and holder.get("kind") == ROW:
                self.assertTrue(button.get("rel"), button["name"])

    def test_recognition_images(self):
        lw = self.map.list_windows()[0]
        self.assertIsNotNone(self.map.image(lw))
        self.assertTrue(any(self.map.image(r) is not None for r in self.map.rows(lw)))

    def test_pets_template(self):
        templates = {w["name"]: m for w, m in self.map.templates()}
        self.assertIn("Pets-Roll (Vorlage)", templates)
        roll = self.map.container("W1 Pets-Roll")
        self.assertIsNotNone(roll)
        self.assertIsNotNone(self.map.element(roll, "Auto!"))
        self.assertIsNotNone(self.map.close_element(roll))

    def test_no_personal_ids(self):
        """No webhooks or long IDs (Discord IDs have 17–20 digits) in the public map."""
        import re
        text = (self.map.base / "index.json").read_text(encoding="utf-8")
        self.assertNotIn("webhook", text.lower())
        self.assertIsNone(re.search(r"\d{15,}", text))

    def test_helpers(self):
        self.assertEqual(world_number("W12 Lion Kingdom"), 12)
        self.assertEqual(world_number("Lobby"), 0)
        self.assertIsNone(world_number("Trial Shop"))
        self.assertLess(natural("W2 Namek"), natural("W10 Hueco"))
        rows = [{"name": "Lobby"}, {"name": "W1 Ninja Village"}, {"name": "W2 Namek City"}]
        self.assertEqual(match_row("Ninja Village", rows)["name"], "W1 Ninja Village")
        self.assertEqual(match_row("Lobby Arena", rows)["name"], "Lobby")
        self.assertIsNone(match_row("Wano Island", rows))
        self.assertTrue(vision.similar_title("Crafting", "W3 Crafting"))
        self.assertTrue(vision.similar_title("Zenkal", "Zenkai"))
        self.assertFalse(vision.similar_title("Merchant", "Ki Progression"))


class VisionTest(unittest.TestCase):
    """Put the teleporter image from the map into a Roblox window: rows and X must be found."""

    @classmethod
    def setUpClass(cls):
        cls.map = UiMap.load()
        lw = cls.map.list_windows()[0]
        img = cls.map.image(lw)
        cls.window = lw
        w, h = (lw.get("window") or [2560, 1440])
        frame = np.full((h, w, 3), 40, np.uint8)
        x0, y0 = int(lw["roi"][0] * w), int(lw["roi"][1] * h)
        frame[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img[:h - y0, :w - x0]
        cls.frame = frame
        row = next(r for r in cls.map.rows(lw) if cls.map.image(r) is not None)
        cls.rows = vision.RowFinder(row, cls.map.image(row))
        cls.menu = vision.MenuFrame(lw, img)

    def test_rows_found(self):
        rows = self.rows.find(self.frame, self.window["roi"])
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows, sorted(rows, key=lambda r: r.roi[1]))

    def test_menu_x_found(self):
        state = self.menu.state(self.frame, None)
        self.assertIsNotNone(state)
        roi, _title, x = state
        self.assertAlmostEqual(roi[0], self.window["roi"][0], places=2)
        self.assertGreater(x[0], roi[0] + 0.8 * (roi[2] - roi[0]))     # X sits at the top right

    def test_no_menu_on_empty_screen(self):
        empty = np.full_like(self.frame, 40)
        self.assertIsNone(self.menu.state(empty, None))
        self.assertEqual(self.rows.find(empty, self.window["roi"]), [])


if __name__ == "__main__":
    unittest.main()
