"""Debug-Ansicht: sammelt nur, solange eingeschaltet; lädt das Ende von monitor.log vor."""
import logging
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401

from astral_monitor.debuglog import DebugBuffer, level_of, tail_lines


class DebugBufferTest(unittest.TestCase):
    def test_collects_only_while_enabled(self):
        buf = DebugBuffer()
        log = logging.getLogger("test.debug")
        log.setLevel(logging.INFO)
        log.info("vorher")
        self.assertEqual(buf.since(0), [])
        buf.enable(True)
        log.warning("Makro: Öffne „Teleporter“.")
        lines = buf.since(0)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][1], "WARNING")
        self.assertIn("test.debug: Makro", lines[0][2])
        self.assertEqual(buf.since(lines[0][0]), [])
        buf.enable(False)
        log.info("nachher")
        self.assertEqual(buf.since(0), [])
        self.assertNotIn(buf, logging.getLogger().handlers)

    def test_preload_from_log_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "monitor.log"
            f.write_text("".join(f"10:00:{i:02d} [INFO] engine: Zeile {i}\n" for i in range(50)) +
                         "10:01:00 [ERROR] engine: kaputt\n", encoding="utf-8")
            self.assertEqual(len(tail_lines(f, 10)), 10)
            buf = DebugBuffer()
            buf.enable(True, f, tail=5)
            lines = buf.since(0)
            buf.enable(False)
            self.assertEqual(len(lines), 5)
            self.assertEqual(lines[-1][1], "ERROR")
        self.assertEqual(level_of("x [WARNING] y"), "WARNING")
        self.assertEqual(tail_lines(Path("gibt/es/nicht.log"), 5), [])


if __name__ == "__main__":
    unittest.main()
