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


class ReleaseListTests(unittest.TestCase):
    def test_list_sorted_and_filtered(self):
        def rel(tag, **extra):
            data = {k: v for k, v in RELEASE.items() if k != "tag_name"}
            data.update(tag_name=tag, published_at="2026-10-06T12:00:00Z", **extra)
            return data
        no_installer = rel("v0.5.5")
        no_installer["assets"] = []
        listing = [rel("v0.5.2"), rel("v0.6.10"), rel("v0.6.9"), rel("v0.7.0-beta", prerelease=True),
                   rel("v0.8.0", draft=True), no_installer]
        out = updater.list_releases(REPO, getter=lambda *a, **k: Resp(200, listing))
        self.assertEqual([r.version for r in out], ["0.6.10", "0.6.9", "0.5.2"])     # numerisch, nicht als Text
        self.assertEqual(out[0].published, "2026-10-06T12:00:00Z")
        self.assertEqual(updater.list_releases(REPO, getter=lambda *a, **k: Resp(404)), [])

    def test_beta_channel(self):
        def rel(tag, **extra):
            data = {k: v for k, v in RELEASE.items() if k != "tag_name"}
            data.update(tag_name=tag, **extra)
            return data
        listing = [rel("v0.7.1"), rel("v0.7.2-beta.2", prerelease=True), rel("v0.7.2-beta.10", prerelease=True)]
        get = lambda *a, **k: Resp(200, listing)                                     # noqa: E731
        self.assertEqual(updater.check_latest(REPO, getter=get, beta=True).version, "0.7.2-beta.10")
        self.assertTrue(updater.check_latest(REPO, getter=get, beta=True).prerelease)
        self.assertEqual([r.version for r in updater.list_releases(REPO, getter=get)], ["0.7.1"])
        self.assertEqual(len(updater.list_releases(REPO, getter=get, beta=True)), 3)

    def test_beta_version_order(self):
        order = ["0.7.1", "0.7.2-beta.1", "0.7.2-beta.2", "0.7.2-beta.10", "0.7.2", "0.7.3-beta.1", "0.8"]
        self.assertEqual(sorted(reversed(order), key=updater.version_key), order)
        self.assertTrue(updater.is_newer("0.7.2", "0.7.2-beta.3"))           # Beta -> stabile Version
        self.assertFalse(updater.is_newer("0.7.2-beta.1", "0.7.2"))
        self.assertEqual(updater.version_key("0.7"), updater.version_key("0.7.0"))

    def test_beta_notes_section(self):
        import importlib.util
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location("release_notes", root / "tools" / "release_notes.py")
        notes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(notes)
        text = "## 0.7.2-beta.1\n- Beta\n## 0.7.2\n- Stabil\n"
        self.assertEqual(notes.section("0.7.2", text), "- Stabil")
        self.assertEqual(notes.section("v0.7.2-beta.1", text), "- Beta")


class ChangelogTests(unittest.TestCase):
    def test_every_version_has_short_notes(self):
        import importlib.util
        import re
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location("release_notes", root / "tools" / "release_notes.py")
        notes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(notes)
        from astral_monitor.version import __version__
        body = notes.section(__version__)
        self.assertIsNotNone(body, f"CHANGELOG.md braucht einen Abschnitt „## {__version__}“")
        for line in body.splitlines():                     # Stichpunkte statt Erklärungen
            if line.startswith("- "):
                self.assertLessEqual(len(line), 70, line)
        self.assertIsNone(notes.section("9.9.9", "## 1.0\n- x\n"))
        self.assertEqual(notes.section("1.0", "## 1.0\n### Neu\n- x\n## 0.9\n- y\n"), "#### Neu\n- x")
        self.assertTrue(re.search(r"^## 0\.5\.0", (root / "CHANGELOG.md").read_text(encoding="utf-8"), re.M))


class WhatsNewTests(unittest.TestCase):
    def test_highlights_and_when(self):
        from astral_monitor import changelog
        from astral_monitor.version import __version__
        text = "## 1.0.0\n\n### ✨ Neu\n- A\n- B\n\n### 🐞 Behoben\n- C\n\n## 0.9.0\n- alt\n"
        self.assertEqual(changelog.highlights("1.0.0", 2, text), ["A", "B"])
        self.assertEqual(changelog.highlights("1.0.0", 9, text), ["A", "B", "C"])
        self.assertTrue(changelog.highlights(__version__))              # mitgelieferte CHANGELOG.md hat die Version
        from astral_monitor.ui.whats_new import should_show
        self.assertTrue(should_show("0.7.5", True))                      # Update
        self.assertFalse(should_show(__version__, True))                 # schon gesehen
        self.assertFalse(should_show("", False))                         # Neuinstallation
