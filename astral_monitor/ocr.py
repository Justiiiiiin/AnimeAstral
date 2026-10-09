"""Tesseract binding: preferably directly via libtesseract (the model stays loaded), otherwise one process per reading."""
from __future__ import annotations

import ctypes
import logging
import os
import shutil
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .i18n import tr

log = logging.getLogger("ocr")


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
    y: float      # vertical center (pixels in the given image)
    x: float
    text: str


_EXE_NAMES = ("tesseract.exe", "tesseract")
_TSV_KEYS = ("level", "page_num", "block_num", "par_num", "line_num", "word_num",
             "left", "top", "width", "height", "conf", "text")


class _TessLib:
    """libtesseract directly via ctypes: no process start and no reloading of the model per reading
    (measured ~5 instead of ~65 ms per counter reading). One instance, thread-safe through a lock."""

    def __init__(self, folder: Path) -> None:
        dll = next(iter(sorted(folder.glob("libtesseract*.dll"))), None)
        tessdata = folder / "tessdata"
        if dll is None or not (tessdata / "eng.traineddata").is_file():
            raise OSError("libtesseract or eng.traineddata missing")
        if hasattr(os, "add_dll_directory"):
            self._dll_dir = os.add_dll_directory(str(folder))      # dependent DLLs are next to it
        lib = ctypes.CDLL(str(dll))
        vp, ci, cp = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p
        lib.TessBaseAPICreate.restype = vp
        lib.TessBaseAPIInit3.argtypes = [vp, cp, cp]
        lib.TessBaseAPISetPageSegMode.argtypes = [vp, ci]
        lib.TessBaseAPISetVariable.argtypes = [vp, cp, cp]
        lib.TessBaseAPISetImage.argtypes = [vp, vp, ci, ci, ci, ci]
        lib.TessBaseAPISetSourceResolution.argtypes = [vp, ci]
        lib.TessBaseAPIGetUTF8Text.argtypes = [vp]
        lib.TessBaseAPIGetUTF8Text.restype = vp
        lib.TessBaseAPIGetTsvText.argtypes = [vp, ci]
        lib.TessBaseAPIGetTsvText.restype = vp
        lib.TessBaseAPIClear.argtypes = [vp]
        lib.TessDeleteText.argtypes = [vp]
        lib.TessVersion.restype = cp
        api = lib.TessBaseAPICreate()
        # Tesseract opens the path with the ANSI code page; UTF-8 as a second try (umlauts in the user name)
        for encoding in ("mbcs" if sys.platform == "win32" else "utf-8", "utf-8"):
            try:
                path = str(tessdata).encode(encoding)
            except UnicodeEncodeError:
                continue
            if lib.TessBaseAPIInit3(api, path, b"eng") == 0:
                break
        else:
            raise OSError("Could not load the Tesseract model")
        self._lib, self._api = lib, api
        self._lock = threading.Lock()
        self.version = lib.TessVersion().decode("ascii", "replace")

    def run(self, image: np.ndarray, psm: int, whitelist: str = "", tsv: bool = False) -> str:
        img = np.ascontiguousarray(image)
        channels = 1 if img.ndim == 2 else img.shape[2]
        lib, api = self._lib, self._api
        with self._lock:
            lib.TessBaseAPISetPageSegMode(api, psm)
            lib.TessBaseAPISetVariable(api, b"tessedit_char_whitelist", whitelist.encode("ascii"))
            lib.TessBaseAPISetImage(api, img.ctypes.data, img.shape[1], img.shape[0], channels, img.strides[0])
            lib.TessBaseAPISetSourceResolution(api, 70)       # like the process call without a DPI value
            ptr = lib.TessBaseAPIGetTsvText(api, 0) if tsv else lib.TessBaseAPIGetUTF8Text(api)
            try:
                return ctypes.string_at(ptr).decode("utf-8", "replace") if ptr else ""
            finally:
                if ptr:
                    lib.TessDeleteText(ptr)
                lib.TessBaseAPIClear(api)


def _parse_tsv(text: str) -> dict[str, list]:
    """TSV from libtesseract -> the same form as pytesseract.image_to_data(..., Output.DICT)."""
    data: dict[str, list] = {key: [] for key in _TSV_KEYS}
    for row in text.splitlines():
        cols = row.split("\t")
        if len(cols) < 11 or not cols[0].isdigit():
            continue
        cols += [""] * (12 - len(cols))
        for key, value in zip(_TSV_KEYS[:11], cols[:11]):
            try:
                data[key].append(float(value) if key == "conf" else int(value))
            except ValueError:
                data[key].append(-1)
        data["text"].append(cols[11])
    return data


def bundled_dir() -> Optional[Path]:
    """Folder “tesseract” next to the program (EXE package) or in the development folder – if bundled."""
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
        # otherwise Tesseract uses several threads per call -> needless CPU
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
        try:
            import pytesseract
        except ImportError as exc:
            raise OcrError(tr("The package “pytesseract” is missing (pip install pytesseract).")) from exc

        cmd = find_tesseract(tesseract_path)
        if not cmd:
            raise OcrError(
                tr("Text recognition (Tesseract) is missing. Please reinstall the program.")
            )
        pytesseract.pytesseract.tesseract_cmd = cmd
        bundled = bundled_dir()
        if bundled is not None and Path(cmd).resolve().parent == bundled.resolve():
            os.environ.pop("TESSDATA_PREFIX", None)       # the bundled Tesseract finds its data next to itself
        self.bundled = bundled is not None and Path(cmd).resolve().parent == bundled.resolve()
        self._pt = pytesseract
        self.cmd = cmd
        self._lib: Optional[_TessLib] = None
        if sys.platform == "win32":
            try:
                self._lib = _TessLib(Path(cmd).resolve().parent)
            except (OSError, AttributeError) as exc:
                log.info("Tesseract not usable directly (%s) – using tesseract.exe per reading.", exc)
        if self._lib is not None:
            self.version = self._lib.version
            log.info("Tesseract %s direkt geladen (ohne Prozessstarts).", self.version)
            return
        try:
            self.version = str(pytesseract.get_tesseract_version())
        except Exception as exc:
            raise OcrError(tr("Tesseract cannot be started ({path}): {error}", path=cmd, error=exc)) from exc

    def line(self, image: np.ndarray, psm: int = 7, whitelist: str | None = None) -> str:
        if self._lib is not None:
            return self._lib.run(image, psm, whitelist or "").strip()
        config = f"--psm {psm}"
        if whitelist:
            config += f" -c tessedit_char_whitelist={whitelist}"
        return self._pt.image_to_string(image, config=config).strip()

    def _data(self, image: np.ndarray, psm: int) -> dict:
        if self._lib is not None:
            return _parse_tsv(self._lib.run(image, psm, tsv=True))
        return self._pt.image_to_data(image, config=f"--psm {psm}", output_type=self._pt.Output.DICT)

    def words(self, image: np.ndarray, psm: int = 6) -> list[OcrWord]:
        """All recognized words with position (pixels in the given image)."""
        data = self._data(image, psm)
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
        data = self._data(image, psm)
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
