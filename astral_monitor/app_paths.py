"""Speicherorte der Anwendung (Einstellungen, Verlauf, Logs)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "AnimeAstralMonitor"


def data_dir() -> Path:
    """%APPDATA%/AnimeAstralMonitor (oder ASTRAL_DATA_DIR, z. B. für Tests)."""
    override = os.environ.get("ASTRAL_DATA_DIR")
    if override:
        base = Path(override)
    else:
        root = os.environ.get("APPDATA") or str(Path.home() / ".config")
        base = Path(root) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def resource_path(relative: str) -> Path:
    """Ressourcen (z. B. Icon): im Entwicklungsordner oder im EXE-Paket (PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def settings_file() -> Path:
    return data_dir() / "settings.json"


def history_file() -> Path:
    return data_dir() / "raid_history.csv"


def log_file() -> Path:
    return data_dir() / "monitor.log"


def profiles_dir() -> Path:
    path = data_dir() / "profiles"
    path.mkdir(exist_ok=True)
    return path


def debug_dir() -> Path:
    path = data_dir() / "debug"
    path.mkdir(exist_ok=True)
    return path
