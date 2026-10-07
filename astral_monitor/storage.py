"""Speicher-Übersicht: wie viel Platz das Programm belegt, und Entbehrliches aufräumen."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import app_paths
from .i18n import N_


@dataclass
class Usage:
    label: str                 # Anzeigename (N_, mit tr() übersetzen)
    size: int                  # Bytes
    removable: bool            # „Aufräumen“ löscht es


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return 0


def _groups(base: Path) -> list[tuple[str, list[Path], bool]]:
    log = app_paths.log_file()
    return [
        (N_("Statistik"), [app_paths.history_file()], False),
        (N_("Archiv"), [base / "archive"], False),
        (N_("Raids und Einstellungen"), [base / "profiles", app_paths.settings_file()], False),
        (N_("Protokoll"), [log], False),
        (N_("Ältere Protokolle"), sorted(base.glob(log.name + ".*")), True),
        (N_("Debug-Bilder"), [base / "debug"], True),
        (N_("Update-Reste"), [base / "updates"], True),
    ]


def usage(base: Optional[Path] = None) -> list[Usage]:
    base = base or app_paths.data_dir()
    out = [Usage(name, sum(_size(p) for p in paths), removable) for name, paths, removable in _groups(base)]
    known = {p.resolve() for _n, paths, _r in _groups(base) for p in paths}
    other = sum(_size(p) for p in base.iterdir() if p.resolve() not in known)
    out.append(Usage(N_("Sonstiges"), other, False))
    return out


def clean(base: Optional[Path] = None) -> int:
    """Löscht ältere Protokolle, Debug-Bilder und Update-Reste. Gibt die freigegebenen Bytes zurück.
    Dateien in Benutzung (z. B. ein laufendes Update) bleiben liegen."""
    base = base or app_paths.data_dir()
    freed = 0
    for _name, paths, removable in _groups(base):
        if not removable:
            continue
        for path in paths:
            files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else []
            for f in files:
                if f.name == "apply.log":                 # Protokoll des letzten Updates (Fehlersuche)
                    continue
                try:
                    size = f.stat().st_size
                    f.unlink()
                    freed += size
                except OSError:
                    pass
    return freed


def fmt_size(size: int) -> str:
    """1 234 567 -> „1,2 MB“ (Dezimaltrennzeichen je Sprache via i18n.dec)."""
    from .i18n import dec
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.0f} KB"
    return dec(f"{size / 1024 ** 2:.1f} MB")
