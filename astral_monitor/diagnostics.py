"""Diagnose-Paket: sammelt Protokoll, Wertverlauf, Einstellungen (ohne Webhook) und Bilder in einer ZIP-Datei."""
from __future__ import annotations

import csv
import io
import json
import platform
import sys
import time
import zipfile
from importlib import metadata
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import app_paths
from .version import __version__


def _pkg(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "nicht installiert"


def _png(image: Optional[np.ndarray]) -> Optional[bytes]:
    if image is None:
        return None
    ok, buf = cv2.imencode(".png", image)
    return buf.tobytes() if ok else None


def _jpg(image: Optional[np.ndarray]) -> Optional[bytes]:
    if image is None:
        return None
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None


def build_report(engine, dest_dir: Path) -> Path:
    """Schreibt das Diagnose-Paket und gibt den Pfad zurück. Enthält keine Webhook-URL."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = dest_dir / f"astral_diagnose_{stamp}.zip"
    s = engine.settings
    state = engine.state

    lines = [f"Anime Astral Monitor {__version__}", f"Zeit: {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"Python {sys.version.split()[0]} ({'EXE' if getattr(sys, 'frozen', False) else 'Quellcode'})",
             f"System: {platform.platform()}"]
    for name in ("PySide6", "opencv-python", "opencv-python-headless", "numpy", "windows-capture",
                 "pytesseract", "psutil", "Pillow", "requests"):
        lines.append(f"{name}: {_pkg(name)}")
    try:
        ocr = engine.get_ocr()
        lines.append(f"Tesseract: {ocr.version} ({ocr.cmd})")
    except Exception as exc:
        lines.append(f"Tesseract: FEHLER {exc}")

    run = engine.tracker.run
    lines += ["", "--- Zustand ---",
              f"läuft: {state.running}  pausiert: {state.paused}  Quelle: {state.source_info}",
              f"Bildgröße: {state.frame_size}  Lesezeit: {state.read_ms:.0f} ms",
              f"Welle: {state.wave_value}/{state.wave_total}  Info: {state.info}",
              f"Lauf: {None if run is None else (run.first_wave, run.max_wave, run.total, run.completed)}",
              f"erkannter Raid: {state.profile or '-'}",
              f"Roblox-Prozess: alive={state.roblox_alive} RAM={state.roblox_ram_mb} CPU={state.roblox_cpu}",
              f"Datensätze: gesamt {len(engine.stats.records)}, Fehlversuche {engine.stats.failed_count()}"]

    settings = s.to_dict()
    for secret in ("webhook_url", "private_server_link", "ping_user_id", "rpc_client_id"):   # persönliche Zugänge/IDs
        if settings.get(secret):
            settings[secret] = "<entfernt>"
    if settings.get("ping_user_id"):
        settings["ping_user_id"] = "<entfernt>"

    trace = io.StringIO()
    writer = csv.writer(trace, delimiter=";")
    writer.writerow(["zeit", "welle", "gesamt", "hoechste_welle_im_lauf", "info"])
    for ts, value, total, max_wave, info in list(engine.trace):
        writer.writerow([time.strftime("%H:%M:%S", time.localtime(ts)), value, total, max_wave, info])

    frame = None
    try:
        res = engine.grab_for_ui(full=True)
        frame = res.full if res else None
    except Exception as exc:
        lines.append(f"Screenshot: FEHLER {exc}")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("system_und_zustand.txt", "\n".join(lines))
        zf.writestr("einstellungen.json", json.dumps(settings, indent=2, ensure_ascii=False))
        zf.writestr("wellenverlauf.csv", trace.getvalue())
        for log_file in (app_paths.log_file(), app_paths.log_file().with_name("monitor.log.1")):
            if log_file.is_file():
                zf.write(log_file, log_file.name)
        history = app_paths.history_file()
        if history.is_file():
            tail = history.read_text(encoding="utf-8", errors="replace").splitlines()
            zf.writestr("raid_history_letzte_200.csv", "\n".join(tail[:1] + tail[1:][-200:]) if tail else "")
        for name, data in (("zaehler_ausschnitt.png", _png(state.preview)), ("fenster.jpg", _jpg(frame))):
            if data:
                zf.writestr(name, data)
    return path
