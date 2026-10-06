import json
import unittest
import zipfile
from pathlib import Path

import cv2
import numpy as np

import _env
from astral_monitor.profiles import ProfileStore, RaidMatcher


def image():
    rng = np.random.default_rng(1)
    return rng.integers(0, 255, (240, 400, 3), dtype=np.uint8)


def texture(seed, h, w, block, lo, hi):
    """Blockmuster (statt Pixelrauschen, damit ORB stabile Merkmale findet)."""
    rng = np.random.default_rng(seed)
    small = rng.integers(lo, hi, (h // block, w // block, 3), dtype=np.uint8)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def scene(map_seed, army_seed, army_w=0.36):
    """Wie im Spiel: kontrastarmer Boden als Map, detailreiche Armee unten in der Mitte. Ohne Ausblenden/Filtern
    findet der Vergleich fast nur die Armee (geprüft: alte Methode entscheidet hier nicht oder falsch)."""
    img = texture(map_seed, 480, 960, 24, 90, 140)
    h, w = img.shape[:2]
    x0, x1 = int((0.5 - army_w / 2) * w), int((0.5 + army_w / 2) * w)
    img[int(0.35 * h):, x0:x1] = texture(army_seed, h - int(0.35 * h), x1 - x0, 6, 0, 255)
    return img


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

    def test_pack_roundtrip_skips_existing(self):
        self.a.create("Alvarez War")
        self.a.add_image("Alvarez War", image())
        self.a.add_image("Alvarez War", image())
        pack = Path(_env.DATA) / f"{self.id()}.astralpack"
        path, count = self.a.export_pack(pack)
        self.assertEqual(count, 2)
        self.b.create("Alvarez War")                          # Freund hat diesen Raid schon
        imported, skipped = self.b.import_pack(path)
        self.assertEqual(imported, ["Militech Convoy"])
        self.assertEqual(skipped, ["Alvarez War"])
        self.assertEqual(self.b.settings("Militech Convoy")["note"], "Boss bei 27")
        self.assertEqual(self.b.import_pack(path), ([], ["Alvarez War", "Militech Convoy"]))   # zweimal: nichts doppelt

    def test_pack_with_broken_profile_imports_the_rest(self):
        pack = Path(_env.DATA) / f"{self.id()}.astralpack"
        good = cv2.imencode(".jpg", image())[1].tobytes()
        with zipfile.ZipFile(pack, "w") as z:
            z.writestr("pack.json", json.dumps({"format": "astral-pack-1", "profiles": ["Gut", "Kaputt", "../Boese"]}))
            z.writestr("Gut/ref_01.jpg", good)
            z.writestr("Kaputt/ref_01.jpg", b"kein jpg")
            z.writestr("../Boese/ref_01.jpg", good)
        imported, skipped = self.b.import_pack(pack)
        self.assertEqual(imported, ["Gut"])
        self.assertTrue(skipped[0].startswith("Kaputt"))
        self.assertTrue(skipped[1].startswith("Boese"))                         # Pfad mit „..“ abgelehnt
        self.assertEqual(self.b.names(), ["Gut"])                               # nichts außerhalb des Ordners
        self.a.export_zip("Militech Convoy", self.zip)           # einzelnes Profil ist kein Paket
        with self.assertRaises(ValueError):
            self.b.import_pack(self.zip)

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

    def test_same_army_on_different_maps_is_not_confused(self):
        # Referenzbilder: zwei Maps, beide mit DERSELBEN Armee (so entstanden „Alvarez War“/„Holy Grail War“-Verwechslungen)
        store = ProfileStore(Path(_env.DATA) / "maps")
        for name, map_seed in (("Alvarez War", 10), ("Holy Grail War", 20)):
            store.create(name)
            store.add_image(name, scene(map_seed, army_seed=99))
        m = RaidMatcher(store, 14)
        self.assertEqual(m.decide(m.score(scene(10, army_seed=99))), "Alvarez War")
        # Freund mit anderer, größerer Armee
        scores = m.score(scene(20, army_seed=7, army_w=0.55))
        self.assertEqual(m.decide(scores), "Holy Grail War", scores)

    def test_reload_async_keeps_old_state_until_done(self):
        m = RaidMatcher(self.a, 14, load=False)
        self.assertFalse(m.has_profiles)
        m.reload_async()
        for _ in range(100):
            if not m.loading:
                break
            import time
            time.sleep(0.05)
        self.assertTrue(m.has_profiles)

    def test_not_a_zip(self):
        path = Path(_env.DATA) / "kein.zip"
        path.write_bytes(b"nope")
        with self.assertRaises(ValueError):
            self.b.import_zip(path)


if __name__ == "__main__":
    unittest.main()
