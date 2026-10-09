"""Read CHANGELOG.md: the section of a version (for release notes and “What's new” in the program)."""
from __future__ import annotations

import re
from typing import Optional

from . import app_paths


def read() -> str:
    """Bundled CHANGELOG.md (in the program package or the project folder)."""
    try:
        return app_paths.resource_path("CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def section(version: str, text: Optional[str] = None) -> Optional[str]:
    """Content under “## <version>” up to the next version (without heading), None = no section."""
    text = read() if text is None else text
    version = version.lstrip("vV")
    match = re.search(rf"^## {re.escape(version)}(?![\w.-])[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        return None
    return match.group(1).strip() or None


def highlights(version: str, limit: int = 4, text: Optional[str] = None) -> list[str]:
    """The first bullet points of a version – “New” first, then the rest (for the short “What's new”)."""
    body = section(version, text) or ""
    bullets = [ln[2:].strip() for ln in body.splitlines() if ln.startswith("- ")]
    return bullets[:limit]
