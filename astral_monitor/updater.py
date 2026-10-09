"""Automatic updates via GitHub releases: check, download, verify the checksum, install.

Two ways: a small update package with only the changed files (see tools/make_patch.py) – if it fits the installed
state, only these files are downloaded and swapped after exiting. Otherwise the full installer."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import requests

from . import app_paths, build_info
from .i18n import tr
from .version import __version__

log = logging.getLogger("updater")

API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
API_LIST = "https://api.github.com/repos/{repo}/releases?per_page=50"
INSTALLER_RE = re.compile(r"^AnimeAstralMonitor-Setup-.+\.exe$", re.IGNORECASE)
PATCH_RE = re.compile(r"^AnimeAstralMonitor-Update-.+\.zip$", re.IGNORECASE)
MANIFEST_RE = re.compile(r"^files-.+\.json$", re.IGNORECASE)
MANIFEST_NAME = "files.json"           # lives in the program folder: checksums of all files of this version
CHECK_EVERY_SECONDS = 6 * 3600
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{B7C1D0A4-5E2F-4C8B-9A3D-1F6E2A7C4D90}_is1"


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
    manifest_url: Optional[str] = None
    patch_url: Optional[str] = None
    patch_name: str = ""
    patch_size: int = 0
    published: str = ""                 # ISO time of the release (GitHub)
    prerelease: bool = False            # beta (pre-release)


@dataclass
class PatchPlan:
    """Small update: these files come from the package, these are removed."""
    manifest: dict
    changed: list = field(default_factory=list)
    removed: list = field(default_factory=list)


def current_repo() -> str:
    """“user/repo” – from the GitHub build (or ASTRAL_UPDATE_REPO for testing)."""
    return (os.environ.get("ASTRAL_UPDATE_REPO") or build_info.GITHUB_REPO or "").strip().strip("/")


def is_installed_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def version_key(text: str) -> tuple:
    """Sort key: “0.7.2-beta.1” < “0.7.2-beta.2” < “0.7.2” < “0.7.3-beta.1”."""
    main, _, beta = text.strip().lstrip("vV").partition("-")
    nums = tuple(int(p) for p in re.findall(r"\d+", main)) or (0,)
    nums += (0,) * (4 - len(nums))                     # 0.7 == 0.7.0
    if not beta:
        return nums + (1, 0)
    n = re.findall(r"\d+", beta)
    return nums + (0, int(n[0]) if n else 0)


def is_beta(version: str) -> bool:
    return "-" in version.strip()


def is_newer(candidate: str, current: str = __version__) -> bool:
    return version_key(candidate) > version_key(current)


def due(last_check: float, now: Optional[float] = None) -> bool:
    return ((now if now is not None else time.time()) - last_check) >= CHECK_EVERY_SECONDS


def pick_assets(release: dict, repo: str) -> tuple[Optional[dict], Optional[dict]]:
    """Installer and checksum file from the release response; only downloads from our own repository."""
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


def _get_json(url: str, timeout: float, getter: Callable):
    try:
        resp = getter(url, timeout=timeout,
                      headers={"Accept": "application/vnd.github+json", "User-Agent": f"AnimeAstralMonitor/{__version__}"})
    except requests.RequestException as exc:
        raise UpdateError(tr("No connection to GitHub ({error}).", error=exc.__class__.__name__)) from exc
    if resp.status_code == 404:
        return None                                    # no release yet
    if resp.status_code != 200:
        raise UpdateError(tr("GitHub answered with HTTP {code}.", code=resp.status_code))
    try:
        return resp.json()
    except ValueError as exc:
        raise UpdateError(tr("Invalid response from GitHub.")) from exc


def _check_repo(repo: str) -> None:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise UpdateError(tr("No valid GitHub repository set."))


def release_info(data: dict, repo: str) -> Optional[ReleaseInfo]:
    """One release from the GitHub response; None = without installer (not installable)."""
    if not isinstance(data, dict) or data.get("draft"):
        return None
    installer, sha = pick_assets(data, repo)
    if installer is None:
        return None
    tag = str(data.get("tag_name", ""))
    manifest, patch = pick_patch_assets(data, repo)
    return ReleaseInfo(version=tag.lstrip("vV"), tag=tag, notes=str(data.get("body") or "").strip(),
                       page_url=str(data.get("html_url", "")), installer_url=installer["browser_download_url"],
                       installer_name=installer["name"], size=int(installer.get("size") or 0),
                       sha_url=sha["browser_download_url"] if sha else None,
                       manifest_url=manifest["browser_download_url"] if manifest else None,
                       patch_url=patch["browser_download_url"] if patch else None,
                       patch_name=patch["name"] if patch else "", patch_size=int((patch or {}).get("size") or 0),
                       published=str(data.get("published_at") or ""),
                       prerelease=bool(data.get("prerelease")) or is_beta(tag))


def check_latest(repo: str, timeout: float = 12.0, getter: Callable = requests.get,
                 beta: bool = False) -> Optional[ReleaseInfo]:
    """Newest release (with beta=True betas too). None = no matching release (no installer yet).
    Errors -> UpdateError."""
    _check_repo(repo)
    if beta:
        found = list_releases(repo, timeout, getter, beta=True)
        return found[0] if found else None
    data = _get_json(API_LATEST.format(repo=repo), timeout, getter)
    return release_info(data, repo) if data is not None else None


def list_releases(repo: str, timeout: float = 12.0, getter: Callable = requests.get,
                  beta: bool = False) -> list[ReleaseInfo]:
    """All installable releases, newest first (for release notes and downgrades).
    Betas only with beta=True."""
    _check_repo(repo)
    data = _get_json(API_LIST.format(repo=repo), timeout, getter) or []
    out = [info for info in (release_info(d, repo) for d in data if isinstance(d, dict)) if info]
    if not beta:
        out = [r for r in out if not r.prerelease]
    out.sort(key=lambda r: version_key(r.version), reverse=True)
    return out


def pick_patch_assets(release: dict, repo: str) -> tuple[Optional[dict], Optional[dict]]:
    """File list (files-X.json) and update package (AnimeAstralMonitor-Update-X.zip), only from our own repository."""
    prefix = f"https://github.com/{repo}/releases/download/"
    manifest = patch = None
    for asset in release.get("assets", []):
        name, url = str(asset.get("name", "")), str(asset.get("browser_download_url", ""))
        if not url.startswith(prefix):
            continue
        if MANIFEST_RE.match(name):
            manifest = asset
        elif PATCH_RE.match(name):
            patch = asset
    return manifest, patch


# ------------------------------------------------------------------ small update (changed files only)
def app_dir() -> Path:
    return Path(sys.executable).resolve().parent


def read_manifest(folder: Path) -> Optional[dict]:
    try:
        data = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data.get("files"), dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def _safe_rel(path: str) -> bool:
    """Only relative paths inside the program folder (no “..”, no drive)."""
    parts = Path(path).parts
    return bool(parts) and not Path(path).is_absolute() and ".." not in parts and ":" not in path


def plan_patch(local: Optional[dict], remote: Optional[dict], folder: Path) -> Optional[PatchPlan]:
    """Does the update package fit the installed state? None = no (then the full installer)."""
    if not local or not remote or not isinstance(remote.get("files"), dict):
        return None
    lf, rf = local["files"], remote["files"]
    if not isinstance(remote.get("patch"), dict) or not all(_safe_rel(p) for p in list(rf) + list(lf)):
        return None
    contains = set(remote["patch"].get("contains") or [])
    changed = sorted(p for p, digest in rf.items() if lf.get(p) != digest)
    if not set(changed) <= contains:
        return None                                    # e.g. version skipped: the package doesn't contain everything
    if any(not (folder / p).is_file() for p in rf if p not in changed):
        return None                                    # installed files missing: rather install completely
    removed = sorted(p for p in lf if p not in rf)
    return PatchPlan(manifest={"version": remote.get("version"), "files": rf}, changed=changed, removed=removed)


def folder_writable(folder: Path) -> bool:
    probe = folder / ".write_test"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def fetch_manifest(info: ReleaseInfo, getter: Callable = requests.get) -> Optional[dict]:
    """Loads the file list of the new version and checks it against SHA256SUMS. None = not available."""
    if not info.manifest_url or not info.sha_url:
        return None
    headers = {"User-Agent": f"AnimeAstralMonitor/{__version__}"}
    try:
        sums = getter(info.sha_url, timeout=15, headers=headers)
        resp = getter(info.manifest_url, timeout=15, headers=headers)
    except requests.RequestException:
        return None
    if sums.status_code != 200 or resp.status_code != 200:
        return None
    name = info.manifest_url.rsplit("/", 1)[-1]
    expected = expected_sha(sums.text, name)
    if not expected or hashlib.sha256(resp.content).hexdigest() != expected:
        return None
    try:
        data = json.loads(resp.content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def prepare_patch(info: ReleaseInfo, getter: Callable = requests.get,
                  folder: Optional[Path] = None) -> Optional[PatchPlan]:
    """Small update possible? (installed version only, writable folder, matching package)."""
    folder = folder or app_dir()
    if not info.patch_url or not folder_writable(folder):
        return None
    return plan_patch(read_manifest(folder), fetch_manifest(info, getter), folder)


def expected_sha(sha_text: str, filename: str) -> Optional[str]:
    """Reads “<hash>  <file>” lines (sha256sum format, also PowerShell output with asterisks)."""
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
             dest_dir: Optional[Path] = None, patch: bool = False) -> Path:
    """Downloads the installer (or with patch=True the update package), verifies the checksum and returns the path.
    Without a published checksum an update package is refused (it is unpacked without an installer)."""
    folder = dest_dir or (app_paths.data_dir() / "updates")
    folder.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.exe*", "*.zip*"):                 # clean up leftovers of earlier updates
        for old in folder.glob(pattern):
            old.unlink(missing_ok=True)
    name, url, size = ((info.patch_name, info.patch_url, info.patch_size) if patch
                       else (info.installer_name, info.installer_url, info.size))
    target, part = folder / name, folder / (name + ".part")
    expected = None
    try:
        if info.sha_url:
            resp = getter(info.sha_url, timeout=15, headers={"User-Agent": f"AnimeAstralMonitor/{__version__}"})
            if resp.status_code == 200:
                expected = expected_sha(resp.text, name)
        if patch and not expected:
            raise UpdateError(tr("No checksum is published for the update package."))
        with getter(url, stream=True, timeout=30,
                    headers={"User-Agent": f"AnimeAstralMonitor/{__version__}"}) as resp:
            if resp.status_code != 200:
                raise UpdateError(tr("Download failed (HTTP {code}).", code=resp.status_code))
            total = int(resp.headers.get("Content-Length") or size or 0)
            done = 0
            with part.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if cancelled():
                        raise UpdateError(tr("Cancelled."))
                    fh.write(chunk)
                    done += len(chunk)
                    progress(done, total)
    except requests.RequestException as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(tr("Download interrupted ({error}).", error=exc.__class__.__name__)) from exc
    except Exception:
        part.unlink(missing_ok=True)
        raise
    if expected and sha256_of(part) != expected:
        part.unlink(missing_ok=True)
        raise UpdateError(tr("The checksum of the downloaded file does not match – update cancelled."))
    if not patch and part.stat().st_size < 1024 * 100:   # obviously incomplete
        part.unlink(missing_ok=True)
        raise UpdateError(tr("The downloaded file is incomplete."))
    part.replace(target)
    return target


# Swap after exiting (PowerShell exists on every Windows 10/11). Backs up every replaced/removed file first
# and restores everything on an error; afterwards the program restarts.
APPLY_SCRIPT = r"""param([string]$Plan)
$ErrorActionPreference = 'Stop'
$p = Get-Content -LiteralPath $Plan -Raw -Encoding UTF8 | ConvertFrom-Json
$log = Join-Path $p.work 'apply.log'
function Log($t) { Add-Content -LiteralPath $log -Value ((Get-Date -Format 'HH:mm:ss ') + $t) -Encoding UTF8 }
try { Wait-Process -Id $p.pid -Timeout 60 -ErrorAction SilentlyContinue } catch {}
Start-Sleep -Milliseconds 500
$backup = Join-Path $p.work 'backup'
$moved = New-Object System.Collections.ArrayList
try {
  foreach ($rel in @($p.changed) + @($p.removed) + @('files.json')) {
    if (-not $rel) { continue }
    $dst = Join-Path $p.app $rel
    if (Test-Path -LiteralPath $dst) {
      $bak = Join-Path $backup $rel
      New-Item -ItemType Directory -Force -Path (Split-Path $bak) | Out-Null
      for ($i = 0; $i -lt 20; $i++) { try { Move-Item -LiteralPath $dst -Destination $bak -Force; break } catch { if ($i -eq 19) { throw }; Start-Sleep -Milliseconds 500 } }
      [void]$moved.Add($rel)
    }
  }
  foreach ($rel in @($p.changed) + @('files.json')) {
    if (-not $rel) { continue }
    $dst = Join-Path $p.app $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Copy-Item -LiteralPath (Join-Path $p.staging $rel) -Destination $dst -Force
  }
  try { Set-ItemProperty -Path ('HKCU:\' + $p.uninstall_key) -Name DisplayVersion -Value $p.version -ErrorAction Stop } catch {}
  Log ('Update to ' + $p.version + ' installed: ' + @($p.changed).Count + ' files replaced, ' + @($p.removed).Count + ' removed')
} catch {
  Log ('ERROR: ' + $_ + ' - restoring the previous state')
  foreach ($rel in @($p.changed) + @('files.json')) { if ($rel -and -not $moved.Contains($rel)) { Remove-Item -LiteralPath (Join-Path $p.app $rel) -Force -ErrorAction SilentlyContinue } }
  foreach ($rel in $moved) { Move-Item -LiteralPath (Join-Path $backup $rel) -Destination (Join-Path $p.app $rel) -Force -ErrorAction SilentlyContinue }
}
if ($p.relaunch) { Start-Process -FilePath (Join-Path $p.app $p.exe) }
Remove-Item -LiteralPath $p.staging -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
"""


def stage_patch(zip_path: Path, plan: PatchPlan, work: Path) -> Path:
    """Unpacks only the planned files and checks each one against the checksum of the file list."""
    staging = work / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = {n.replace("\\", "/"): n for n in zf.namelist()}
            for rel in plan.changed:
                member = names.get(rel)
                if member is None:
                    raise UpdateError(tr("{file} is missing in the update package.", file=rel))
                data = zf.read(member)
                if hashlib.sha256(data).hexdigest() != plan.manifest["files"][rel]:
                    raise UpdateError(tr("Checksum does not match: {file}.", file=rel))
                dst = staging / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(tr("Update package damaged ({error}).", error=exc.__class__.__name__)) from exc
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    (staging / MANIFEST_NAME).write_text(json.dumps(plan.manifest, indent=1), encoding="utf-8")
    return staging


def launch_patch(zip_path: Path, plan: PatchPlan, relaunch: bool = True, folder: Optional[Path] = None,
                 work: Optional[Path] = None, pid: Optional[int] = None) -> Path:
    """Prepares the swap and starts it in the background. Afterwards the program must exit."""
    folder = folder or app_dir()
    work = work or (app_paths.data_dir() / "updates" / "apply")
    staging = stage_patch(zip_path, plan, work)
    plan_file = work / "plan.json"
    plan_file.write_text(json.dumps({
        "pid": pid or os.getpid(), "app": str(folder), "work": str(work), "staging": str(staging),
        "changed": plan.changed, "removed": plan.removed, "version": plan.manifest.get("version") or "",
        "exe": Path(sys.executable).name, "relaunch": relaunch, "uninstall_key": UNINSTALL_KEY,
    }, ensure_ascii=False), encoding="utf-8")
    script = work / "apply.ps1"
    script.write_text(APPLY_SCRIPT, encoding="utf-8-sig")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP   # invisible, survives the end of the program
    subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                      "-WindowStyle", "Hidden", "-File", str(script), "-Plan", str(plan_file)],
                     close_fds=True, creationflags=flags)
    return plan_file


def cleanup_downloads(folder: Optional[Path] = None) -> int:
    """At start-up: delete downloaded installers/packages of earlier updates (otherwise ~60 MB stay behind).
    Files still in use stay until the next start. The swap log is kept."""
    folder = folder or (app_paths.data_dir() / "updates")
    removed = 0
    for pattern in ("*.exe", "*.zip", "*.part", "apply/plan.json", "apply/apply.ps1"):
        for path in folder.glob(pattern):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    for sub in ("apply/staging", "apply/backup"):
        if (folder / sub).is_dir():
            shutil.rmtree(folder / sub, ignore_errors=True)
    return removed


def launch_installer(path: Path, relaunch: bool = True) -> None:
    """Starts the installer silently in the background. Afterwards the program must exit."""
    args = [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
    if relaunch:
        args.append("/relaunch=1")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP   # survives the end of the program
    subprocess.Popen(args, close_fds=True, creationflags=flags)
