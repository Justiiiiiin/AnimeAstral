"""Kommandozeilen-Test der Erkennung an einem Screenshot.

    python -m astral_monitor.selftest bild.png
"""
from __future__ import annotations

import sys
import time

import cv2

from .imaging import crop_roi
from .ocr import OcrEngine, OcrError
from .quests import QuestReader
from .settings import Settings
from .wave import WaveReader


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Aufruf: python -m astral_monitor.selftest <screenshot.png>")
        return 2
    image = cv2.imread(argv[1], cv2.IMREAD_COLOR)
    if image is None:
        print("Bild konnte nicht gelesen werden.")
        return 2
    settings = Settings.load()
    try:
        ocr = OcrEngine(settings.tesseract_path)
    except OcrError as exc:
        print("OCR-Fehler:", exc)
        return 1
    print(f"Tesseract {ocr.version} ({ocr.cmd})  ·  Bild {image.shape[1]}×{image.shape[0]}")

    reader = WaveReader(ocr, settings.allowed_totals_list())
    t0 = time.perf_counter()
    reading = reader.read(crop_roi(image, settings.wave_roi))
    ms = (time.perf_counter() - t0) * 1000
    print(f"Wellenzähler: {reading.value}/{reading.total}" if reading else "Wellenzähler: nicht erkannt",
          f"({ms:.0f} ms)")

    t0 = time.perf_counter()
    lines = QuestReader(ocr).read(crop_roi(image, settings.quest_roi))
    ms = (time.perf_counter() - t0) * 1000
    print(f"Quests ({ms:.0f} ms):")
    for ln in lines:
        prog = "?" if ln.cur is None else f"{ln.cur}/{ln.total}"
        print(f"  - {ln.title}  [{prog}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
