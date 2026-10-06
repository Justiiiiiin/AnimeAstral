"""Versionshinweis einer Version aus CHANGELOG.md ausgeben (für den Release-Workflow und zum Nachtragen).

    python tools/release_notes.py 0.6.6 > notes.md
Gibt es keinen Abschnitt „## <Version>“, endet das Skript mit Fehler – so wird kein Release ohne Hinweise gebaut."""
from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(version: str, text: str | None = None) -> str | None:
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    version = version.lstrip("vV")
    match = re.search(rf"^## {re.escape(version)}(?![\w.-])[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        return None
    body = match.group(1).strip()
    return body.replace("### ", "#### ") if body else None      # im Release eine Stufe kleiner


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    body = section(sys.argv[1])
    if body is None:
        print(f"CHANGELOG.md hat keinen Abschnitt „## {sys.argv[1].lstrip('vV')}“.", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
