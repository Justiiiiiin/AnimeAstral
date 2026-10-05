import hashlib
import unittest
from pathlib import Path

import requests

import _env
from astral_monitor import updater
from astral_monitor.updater import ReleaseInfo, UpdateError

REPO = "friend/AnimeAstral"
BASE = f"https://github.com/{REPO}/releases/download/v0.6.0/"
RELEASE = {"tag_name": "v0.6.0", "body": "Neu: Dinge", "html_url": f"https://github.com/{REPO}/releases/tag/v0.6.0",
           "assets": [{"name": "AnimeAstralMonitor-Setup-0.6.0.exe", "browser_download_url": BASE + "AnimeAstralMonitor-Setup-0.6.0.exe", "size": 300000},
                      {"name": "SHA256SUMS.txt", "browser_download_url": BASE + "SHA256SUMS.txt", "size": 100},
                      {"name": "Boese.exe", "browser_download_url": "https://evil.example/Boese.exe", "size": 1}]}


class Resp:
    def __init__(self, code=200, data=None, text="", content=b"", headers=None):
        self.status_code, self._data, self.text, self.content, self.headers = code, data, text, content, headers or {}

    def json(self):
        if self._data is None:
            raise ValueError("kein JSON")
        return self._data

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class UpdaterTests(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(updater.is_newer("0.10.0", "0.9.9"))
        self.assertFalse(updater.is_newer("0.5.0", "0.5.0"))
        self.assertFalse(updater.is_newer("0.4.9", "0.5.0"))
        self.assertTrue(updater.is_newer("v1.0", "0.9.9".lstrip("v")))

    def test_due(self):
        self.assertTrue(updater.due(0.0, 10 * 3600))
        self.assertFalse(updater.due(100.0, 100.0 + 3600))

    def test_pick_assets_ignores_foreign_urls(self):
        installer, sha = updater.pick_assets(RELEASE, REPO)
        self.assertEqual(installer["name"], "AnimeAstralMonitor-Setup-0.6.0.exe")
        self.assertEqual(sha["name"], "SHA256SUMS.txt")
        self.assertEqual(updater.pick_assets(RELEASE, "other/repo"), (None, None))

    def test_check_latest_variants(self):
        info = updater.check_latest(REPO, getter=lambda *a, **k: Resp(200, RELEASE))
        self.assertEqual((info.version, info.tag), ("0.6.0", "v0.6.0"))
        self.assertIsNone(updater.check_latest(REPO, getter=lambda *a, **k: Resp(404)))
        no_asset = dict(RELEASE, assets=[])
        self.assertIsNone(updater.check_latest(REPO, getter=lambda *a, **k: Resp(200, no_asset)))
        with self.assertRaises(UpdateError):
            updater.check_latest(REPO, getter=lambda *a, **k: Resp(500))
        with self.assertRaises(UpdateError):
            updater.check_latest("kaputt", getter=lambda *a, **k: Resp(200, RELEASE))

        def boom(*a, **k):
            raise requests.ConnectionError("offline")
        with self.assertRaises(UpdateError):
            updater.check_latest(REPO, getter=boom)

    def test_expected_sha_formats(self):
        h = "a" * 64
        self.assertEqual(updater.expected_sha(f"{h}  Datei.exe\n", "Datei.exe"), h)
        self.assertEqual(updater.expected_sha(f"{h.upper()} *Datei.exe", "Datei.exe"), h)
        self.assertIsNone(updater.expected_sha(f"{h}  andere.exe", "Datei.exe"))

    def _info(self):
        return ReleaseInfo("0.6.0", "v0.6.0", "", "", BASE + "AnimeAstralMonitor-Setup-0.6.0.exe",
                           "AnimeAstralMonitor-Setup-0.6.0.exe", 300000, BASE + "SHA256SUMS.txt")

    def test_download_verifies_checksum(self):
        payload = b"X" * 300000
        good = hashlib.sha256(payload).hexdigest()
        seen = []

        def getter(url, **kw):
            if url.endswith("SHA256SUMS.txt"):
                return Resp(200, text=f"{good}  AnimeAstralMonitor-Setup-0.6.0.exe\n")
            return Resp(200, content=payload, headers={"Content-Length": str(len(payload))})

        path = updater.download(self._info(), lambda d, t: seen.append((d, t)), getter=getter,
                                dest_dir=Path(_env.DATA) / "ok")
        self.assertEqual(path.read_bytes(), payload)
        self.assertEqual(seen[-1][0], len(payload))

    def test_download_rejects_wrong_checksum_and_cancel(self):
        payload = b"X" * 300000

        def bad(url, **kw):
            if url.endswith("SHA256SUMS.txt"):
                return Resp(200, text=f"{'0' * 64}  AnimeAstralMonitor-Setup-0.6.0.exe\n")
            return Resp(200, content=payload)
        folder = Path(_env.DATA) / "bad"
        with self.assertRaises(UpdateError):
            updater.download(self._info(), getter=bad, dest_dir=folder)
        self.assertEqual(list(folder.glob("*.exe*")), [])               # nichts bleibt liegen

        with self.assertRaises(UpdateError):
            updater.download(self._info(), cancelled=lambda: True, getter=bad, dest_dir=folder)
        self.assertEqual(list(folder.glob("*.exe*")), [])


if __name__ == "__main__":
    unittest.main()
