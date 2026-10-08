"""Debug-Ansicht (ohne Qt): sammelt – nur solange eingeschaltet – jede Protokollzeile des Programms, also genau das,
was auch in monitor.log bzw. im Diagnose-Paket steht (Überwachung, Makro, Erkunden, Anti-AFK, Rejoin, Fehler …).
Aus = kein Handler am Logger, nichts wird gesammelt (spart Ressourcen)."""
from __future__ import annotations

import collections
import logging
import threading
from pathlib import Path
from typing import Optional

KEEP = 1500                       # so viele Zeilen hält die Ansicht höchstens
FORMAT = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")


class DebugBuffer(logging.Handler):
    """Ringpuffer für Protokollzeilen; thread-sicher (Engine, Makro und Oberfläche loggen aus eigenen Threads)."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.setFormatter(FORMAT)
        self._lines: "collections.deque[tuple[int, str, str]]" = collections.deque(maxlen=KEEP)
        self._seq = 0
        self._lock = threading.Lock()
        self.enabled = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
        except Exception:  # noqa: BLE001 – Protokoll darf nie stören
            return
        self.add(text, record.levelname)

    def add(self, text: str, level: str = "INFO") -> None:
        with self._lock:
            self._seq += 1
            self._lines.append((self._seq, level, text))

    def since(self, seq: int) -> list[tuple[int, str, str]]:
        """Zeilen nach seq (für die Anzeige: nur Neues abholen)."""
        with self._lock:
            return [line for line in self._lines if line[0] > seq]

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()

    def text(self) -> str:
        with self._lock:
            return "\n".join(line for _s, _l, line in self._lines)

    def enable(self, on: bool, log_file: Optional[Path] = None, tail: int = 300) -> None:
        """An: an den Logger hängen und die letzten Zeilen aus monitor.log vorladen. Aus: abhängen, leeren."""
        root = logging.getLogger()
        if on and not self.enabled:
            self.clear()
            if log_file is not None:
                for line in tail_lines(log_file, tail):
                    self.add(line, level_of(line))
            root.addHandler(self)
        elif not on and self.enabled:
            root.removeHandler(self)
            self.clear()
        self.enabled = on


def level_of(line: str) -> str:
    for level in ("ERROR", "CRITICAL", "WARNING", "DEBUG"):
        if f"[{level}]" in line:
            return level
    return "INFO"


def tail_lines(path: Path, count: int) -> list[str]:
    """Letzte count Zeilen einer Textdatei (liest nur das Ende)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 256 * 1024))
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = [ln for ln in data.splitlines() if ln.strip()]
    if size > 256 * 1024:
        lines = lines[1:]                                 # erste Zeile ist evtl. angeschnitten
    return lines[-count:]


BUFFER = DebugBuffer()
