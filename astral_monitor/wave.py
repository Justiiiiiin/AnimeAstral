"""Find and read the wave counter (“Wave 12/100”).

The counter is searched for within the given search area (text recognition with word positions). After that only
a narrow area around it is read (fast, cached). The search area may therefore be generous."""
from __future__ import annotations

import difflib
import hashlib
import re
import struct
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .imaging import PAD, near_white_mask, ocr_input_mask, ocr_input_threshold, text_mask, to_gray
from .ocr import OcrEngine, OcrWord

TEXT_THRESHOLD = 200       # brightness from which a pixel counts as white text
MIN_TEXT_PIXELS = 60       # fewer white pixels = no counter in the image
CACHE_LIMIT = 4096
_MISS = (-1, -1)           # cache marker: this image was not readable
PAD_X, PAD_Y = 0.8, 0.5    # margin around the found counter (in text line heights); room for longer numbers
TIGHT_MAX_HEIGHT = 90      # areas this small are read directly first (previous method)
SCAN_MIN, SCAN_MAX = 1.0, 4.0     # seconds between searches (grows while nothing is found)
RESCAN_AFTER = 3.0         # this long without a hit, then the area is searched again
MAX_BAD_READS = 3          # this many unreadable hits at the remembered place, then search again

# Characters Tesseract often returns instead of digits (t -> 1, O -> 0 ...)
_WAVE_RE = re.compile(r"([0-9tlIO|oSB]{1,4})\s*/\s*([0-9tlIO|oSB]{1,4})")   # up to 2000 waves
_FIX = str.maketrans({"t": "1", "l": "1", "I": "1", "|": "1", "O": "0", "o": "0", "S": "5", "B": "8"})


@dataclass
class WaveReading:
    value: int
    total: int
    raw: str = ""
    cached: bool = False


def parse_wave(text: str, allowed_totals: list[int]) -> Optional[tuple[int, int]]:
    """'Wave 12/100' -> (12, 100). Only allowed totals, value <= total."""
    for match in _WAVE_RE.finditer(text):
        try:
            cur = int(match.group(1).translate(_FIX))
            tot = int(match.group(2).translate(_FIX))
        except ValueError:
            continue
        if allowed_totals:
            if tot not in allowed_totals:
                continue
        elif not 2 <= tot <= 2000:
            continue
        if 0 <= cur <= tot:
            return cur, tot
    return None


_BARE_RE = re.compile(r"([a-zA-Z]{3,6})\W{0,3}([0-9tlIO|oSB]{1,4})\b")


def parse_bare_wave(text: str) -> Optional[int]:
    """“Wave 542” (modes with more than 100 waves show no total) -> 542. Only with the word “Wave” right before it
    and without “/” in the text – otherwise a misread “54/100” could pass as “54”."""
    if "/" in text:
        return None
    for match in _BARE_RE.finditer(text):
        if _is_wave_word(match.group(1)):
            try:
                return int(match.group(2).translate(_FIX))
            except ValueError:
                continue
    return None


def _is_wave_word(text: str) -> bool:
    letters = re.sub(r"[^a-z]", "", text.lower())
    return len(letters) >= 3 and difflib.SequenceMatcher(None, letters, "wave").ratio() >= 0.6


