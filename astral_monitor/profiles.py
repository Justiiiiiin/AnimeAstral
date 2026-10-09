"""Raids als einfache Namensliste (je Raid ein Ordner mit profile.json: Notiz, eigener Auslöser).

Bis 0.6.3 gab es hier eine Raid-Erkennung per Referenzbild (ORB-Merkmalsvergleich). Entfernt auf Wunsch des
Eigentümers (06.10.2026): Die Kamera im Spiel ist frei einstellbar und zeigt zum Ressourcensparen manchmal nichts –
der Raid wird jetzt auf der Startseite ausgewählt. Alte Referenzbilder räumt `remove_reference_images` einmalig weg."""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from .i18n import tr

log = logging.getLogger("profiles")


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^\w \-]", "", name, flags=re.UNICODE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)[:40]
    if not cleaned:
        raise ValueError(tr("Please enter a name made of letters or digits."))
    return cleaned


class ProfileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def names(self) -> list[str]:
        return sorted((p.name for p in self.root.iterdir() if p.is_dir() and not p.name.endswith(".tmp_rename")),
                      key=str.lower)

    def create(self, name: str) -> str:
        clean = sanitize_name(name)
        if any(n.lower() == clean.lower() for n in self.names()):
            raise ValueError(tr("A raid “{name}” already exists.", name=clean))
        (self.root / clean).mkdir()
        return clean

    def rename(self, old: str, new: str) -> str:
        """Raid umbenennen (Ordner samt Einstellungen). Rückgabe: neuer, bereinigter Name."""
        src, clean = self.root / sanitize_name(old), sanitize_name(new)
        if not src.is_dir():
            raise ValueError(tr("There is no profile “{name}”.", name=old))
        if clean == src.name:
            return clean
        if clean.lower() != src.name.lower() and any(n.lower() == clean.lower() for n in self.names()):
            raise ValueError(tr("A raid “{name}” already exists.", name=clean))
        if clean.lower() == src.name.lower():        # nur Groß-/Kleinschreibung: Windows braucht einen Zwischenschritt
            tmp = self.root / (clean + ".tmp_rename")
            src.rename(tmp)
            src = tmp
        src.rename(self.root / clean)
        return clean

    def delete(self, name: str) -> None:
        folder = self.root / sanitize_name(name)
        if folder.is_dir():
            shutil.rmtree(folder)

    # ------------------------------------------------------- Einstellungen je Raid
    def settings(self, name: str) -> dict:
        try:
            data = json.loads((self.root / sanitize_name(name) / "profile.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self, name: str, data: dict) -> None:
        folder = self.root / sanitize_name(name)
        folder.mkdir(exist_ok=True)
        (folder / "profile.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------- Aufräumen (einmalig)
    def remove_reference_images(self) -> int:
        """Referenzbilder der früheren Raid-Erkennung löschen. Rückgabe: Anzahl gelöschter Bilder."""
        count = 0
        for folder in self.root.iterdir():
            if not folder.is_dir():
                continue
            for img in folder.glob("ref_*.jpg"):
                try:
                    img.unlink()
                    count += 1
                except OSError:
                    pass
        if count:
            log.info("%d alte Referenzbilder gelöscht (Raid-Erkennung entfernt).", count)
        return count
