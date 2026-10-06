"""Download-Test mit echtem HTTP (lokaler Server): Fortschritt, Prüfsumme, Abbruch, Installer-Start."""
import hashlib
import http.server
import os
import stat
import sys
import threading
import time
import unittest
from pathlib import Path

import _env
from astral_monitor import updater
from astral_monitor.updater import ReleaseInfo, UpdateError

PAYLOAD = os.urandom(900_000)
NAME = "AnimeAstralMonitor-Setup-9.9.9.exe"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/sums":
            body = f"{hashlib.sha256(PAYLOAD).hexdigest()}  {NAME}\n".encode()
        elif self.path == "/badsums":
            body = f"{'1' * 64}  {NAME}\n".encode()
        elif self.path == "/file":
            body = PAYLOAD
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def info(self, sums="/sums"):
        return ReleaseInfo("9.9.9", "v9.9.9", "", "", self.base + "/file", NAME, len(PAYLOAD), self.base + sums)

    def test_download_with_progress_and_checksum(self):
        seen = []
        path = updater.download(self.info(), lambda d, t: seen.append((d, t)), dest_dir=Path(_env.DATA) / "http_ok")
        self.assertEqual(path.read_bytes(), PAYLOAD)
        self.assertEqual(seen[-1], (len(PAYLOAD), len(PAYLOAD)))

    def test_wrong_checksum_leaves_nothing(self):
        folder = Path(_env.DATA) / "http_bad"
        with self.assertRaises(UpdateError):
            updater.download(self.info("/badsums"), dest_dir=folder)
        self.assertEqual(list(folder.glob("*.exe*")), [])

    def test_cancel_midway(self):
        folder = Path(_env.DATA) / "http_cancel"
        calls = {"n": 0}

        def cancel():
            calls["n"] += 1
            return calls["n"] > 1
        with self.assertRaises(UpdateError):
            updater.download(self.info(), cancelled=cancel, dest_dir=folder)
        self.assertEqual(list(folder.glob("*.exe*")), [])

    @unittest.skipIf(sys.platform == "win32", "Skript-Installer nur unter Linux/macOS")
    def test_installer_is_started_with_silent_flags(self):
        out = Path(_env.DATA) / "args.txt"
        script = Path(_env.DATA) / "fake-setup.sh"
        script.write_text(f'#!/bin/sh\necho "$@" > "{out}"\n', encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        updater.launch_installer(script, relaunch=True)
        for _ in range(50):
            if out.exists() and out.read_text().strip():
                break
            time.sleep(0.1)
        args = out.read_text().split()
        self.assertEqual(args, ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/relaunch=1"])


if __name__ == "__main__":
    unittest.main()
