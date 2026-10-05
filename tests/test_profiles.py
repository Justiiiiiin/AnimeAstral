import json
import unittest
import zipfile
from pathlib import Path

import cv2
import numpy as np

import _env
from astral_monitor.profiles import ProfileStore


def image():
    rng = np.random.default_rng(1)
    return rng.integers(0, 255, (240, 400, 3), dtype=np.uint8)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        base = Path(_env.DATA) / self.id().split(".")[-1]
        self.a, self.b = ProfileStore(base / "a"), ProfileStore(base / "b")
        self.a.create("Militech Convoy")
        self.a.add_image("Militech Convoy", image())
        self.a.save_settings("Militech Convoy", {"trigger_offset": 2, "note": "Boss bei 27"})
        self.zip = base / "x.astralprofile"

    def test_export_import_roundtrip(self):
        self.a.export_zip("Militech Convoy", self.zip)
        name = self.b.import_zip(self.zip)
        self.assertEqual(name, "Militech Convoy")
        self.assertEqual(len(self.b.images(name)), 1)
        self.assertEqual(self.b.settings(name)["trigger_offset"], 2)
        self.assertEqual(self.b.import_zip(self.zip), "Militech Convoy 2")

    def test_bad_files_are_rejected_cleanly(self):
        good = json.dumps({"format": "astral-profile-1", "name": "X"})
        cases = {"leer": [("profile.json", good)],
                 "fremd": [("profile.json", json.dumps({"format": "fremd"})), ("ref_01.jpg", b"x")],
                 "kaputtes bild": [("profile.json", good), ("ref_01.jpg", b"kein jpg")]}
        for label, entries in cases.items():
            path = Path(_env.DATA) / f"{self.id()}_{label}.zip"
            with zipfile.ZipFile(path, "w") as z:
                for k, v in entries:
                    z.writestr(k, v)
            with self.assertRaises(ValueError, msg=label):
                self.b.import_zip(path)
        self.assertEqual(self.b.names(), [])

    def test_not_a_zip(self):
        path = Path(_env.DATA) / "kein.zip"
        path.write_bytes(b"nope")
        with self.assertRaises(ValueError):
            self.b.import_zip(path)


if __name__ == "__main__":
    unittest.main()
