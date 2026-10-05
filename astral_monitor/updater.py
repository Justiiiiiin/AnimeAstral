"""Automatische Updates über GitHub-Releases: prüfen, laden, Prüfsumme kontrollieren, Installer starten."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

from . import app_paths, build_info
from .version import __version__

log = logging.getLogger("updater")

API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
INSTALLER_RE = re.compile(r"^AnimeAstralMonitor-Setup-.+\.exe$", re.IGNORECASE)
CHECK_EVERY_SECONDS = 6 * 3600


class UpdateError(RuntimeError):
    pass


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    page_url: str
    installer_url: str
    installer_name: str
    size: int
    sha_url: Optional[str]


def current_repo() -> str:
    """„benutzer/repo“ – aus dem GitHub-Build (oder ASTRAL_UPDATE_REPO zum Testen)."""
    return (os.environ.get("ASTRAL_UPDATE_REPO") or build_info.GITHUB_REPO or "").strip().strip("/")


def is_installed_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def version_key(text: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", text)) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return version_key(candidate) > version_key(current)


def due(last_check: float, now: Optional[float] = None) -> bool:
    return ((now if now is not None else time.time()) - last_check) >= CHECK_EVERY_SECONDS


def pick_assets(release: dict, repo: str) -> tuple[Optional[dict], Optional[dict]]:
    """Installer- und Prüfsummen-Datei aus der Release-Antwort; nur Downloads aus dem eigenen Repository."""
    prefix = f"https://github.com/{repo}/releases/download/"
    installer = sha = None
    for asset in release.get("assets", []):
        name, url = str(asset.get("name", "")), str(asset.get("browser_download_url", ""))
        if not url.startswith(prefix):
            continue
        if INSTALLER_RE.match(name):
            installer = asset
        elif name.upper() == "SHA256SUMS.TXT":
            sha = asset
    return installer, sha


def check_latest(repo: str, timeout: float = 12.0, getter: Callable = requests.get) -> Optional[ReleaseInfo]:
    """Neueste Veröffentlichung. None = keine passende Veröffentlichung (noch ohne Installer). Fehler -> UpdateError."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise UpdateError("Kein gültiges GitHub-Repository eingetragen.")
    try:
        resp = getter(API_LATEST.format(repo=repo), timeout=timeout,
                      headers={"Accept": "application/vnd.github+json", "User-Agent": f"AnimeAstralMonitor/{__version__}"})
    except requests.RequestException as exc:
        raise UpdateError(f"Keine Verbindung zu GitHub ({exc.__class__.__name__}).") from exc
    if resp.status_code == 404:
        return None                                    # noch keine Veröffentlichung
    if resp.status_code != 200:
        raise UpdateError(f"GitHub antwortete mit HTTP {resp.status_code}.")
    try:
        data = resp.json()
    except ValueError as exc:
        raise UpdateError("Ungültige Antwort von GitHub.") from exc
    installer, sha = pick_assets(data, repo)
    if installer is None:
        return None
    tag = str(data.get("tag_name", ""))
    return ReleaseInfo(version=tag.lstrip("vV"), tag=tag, notes=str(data.get("body") or "").strip(),
                       page_url=str(data.get("html_url", "")), installer_url=installer["browser_download_url"],
                       installer_name=installer["name"], size=int(installer.get("size") or 0),
                       sha_url=sha["browser_download_url"] if sha else None)


def expected_sha(sha_text: str, filename: str) -> Optional[str]:
    """Liest „<hash>  <datei>“-Zeilen (sha256sum-Format, auch PowerShell-Ausgabe mit Sternchen)."""
    for line in sha_text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]) \
                and parts[1].strip().lstrip("*").strip() == filename:
            return parts[0].lower()
    return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(info: ReleaseInfo, progress: Callable[[int, int], None] = lambda done, total: None,
             cancelled: Callable[[], bool] = lambda: False, getter: Callable = requests.get,
             dest_dir: Optional[Path] = None) -> Path:
    """Lädt den Installer, prüft die Prüfsumme (falls veröffentlicht) und gibt den Pfad zurück."""
    folder = dest_dir or (app_paths.data_dir() / "updates")
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.exe*"):                    # Reste früherer Updates aufräumen
        old.unlink(missing_ok=True)
    target, part = folder / info.installer_name, folder / (info.installer_name + ".part")
    expected = None
    try:
        if info.sha_url:
            resp = getter(info.sha_url, timeout=15, headers={"User-Agent": f"AnimeAstralMonitor/{__version__}"})
            if resp.status_code == 200:
                expected = expected_sha(resp.text, info.installer_name)
        with getter(info.installer_url, stream=True, timeout=30,
                    headers={"User-Agent": f"AnimeAstralMonitor/{__version__}"}) as resp:
            if resp.status_code != 200:
                raise UpdateError(f"Download fehlgeschlagen (HTTP {resp.status_code}).")
            total = int(resp.headers.get("Content-Length") or info.size or 0)
            done = 0
            with part.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if cancelled():
                        raise UpdateError("Abgebrochen.")
                    fh.write(chunk)
                    done += len(chunk)
                    progress(done, total)
    except requests.RequestException as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Download unterbrochen ({exc.__class__.__name__}).") from exc
    except Exception:
        part.unlink(missing_ok=True)
        raise
    if expected and sha256_of(part) != expected:
        part.unlink(missing_ok=True)
        raise UpdateError("Die Prüfsumme der heruntergeladenen Datei stimmt nicht – Update abgebrochen.")
    if part.stat().st_size < 1024 * 100:                 # offensichtlich unvollständig
        part.unlink(missing_ok=True)
        raise UpdateError("Die heruntergeladene Datei ist unvollständig.")
    part.replace(target)
    return target


def launch_installer(path: Path, relaunch: bool = True) -> None:
    """Startet den Installer leise im Hintergrund. Danach muss sich das Programm beenden."""
    args = [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
    if relaunch:
        args.append("/relaunch=1")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP   # überlebt das Programmende
    subprocess.Popen(args, close_fds=True, creationflags=flags)