class WaveReader:
    def __init__(self, ocr: OcrEngine, allowed_totals: list[int]) -> None:
        self._ocr = ocr
        self._allowed = allowed_totals
        self._cache: dict[bytes, tuple[int, int]] = {}      # marker _MISS = not readable
        self.box: Optional[tuple[int, int, int, int]] = None      # found area (x0, y0, x1, y1) inside the search area
        self._shape: Optional[tuple] = None
        self._bad = 0
        self._last_ok = 0.0
        self._next_scan = 0.0
        self._scan_gap = SCAN_MIN

    def set_allowed(self, allowed_totals: list[int]) -> None:
        if allowed_totals != self._allowed:
            self._allowed = allowed_totals
            self._cache.clear()
            self.box = None

    # ------------------------------------------------------------------ Reading
    def read(self, crop: np.ndarray) -> Optional[WaveReading]:
        if self._shape != crop.shape:                    # different image format: discard the remembered place
            self._shape, self.box, self._bad = crop.shape, None, 0
        now = time.monotonic()

        if self.box is not None:
            reading, had_text = self._read_region(crop, self.box)
            if reading:
                self._bad, self._last_ok = 0, now
                return reading
            if had_text:
                self._bad += 1                              # text there but unreadable: layout changed?
            # The remembered place is kept (the counter usually comes back exactly there). A new search only happens
            # after several unreadable hits or when the counter is missing for longer.
            if self._bad < MAX_BAD_READS and now - self._last_ok < RESCAN_AFTER:
                return None
        elif crop.shape[0] <= TIGHT_MAX_HEIGHT:
            reading, _ = self._read_region(crop, (0, 0, crop.shape[1], crop.shape[0]))   # narrow area: read directly
            if reading:
                self._last_ok = now
                return reading

        return self._scan(crop, now)

    def _read_region(self, crop: np.ndarray, box: tuple[int, int, int, int]) -> tuple[Optional[WaveReading], bool]:
        """Reads a crop. Returns (result, was there any text visible?)."""
        x0, y0, x1, y1 = box
        region = crop[y0:y1, x0:x1]
        if region.size == 0:
            return None, False
        gray = to_gray(region)
        mask = text_mask(gray, TEXT_THRESHOLD)
        if cv2.countNonZero(mask) < MIN_TEXT_PIXELS:
            return None, False                          # no counter in the image: no OCR at all
        key = hashlib.blake2b(mask.tobytes(), digest_size=8).digest() + struct.pack("<HH", *mask.shape[:2])
        hit = self._cache.get(key)
        if hit == _MISS:
            return None, True
        if hit is not None:
            return WaveReading(hit[0], hit[1], "cache", True), True
        for thr in (TEXT_THRESHOLD, None):               # None = Otsu as a fallback attempt
            text = self._ocr.line(ocr_input_threshold(gray, thr), psm=7)
            parsed = parse_wave(text, self._allowed)
            if parsed is None:
                bare = parse_bare_wave(text)
                parsed = (bare, 0) if bare is not None else None     # 0 = without a total
            if parsed:
                if len(self._cache) >= CACHE_LIMIT:
                    self._cache.clear()
                self._cache[key] = parsed
                return WaveReading(parsed[0], parsed[1], text), True
        if len(self._cache) >= CACHE_LIMIT:
            self._cache.clear()
        self._cache[key] = _MISS
        return None, True

    # ------------------------------------------------------------------ Searching
    def _scan(self, crop: np.ndarray, now: float) -> Optional[WaveReading]:
        if now < self._next_scan:
            return None
        mask = near_white_mask(crop, 215, 40)
        if cv2.countNonZero(mask) < MIN_TEXT_PIXELS:
            return None                                  # nothing bright in the area: skip cheaply
        found = self._locate(crop, mask)
        if found is None:
            self._scan_gap = min(self._scan_gap * 1.6, SCAN_MAX)
            self._next_scan = now + self._scan_gap
            return None
        self._scan_gap = SCAN_MIN
        reading, self.box = found
        self._bad, self._last_ok = 0, now
        return reading

    def _locate(self, crop: np.ndarray, mask: np.ndarray) -> Optional[tuple[WaveReading, tuple[int, int, int, int]]]:
        h, w = crop.shape[:2]
        scale = float(min(3.0, max(1.0, 2000.0 / max(w, 1))))
        words = self._ocr.words(ocr_input_mask(mask, scale), psm=6)
        pad = PAD / scale                                # margin added by ocr_input_mask
        words = [OcrWord(wd.text, wd.x / scale - pad, wd.y / scale - pad, wd.w / scale, wd.h / scale, wd.conf)
                 for wd in words]
        best = None
        for wd in words:
            parsed = parse_wave(wd.text, self._allowed)
            cy = wd.y + wd.h / 2
            label = [o for o in words if o is not wd and _is_wave_word(o.text) and abs((o.y + o.h / 2) - cy) < wd.h
                     and o.x < wd.x and wd.x - (o.x + o.w) < 3 * wd.h]
            if parsed is None:                          # “Wave 542”: only with “Wave” right before it
                bare = parse_bare_wave(f"{label[0].text} {wd.text}") if label else None
                if bare is None:
                    continue
                parsed = (bare, 0)
            score = (1 if label else 0, wd.h)           # prefer “Wave” before it, otherwise the largest text
            if best is None or score > best[0]:
                best = (score, wd, parsed, label[0] if label else None)
        if best is None:
            return None
        _score, wd, parsed, label = best
        left = min(wd.x, label.x) if label else wd.x
        right = wd.x + wd.w
        top = min(wd.y, label.y) if label else wd.y
        bottom = max(wd.y + wd.h, label.y + label.h) if label else wd.y + wd.h
        height = bottom - top
        x0 = int(max(0, left - PAD_X * height))           # room for longer numbers (the text is centered)
        x1 = int(min(w, right + PAD_X * height))
        y0 = int(max(0, top - PAD_Y * height))
        y1 = int(min(h, bottom + PAD_Y * height))
        box = (x0, y0, x1, y1)
        reading, _ = self._read_region(crop, box)
        if reading is None:                              # emergency: take the value from the search
            reading = WaveReading(parsed[0], parsed[1], wd.text)
        return reading, box
