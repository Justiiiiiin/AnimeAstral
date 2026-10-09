"""Raids as a simple list of names (one folder per raid with profile.json: note, own trigger).

Up to 0.6.3 there was raid detection via a reference image (ORB feature matching). Removed at the owner's request
(06.10.2026): the in-game camera can be moved freely and sometimes shows nothing to save resources – the raid is
now chosen on the start page. `remove_reference_images` removes old reference images once."""
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
        """Rename a raid (folder including settings). Returns the new, cleaned-up name."""
        src, clean = self.root / sanitize_name(old), sanitize_name(new)
        if not src.is_dir():
            raise ValueError(tr("There is no profile “{name}”.", name=old))
        if clean == src.name:
            return clean
        if clean.lower() != src.name.lower() and any(n.lower() == clean.lower() for n in self.names()):
            raise ValueError(tr("A raid “{name}” already exists.", name=clean))
        if clean.lower() == src.name.lower():        # case only: Windows needs an intermediate step
            tmp = self.root / (clean + ".tmp_rename")
            src.rename(tmp)
            src = tmp
        src.rename(self.root / clean)
        return clean

    def delete(self, name: str) -> None:
        folder = self.root / sanitize_name(name)
        if folder.is_dir():
            shutil.rmtree(folder)

    # ------------------------------------------------------- Settings per raid
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

    # ------------------------------------------------------- Clean-up (one-off)
    def remove_reference_images(self) -> int:
        """Delete reference images of the former raid detection. Returns the number of deleted images."""
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
            log.info("Deleted %d old reference images (raid detection removed).", count)
        return count
