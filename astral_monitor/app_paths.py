"""Storage locations of the application (settings, history, logs)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "AnimeAstralMonitor"


_made: set = set()                                   # folders already created (don't check again on every access)


def data_dir() -> Path:
    """%APPDATA%/AnimeAstralMonitor (or ASTRAL_DATA_DIR, e.g. for tests)."""
    override = os.environ.get("ASTRAL_DATA_DIR")
    if override:
        base = Path(override)
    else:
        root = os.environ.get("APPDATA") or str(Path.home() / ".config")
        base = Path(root) / APP_NAME
    if base not in _made:
        base.mkdir(parents=True, exist_ok=True)
        _made.add(base)
    return base


def resource_path(relative: str) -> Path:
    """Resources (e.g. icon): in the development folder or in the EXE bundle (PyInstaller)."""
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


def archive_dir() -> Path:
    """Archived statistics (Statistics → ⋯ → Archive)."""
    return data_dir() / "archive"


def debug_dir() -> Path:
    path = data_dir() / "debug"
    path.mkdir(exist_ok=True)
    return path
