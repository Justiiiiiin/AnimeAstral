"""Tesseract-Anbindung (ein Prozessaufruf pro Lesung, daher sparsam einsetzen)."""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


class OcrError(RuntimeError):
    pass


@dataclass
class OcrWord:
    text: str
    x: float
    y: float
    w: float
    h: float
    conf: float


@dataclass
class OcrLine:
    y: float      # vertikale Mitte (Pixel im übergebenen Bild)
    x: float
    text: str


_EXE_NAMES = ("tesseract.exe", "tesseract")


def bundled_dir() -> Optional[Path]:
    """Ordner „tesseract“ neben dem Programm (EXE-Paket) oder im Entwicklungsordner – falls mitgeliefert."""
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots += [Path(sys.executable).resolve().parent, Path(getattr(sys, "_MEIPASS", "."))]
    roots.append(Path(__file__).resolve().parent.parent)
    for root in roots:
        folder = root / "tesseract"
        if any((folder / name).is_file() for name in _EXE_NAMES):
            return folder
    return None


def find_tesseract(user_path: str = "") -> str:
    candidates: list[str] = []
    if user_path.strip():
        candidates.append(user_path.strip().strip('"'))
    bundled = bundled_dir()
    if bundled is not None:
        candidates += [str(bundled / name) for name in _EXE_NAMES]
    which = shutil.which("tesseract")
    if which:
        candidates.append(which)
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(str(Path(base) / "Tesseract-OCR" / "tesseract.exe"))
            candidates.append(str(Path(base) / "Programs" / "Tesseract-OCR" / "tesseract.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return ""


class OcrEngine:
    def __init__(self, tesseract_path: str = "") -> None:
        # Tesseract nutzt sonst mehrere Threads pro Aufruf -> unnötig viel CPU
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
        try:
            import pytesseract
        except ImportError as exc:
            raise OcrError("Das Paket „pytesseract“ fehlt (pip install pytesseract).") from exc

        cmd = find_tesseract(tesseract_path)
        if not cmd:
            raise OcrError(
                "Tesseract-OCR wurde nicht gefunden. Installiere es (Windows-Installer) "
                "oder trage den Pfad zur tesseract.exe unter „Erkennung“ ein."
            )
        pytesseract.pytesseract.tesseract_cmd = cmd
        bundled = bundled_dir()
        if bundled is not None and Path(cmd).resolve().parent == bundled.resolve():
            os.environ.pop("TESSDATA_PREFIX", None)       # mitgeliefertes Tesseract findet seine Daten neben sich selbst
        self.bundled = bundled is not None and Path(cmd).resolve().parent == bundled.resolve()
        try:
            self.version = str(pytesseract.get_tesseract_version())
        except Exception as exc:
            raise OcrError(f"Tesseract lässt sich nicht starten ({cmd}): {exc}") from exc
        self._pt = pytesseract
        self.cmd = cmd

    def line(self, image: np.ndarray, psm: int = 7, whitelist: str | None = None) -> str:
        config = f"--psm {psm}"
        if whitelist:
            config += f" -c tessedit_char_whitelist={whitelist}"
        return self._pt.image_to_string(image, config=config).strip()

    def words(self, image: np.ndarray, psm: int = 6) -> list[OcrWord]:
        """Alle erkannten Wörter mit Position (Pixel im übergebenen Bild)."""
        data = self._pt.image_to_data(image, config=f"--psm {psm}", output_type=self._pt.Output.DICT)
        out: list[OcrWord] = []
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if text and conf >= 0:
                out.append(OcrWord(text, float(data["left"][i]), float(data["top"][i]),
                                   float(data["width"][i]), float(data["height"][i]), conf))
        return out

    def lines(self, image: np.ndarray, psm: int = 6) -> list[OcrLine]:
        data = self._pt.image_to_data(image, config=f"--psm {psm}",
                                      output_type=self._pt.Output.DICT)
        groups: dict[tuple, list] = {}
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            groups.setdefault(key, []).append(
                (data["left"][i], data["top"][i], data["height"][i], text))
        out: list[OcrLine] = []
        for items in groups.values():
            items.sort(key=lambda t: t[0])
            y = sum(t[1] + t[2] / 2 for t in items) / len(items)
            out.append(OcrLine(y=y, x=float(items[0][0]), text=" ".join(t[3] for t in items)))
        out.sort(key=lambda ln: ln.y)
        return out
