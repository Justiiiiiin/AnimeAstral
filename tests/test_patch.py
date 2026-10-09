"""Small updates: package choice, fit check, unpacking with checksums, swap script (Windows only)."""
import hashlib
import json
import shutil
import subprocess
import sys
import time
import unittest
import zipfile
from pathlib import Path

import _env
from astral_monitor import updater
from astral_monitor.updater import UpdateError

REPO = "friend/AnimeAstral"
BASE = f"https://github.com/{REPO}/releases/download/v0.6.0/"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_app(folder: Path, files: dict) -> dict:
    if folder.exists():
        shutil.rmtree(folder)
    for rel, data in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    manifest = {"version": "0.5.0", "files": {rel: sha(data) for rel, data in files.items()}}
    (folder / "files.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


OLD = {"App.exe": b"exe-alt", "_internal/lib.dll": b"lib", "_internal/weg.dll": b"weg", "tesseract/t.dll": b"t"}
NEW = {"App.exe": b"exe-neu", "_internal/lib.dll": b"lib", "_internal/neu.pyd": b"neu", "tesseract/t.dll": b"t"}


def remote_manifest(contains=("App.exe", "_internal/neu.pyd")) -> dict:
    return {"version": "0.6.0", "files": {rel: sha(data) for rel, data in NEW.items()},
            "patch": {"base": "0.5.0", "contains": list(contains)}}


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(_env.DATA) / "patch"
        self.app = self.root / "app"
        self.local = make_app(self.app, OLD)

    def test_pick_patch_assets_only_own_repo(self):
        release = {"assets": [
            {"name": "files-0.6.0.json", "browser_download_url": BASE + "files-0.6.0.json"},
            {"name": "AnimeAstralMonitor-Update-0.6.0.zip", "browser_download_url": BASE + "AnimeAstralMonitor-Update-0.6.0.zip"},
            {"name": "AnimeAstralMonitor-Update-0.6.0.zip", "browser_download_url": "https://evil.example/x.zip"}]}
        manifest, patch = updater.pick_patch_assets(release, REPO)
        self.assertTrue(manifest["browser_download_url"].startswith(BASE))
        self.assertTrue(patch["browser_download_url"].startswith(BASE))
        self.assertEqual(updater.pick_patch_assets(release, "other/repo"), (None, None))

    def test_plan_fits(self):
        plan = updater.plan_patch(self.local, remote_manifest(), self.app)
        self.assertEqual(plan.changed, ["App.exe", "_internal/neu.pyd"])
        self.assertEqual(plan.removed, ["_internal/weg.dll"])
        self.assertNotIn("patch", plan.manifest)

    def test_plan_rejects_when_package_incomplete_or_unsafe(self):
        self.assertIsNone(updater.plan_patch(self.local, remote_manifest(contains=("App.exe",)), self.app))
        no_patch = remote_manifest()
        del no_patch["patch"]
        self.assertIsNone(updater.plan_patch(self.local, no_patch, self.app))
        self.assertIsNone(updater.plan_patch(None, remote_manifest(), self.app))
        evil = remote_manifest(contains=("App.exe", "_internal/neu.pyd", "../boese.exe"))
        evil["files"]["../boese.exe"] = sha(b"x")
        self.assertIsNone(updater.plan_patch(self.local, evil, self.app))
        (self.app / "tesseract/t.dll").unlink()                 # unchanged file missing -> full install
        self.assertIsNone(updater.plan_patch(self.local, remote_manifest(), self.app))

    def _zip(self, members: dict) -> Path:
        path = self.root / "update.zip"
        with zipfile.ZipFile(path, "w") as zf:
            for rel, data in members.items():
                zf.writestr(rel, data)
        return path

    def test_stage_checks_every_file(self):
        plan = updater.plan_patch(self.local, remote_manifest(), self.app)
        work = self.root / "work"
        staging = updater.stage_patch(self._zip({"App.exe": NEW["App.exe"], "_internal/neu.pyd": NEW["_internal/neu.pyd"],
                                                 "extra.exe": b"wird ignoriert"}), plan, work)
        self.assertEqual((staging / "App.exe").read_bytes(), NEW["App.exe"])
        self.assertFalse((staging / "extra.exe").exists())
        self.assertEqual(json.loads((staging / "files.json").read_text())["version"], "0.6.0")
        with self.assertRaises(UpdateError):
            updater.stage_patch(self._zip({"App.exe": b"manipuliert", "_internal/neu.pyd": NEW["_internal/neu.pyd"]}),
                                plan, work)
        self.assertFalse((work / "staging").exists())

    def test_cleanup_downloads(self):
        folder = self.root / "updates"
        (folder / "apply" / "staging").mkdir(parents=True)
        for name in ("AnimeAstralMonitor-Setup-0.5.2.exe", "AnimeAstralMonitor-Update-0.5.3.zip", "x.zip.part",
                     "apply/plan.json", "apply/apply.ps1", "apply/apply.log"):
            (folder / name).write_bytes(b"x")
        self.assertEqual(updater.cleanup_downloads(folder), 5)
        self.assertEqual(sorted(p.name for p in folder.rglob("*") if p.is_file()), ["apply.log"])   # log stays
        self.assertFalse((folder / "apply" / "staging").exists())

    @unittest.skipUnless(sys.platform == "win32", "swap script only on Windows")
    def test_apply_script_replaces_and_rolls_back(self):
        plan = updater.plan_patch(self.local, remote_manifest(), self.app)
        zip_path = self._zip({"App.exe": NEW["App.exe"], "_internal/neu.pyd": NEW["_internal/neu.pyd"]})
        done = subprocess.Popen([sys.executable, "-c", "pass"])
        done.wait()                                              # “program” has already ended

        def run(work: Path) -> None:
            plan_file = updater.launch_patch(zip_path, plan, relaunch=False, folder=self.app, work=work, pid=done.pid)
            for _ in range(200):                                 # script runs in the background
                if (work / "apply.log").exists() and not (work / "staging").exists():
                    break
                time.sleep(0.1)
            self.assertTrue(plan_file.exists())

        run(self.root / "ok")
        self.assertEqual((self.app / "App.exe").read_bytes(), NEW["App.exe"])
        self.assertTrue((self.app / "_internal/neu.pyd").exists())
        self.assertFalse((self.app / "_internal/weg.dll").exists())
        self.assertEqual(json.loads((self.app / "files.json").read_text())["version"], "0.6.0")
        self.assertIn("installiert", (self.root / "ok" / "apply.log").read_text(encoding="utf-8-sig"))

        # error case: the target of a new subfolder is a file -> copying fails -> old state restored
        self.local = make_app(self.app, OLD)
        plan = updater.plan_patch(self.local, remote_manifest(), self.app)
        (self.app / "_internal").rename(self.app / "_internal_tmp")
        (self.app / "_internal").write_bytes(b"blockiert")       # “_internal” is now a file
        run(self.root / "bad")
        self.assertIn("FEHLER", (self.root / "bad" / "apply.log").read_text(encoding="utf-8-sig"))
        self.assertEqual((self.app / "App.exe").read_bytes(), OLD["App.exe"])
        self.assertEqual(json.loads((self.app / "files.json").read_text())["version"], "0.5.0")


if __name__ == "__main__":
    unittest.main()
