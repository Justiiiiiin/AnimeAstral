"""Quest-Liste (oben rechts) per OCR lesen: Titel + Fortschritt „7330/75000“."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .imaging import PAD, near_white_mask, ocr_input_mask, ocr_input_threshold, to_gray
from .ocr import OcrEngine

SCALE = 3
_PROG_RE = re.compile(r"(\d[\d .,]*)\s*[/|]\s*(\d[\d .,]*)")
_ZERO_F_RE = re.compile(r"^[0OQo]\s*[fF]\s*(\d[\d .,]*)$")   # Tesseract liest "0/90" manchmal als "Of 90"


@dataclass
class QuestLine:
    title: str
    cur: Optional[int]
    total: Optional[int]


def _num(text: str) -> Optional[int]:
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


_ONE_RE = re.compile(r"(?<!\d)[lI!|](?=\s*/\s*\d)")        # „1/90“ wird gern als „l/90“ oder „I/90“ gelesen
_TIMES_RE = re.compile(r"\s+t(?:i(?:m(?:e(?:s|\(s?\)?)?)?)?)?$", re.IGNORECASE)   # „time(s)“, auch abgeschnitten


def parse_progress(text: str) -> Optional[tuple[int, int]]:
    text = _ONE_RE.sub("1", text.strip())
    match = _PROG_RE.search(text)
    if match:
        cur, tot = _num(match.group(1)), _num(match.group(2))
        if cur is not None and tot:
            return cur, tot
    match = _ZERO_F_RE.match(text)
    if match:
        tot = _num(match.group(1))
        if tot:
            return 0, tot
    return None


def clean_title(text: str, names: tuple = ()) -> str:
    """Titel säubern: Reste am Fensterrand und „time(s)“ weg, Wörter nach der Zahl bleiben („Clear 8000 waves in
    MaxTac Ca“). Bekannte Raid-Namen werden repariert, wenn die Erkennung sie zerteilt („Conv oy“ -> „Convoy“)."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[^\w)]+$", "", text)
    text = _TIMES_RE.sub("", text)
    last = max((i for i, ch in enumerate(text) if ch.isdigit()), default=-1)
    tail = text[last + 1:].split()
    if last >= 0 and len(tail) == 1 and len(tail[0]) <= 4:      # ein kurzes Wortstück nach der Zahl: abgeschnitten
        text = text[: last + 1]
    for name in names:
        letters = name.replace(" ", "")
        if len(letters) >= 4:
            pattern = r"\s*".join(re.escape(ch) for ch in letters)
            text = re.sub(pattern, name, text, flags=re.IGNORECASE)
    return text.strip(" .,:;-|")


def _total_from_title(title: str) -> Optional[int]:
    numbers = re.findall(r"\d[\d.,]*", title)
    return _num(numbers[-1]) if numbers else None


class QuestReader:
    def __init__(self, ocr: OcrEngine) -> None:
        self._ocr = ocr
        self.names: tuple = ()                     # bekannte Raid-Namen (zum Reparieren zerteilter Wörter)

    def read(self, crop: np.ndarray) -> list[QuestLine]:
        height = crop.shape[0]
        mask = near_white_mask(crop, 215, 40)
        lines = self._ocr.lines(ocr_input_mask(mask, SCALE), psm=6)

        entries: list[dict] = []
        pending: Optional[dict] = None
        for ln in lines:
            y = (ln.y - PAD) / SCALE
            progress = parse_progress(ln.text)
            if progress:
                if pending is not None and pending["prog"] is None:
                    pending["prog"], pending["py"] = progress, y
                continue
            letters = sum(ch.isalpha() for ch in ln.text)
            title = clean_title(ln.text, self.names)
            if letters >= 6 and any(ch.isdigit() for ch in title):
                pending = {"title": title, "y": y, "prog": None, "py": None}
                entries.append(pending)

        # Fortschrittszeile fehlt (z. B. ausgeblendet/getönt): gezielt unter dem Titel nachlesen
        offsets = [e["py"] - e["y"] for e in entries if e["prog"] is not None]
        pitch = statistics.median(offsets) if offsets else 0.071 * height
        for entry in entries:
            if entry["prog"] is None:
                entry["prog"] = self._read_strip(crop, entry["y"] + pitch,
                                                 _total_from_title(entry["title"]))

        result = []
        for entry in entries:
            cur, tot = entry["prog"] if entry["prog"] else (None, _total_from_title(entry["title"]))
            result.append(QuestLine(entry["title"], cur, tot))
        return result

    def _read_strip(self, crop: np.ndarray, y_center: float,
                    expected_total: Optional[int]) -> Optional[tuple[int, int]]:
        """Liest eine einzelne Fortschrittszeile mit mehreren Schwellwerten.
        Der Gesamtwert aus dem Titel dient als Plausibilitätsprüfung (z. B. „0/90“, nicht „0/390“)."""
        height = crop.shape[0]
        half = 0.04 * height
        y0, y1 = max(0, int(y_center - half)), min(height, int(y_center + half))
        if y1 - y0 < 6:
            return None
        gray = to_gray(crop[y0:y1])
        for thr in (None, 160, 150, 170, 130):
            text = self._ocr.line(ocr_input_threshold(gray, thr, 4), psm=7, whitelist="0123456789/ ")
            parsed = parse_progress(text)
            if parsed and (expected_total is None or parsed[1] == expected_total):
                return parsed
        return None
