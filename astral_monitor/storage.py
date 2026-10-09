"""Storage overview: how much space the program uses, and cleaning up what isn't needed."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import app_paths
from .i18n import N_


@dataclass
class Usage:
    label: str                 # display name (N_, translate with tr())
    size: int                  # bytes
    removable: bool            # “Clean up” deletes it


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return 0


def _groups(base: Path) -> list[tuple[str, list[Path], bool]]:
    log = app_paths.log_file()
    return [
        (N_("Statistics"), [app_paths.history_file()], False),
        (N_("Archive"), [base / "archive"], False),
        (N_("Raids and settings"), [base / "profiles", app_paths.settings_file()], False),
        (N_("Log"), [log], False),
        (N_("Older logs"), sorted(base.glob(log.name + ".*")), True),
        (N_("Debug images"), [base / "debug"], True),
        (N_("Update leftovers"), [base / "updates"], True),
    ]


def usage(base: Optional[Path] = None) -> list[Usage]:
    base = base or app_paths.data_dir()
    out = [Usage(name, sum(_size(p) for p in paths), removable) for name, paths, removable in _groups(base)]
    known = {p.resolve() for _n, paths, _r in _groups(base) for p in paths}
    other = sum(_size(p) for p in base.iterdir() if p.resolve() not in known)
    out.append(Usage(N_("Other"), other, False))
    return out


def clean(base: Optional[Path] = None) -> int:
    """Deletes older logs, debug images and update leftovers. Returns the freed bytes.
        Files in use (e.g. a running update) are left alone."""
    base = base or app_paths.data_dir()
    freed = 0
    for _name, paths, removable in _groups(base):
        if not removable:
            continue
        for path in paths:
            files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else []
            for f in files:
                if f.name == "apply.log":                 # log of the last update (troubleshooting)
                    continue
                try:
                    size = f.stat().st_size
                    f.unlink()
                    freed += size
                except OSError:
                    pass
    return freed


def fmt_size(size: int) -> str:
    """1 234 567 -> “1.2 MB” (decimal separator per language via i18n.dec)."""
    from .i18n import dec
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.0f} KB"
    return dec(f"{size / 1024 ** 2:.1f} MB")
