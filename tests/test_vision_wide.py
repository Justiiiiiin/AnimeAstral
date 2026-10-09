"""Wide X search (smaller windows): the fast coarse-to-fine search finds the same X as a full search."""
import unittest

import _env  # noqa: F401
import cv2
import numpy as np

from astral_monitor import vision


def _full_search(area, tpl):
    best = (0.0, 1.0, (0, 0))
    for s in vision.WIDE_SCALES:
        t = vision._scaled(tpl, s)
        _a, score, _b, loc = cv2.minMaxLoc(cv2.matchTemplate(area, t, cv2.TM_CCOEFF_NORMED))
        if score > best[0]:
            best = (score, s, loc)
    return best


class WideSearchTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        # textured background (like the game scene) and an X-like template: pink circle with a white cross
        self.area = cv2.GaussianBlur(rng.integers(0, 255, (700, 1300, 3), dtype=np.uint8), (9, 9), 0)
        tpl = np.zeros((60, 60, 3), np.uint8)
        cv2.circle(tpl, (30, 30), 27, (150, 60, 230), -1)
        cv2.line(tpl, (18, 18), (42, 42), (255, 255, 255), 6)
        cv2.line(tpl, (42, 18), (18, 42), (255, 255, 255), 6)
        self.tpl = tpl

    def test_same_hit_as_full_search(self):
        for s, (x, y) in ((0.8, (100, 80)), (1.0, (900, 400)), (1.2, (600, 50)), (0.9, (1200, 600))):
            area = self.area.copy()
            t = vision._scaled(self.tpl, s)
            h, w = t.shape[:2]
            x, y = min(x, area.shape[1] - w), min(y, area.shape[0] - h)
            area[y:y + h, x:x + w] = t
            score, scale, loc, _size = vision._wide_x_search(area, self.tpl)
            full = _full_search(area, self.tpl)
            self.assertGreater(score, 0.95)
            self.assertEqual(scale, full[1])
            self.assertLessEqual(abs(loc[0] - full[2][0]) + abs(loc[1] - full[2][1]), 2)

    def test_nothing_there(self):
        score = vision._wide_x_search(self.area, self.tpl)[0]
        self.assertLess(score, vision.X_WIDE_SOFT)


if __name__ == "__main__":
    unittest.main()
