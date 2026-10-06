"""Bildverarbeitung: Ausschnitte, Masken, OCR-Vorbereitung, JPEG-Export."""
from __future__ import annotations

import cv2
import numpy as np

from .settings import Roi

cv2.setNumThreads(1)        # kleine Ausschnitte: Mehrkern-Verteilung kostet mehr als sie bringt

PAD = 12  # Rand um OCR-Bilder (Pixel, nach Skalierung)


def crop_roi(img: np.ndarray, roi: Roi) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = roi.abs_box(w, h)
    return img[y0:y1, x0:x1]


def to_gray(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def text_mask(gray: np.ndarray, thr: int = 200) -> np.ndarray:
    """Helle Pixel (weißer Text) als 255, Rest 0."""
    return cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY)[1]


def near_white_mask(bgr: np.ndarray, lo: int = 215, spread: int = 40) -> np.ndarray:
    """Nahezu weiße Pixel (alle Kanäle hoch, kaum Farbe) – blendet bunte Kulisse aus."""
    mx = bgr.max(axis=2)
    mn = bgr.min(axis=2)
    return (((mn >= lo) & ((mx - mn) <= spread)) * 255).astype(np.uint8)


def _pad_invert(binary: np.ndarray) -> np.ndarray:
    inv = cv2.bitwise_not(binary)
    return cv2.copyMakeBorder(inv, PAD, PAD, PAD, PAD, cv2.BORDER_CONSTANT, value=255)


def ocr_input_threshold(gray: np.ndarray, thr, scale: int = 3) -> np.ndarray:
    """Graubild -> hochskaliert, binarisiert (thr=None: Otsu), schwarzer Text auf Weiß."""
    big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if thr is None:
        _, binary = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        _, binary = cv2.threshold(big, thr, 255, cv2.THRESH_BINARY)
    return _pad_invert(binary)


def ocr_input_mask(mask: np.ndarray, scale: int = 3) -> np.ndarray:
    big = cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(big, 127, 255, cv2.THRESH_BINARY)
    return _pad_invert(binary)



def encode_jpeg(bgr: np.ndarray, max_width: int = 1600, quality: int = 85) -> bytes:
    """Verkleinert und als JPEG kodiert (klein genug für Discord, schnell)."""
    h, w = bgr.shape[:2]
    if w > max_width:
        bgr = cv2.resize(bgr, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG-Kodierung fehlgeschlagen")
    return buf.tobytes()
