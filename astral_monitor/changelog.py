"""CHANGELOG.md lesen: Abschnitt einer Version (für Release-Hinweise und „Was ist neu“ im Programm)."""
from __future__ import annotations

import re
from typing import Optional

from . import app_paths


def read() -> str:
    """Mitgelieferte CHANGELOG.md (im Programmpaket bzw. im Projektordner)."""
    try:
        return app_paths.resource_path("CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def section(version: str, text: Optional[str] = None) -> Optional[str]:
    """Inhalt unter „## <version>“ bis zur nächsten Version (ohne Überschrift), None = kein Abschnitt."""
    text = read() if text is None else text
    version = version.lstrip("vV")
    match = re.search(rf"^## {re.escape(version)}(?![\w.-])[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        return None
    return match.group(1).strip() or None


def highlights(version: str, limit: int = 4, text: Optional[str] = None) -> list[str]:
    """Die ersten Stichpunkte einer Version – zuerst „Neu“, dann der Rest (für das kurze „Was ist neu“)."""
    body = section(version, text) or ""
    bullets = [ln[2:].strip() for ln in body.splitlines() if ln.startswith("- ")]
    return bullets[:limit]
