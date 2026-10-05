"""Updater für den Anime Astral Monitor.

Ablauf: neue ZIP finden -> Dateien sauber austauschen (veraltete Dateien entfernen) -> Pakete prüfen ->
EXE neu bauen -> Programmordner ersetzen (mit Sicherungskopie) -> optional starten.

Aufruf:   update.bat                    (sucht die neueste anime_astral_monitor*.zip)
          update.bat <datei.zip>        (oder die ZIP auf update.bat ziehen)
Optionen: --yes (keine Rückfragen), --install-dir <Ordner>, --no-build, --no-pip
Deine Daten (Einstellungen, Verlauf) liegen in %APPDATA% und werden nie angefasst.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent
NAME = "AnimeAstralMonitor"
ZIP_PATTERN = "anime_astral_monitor*.zip"
PACKAGE_DIRS = ("astral_monitor", "assets")     # hier werden Dateien, die nicht mehr zum Paket gehören, entfernt
TEXT_SUFFIXES = (".py", ".md", ".bat", ".txt", ".json")
CONFIG_NAME = "update_config.json"


# ------------------------------------------------------------------ Hilfsfunktionen
def say(text: str = "") -> None:
    print(text, flush=True)


class Ask:
    def __init__(self, yes: bool) -> None:
        self.yes = yes

    def __call__(self, question: str, default: str = "") -> str:
        if self.yes:
            return default
        try:
            answer = input(f"{question} ").strip()
        except EOFError:
            return default
        return answer or default

    def confirm(self, question: str, default: bool = True) -> bool:
        hint = "[J/n]" if default else "[j/N]"
        answer = self(f"{question} {hint}", "j" if default else "n").lower()
        return answer.startswith(("j", "y"))


def file_hash(path: Path, rel: str) -> str:
    data = path.read_bytes()
    if rel.endswith(TEXT_SUFFIXES):
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def read_version_text(text: str) -> Optional[str]:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else None


def current_version(root: Path = ROOT) -> str:
    try:
        return read_version_text((root / "astral_monitor" / "version.py").read_text(encoding="utf-8")) or "unbekannt"
    except OSError:
        return "unbekannt"


def version_key(version: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)


def load_manifest(root: Path) -> dict:
    try:
        return json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ ZIP finden und prüfen
def find_zips(explicit: Optional[str], extra_dirs: Optional[list[Path]] = None) -> list[Path]:
    if explicit:
        path = Path(explicit.strip('"'))
        return [path] if path.is_file() else []
    dirs = extra_dirs if extra_dirs is not None else [Path.home() / "Downloads", Path.home() / "Desktop",
                                                      ROOT, ROOT.parent]
    found: dict[Path, float] = {}
    for folder in dirs:
        try:
            for item in folder.glob(ZIP_PATTERN):
                if item.is_file():
                    found[item.resolve()] = item.stat().st_mtime
        except OSError:
            continue
    return sorted(found, key=lambda p: found[p], reverse=True)


def inspect_zip(zip_path: Path) -> tuple[str, str]:
    """(Version, Ordnerpräfix im ZIP). Wirft ValueError, wenn es kein gültiges Paket ist."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if name.endswith("astral_monitor/version.py"):
                    version = read_version_text(zf.read(info).decode("utf-8", "replace"))
                    if not version:
                        break
                    return version, name[: -len("astral_monitor/version.py")]
    except zipfile.BadZipFile as exc:
        raise ValueError("Die Datei ist keine gültige ZIP-Datei.") from exc
    raise ValueError("Die ZIP enthält kein Anime-Astral-Monitor-Paket (astral_monitor/version.py fehlt).")


def extract(zip_path: Path, prefix: str, tmp: Path) -> Path:
    base = tmp.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name.startswith(prefix) or name.endswith("/"):
                continue
            target = (base / name[len(prefix):]).resolve()
            if base not in target.parents:                       # Schutz vor „../“-Pfaden
                raise ValueError(f"Unsicherer Pfad im ZIP: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
    return base


def verify_tree(root: Path, manifest: dict) -> list[str]:
    problems = []
    for rel, digest in manifest.items():
        path = root / rel
        if not path.is_file():
            problems.append(f"fehlt: {rel}")
        elif file_hash(path, rel) != digest:
            problems.append(f"abweichend: {rel}")
    return problems


# ------------------------------------------------------------------ Dateien austauschen
def sync_files(root: Path, new_root: Path, manifest: dict) -> tuple[list[str], list[str]]:
    """Gibt (aktualisierte, entfernte) Dateien zurück. Daten außerhalb des Pakets bleiben unberührt."""
    removed: list[str] = []
    for folder in PACKAGE_DIRS:
        base = root / folder
        if not base.is_dir():
            continue
        for item in sorted(base.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            rel = item.relative_to(root).as_posix()
            if item.is_file() and ("__pycache__" in item.parts or rel not in manifest):
                item.unlink()
                if "__pycache__" not in item.parts:
                    removed.append(rel)
            elif item.is_dir() and not any(item.iterdir()):
                item.rmdir()
    updated: list[str] = []
    for rel in manifest:
        src, dst = new_root / rel, root / rel
        if dst.is_file() and file_hash(dst, rel) == file_hash(src, rel):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        updated.append(rel)
    shutil.copy2(new_root / "manifest.json", root / "manifest.json")
    return updated, removed


# ------------------------------------------------------------------ Programm läuft?
def is_running(exe_name: str = f"{NAME}.exe") -> bool:
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"], capture_output=True,
                             text=True, timeout=15).stdout
        return exe_name.lower() in out.lower()
    except Exception:
        return False


def wait_until_closed(ask: Ask, what: str) -> None:
    while is_running():
        say(f"\nDer Monitor läuft noch. Bitte beende ihn, bevor {what}.")
        if ask.yes:
            raise SystemExit("Der Monitor läuft noch – bitte zuerst beenden.")
        ask("Danach Enter drücken …")


# ------------------------------------------------------------------ Bauen und installieren
def run_pip(root: Path) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                           "-r", "requirements.txt", "pyinstaller"], cwd=root)


def run_build(root: Path) -> None:
    subprocess.check_call([sys.executable, "build_exe.py", "--no-zip"], cwd=root)


def install_program(new_dir: Path, target: Path, ask: Ask) -> Optional[Path]:
    """Ersetzt den Programmordner und behält eine Sicherung. Gibt den Sicherungsordner zurück."""
    if new_dir.resolve() == target.resolve():
        return None
    backup = target.with_name(target.name + "_backup")
    while True:
        try:
            if backup.exists():
                shutil.rmtree(backup)
            if target.exists():
                target.rename(backup)
            break
        except OSError as exc:
            say(f"\nDer Programmordner ist gesperrt ({exc.__class__.__name__}). Bitte den Monitor beenden.")
            if ask.yes:
                raise
            ask("Danach Enter drücken …")
    try:
        shutil.copytree(new_dir, target)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        if backup.exists():
            backup.rename(target)
        raise
    return backup


def make_shortcut(exe: Path) -> bool:
    if sys.platform != "win32":
        return False
    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        return False
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';"
          "$s.WorkingDirectory='%s';$s.Save()" % (desktop / "Anime Astral Monitor.lnk", exe, exe.parent))
    try:
        return subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                              timeout=30).returncode == 0
    except Exception:
        return False


def load_config(root: Path = ROOT) -> dict:
    try:
        return json.loads((root / CONFIG_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(data: dict, root: Path = ROOT) -> None:
    (root / CONFIG_NAME).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ Hauptablauf
def main(argv: Optional[list[str]] = None, *, pip_fn: Callable = run_pip, build_fn: Callable = run_build,
         root: Path = ROOT, zip_dirs: Optional[list[Path]] = None) -> int:
    parser = argparse.ArgumentParser(description="Anime Astral Monitor – Updater")
    parser.add_argument("zip", nargs="?", help="Pfad zur neuen anime_astral_monitor.zip")
    parser.add_argument("--yes", action="store_true", help="keine Rückfragen")
    parser.add_argument("--install-dir", help="Programmordner (AnimeAstralMonitor.exe)")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--no-pip", action="store_true")
    args = parser.parse_args(argv)
    ask = Ask(args.yes)

    say("=== Anime Astral Monitor – Updater ===")
    say(f"Version im Arbeitsordner: {current_version(root)}")

    # 1) Update-Datei bestimmen
    zips = find_zips(args.zip, zip_dirs)
    new_root: Optional[Path] = None
    tmp = root / ".update_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    manifest: dict = {}
    if zips:
        zip_path = zips[0]
        try:
            version, prefix = inspect_zip(zip_path)
        except ValueError as exc:
            say(f"\nFehler: {exc}\n({zip_path})")
            return 1
        stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(zip_path.stat().st_mtime))
        say(f"Update-Datei: {zip_path}  (vom {stamp}, Version {version})")
        if args.zip is None and len(zips) > 1:
            say(f"({len(zips) - 1} ältere Datei(en) gefunden und ignoriert)")
        newer = version_key(version) > version_key(current_version(root))
        if not newer:
            say("Diese Version ist nicht neuer als die vorhandene.")
        if ask.confirm("Diese Datei jetzt einspielen?" if newer else
                       "Trotzdem einspielen (Dateien werden auf den Stand der ZIP gebracht)?", default=newer):
            tmp.mkdir(parents=True, exist_ok=True)
            try:
                new_root = extract(zip_path, prefix, tmp)
            except ValueError as exc:
                say(f"Fehler: {exc}")
                shutil.rmtree(tmp, ignore_errors=True)
                return 1
            manifest = load_manifest(new_root)
            if not manifest:
                say("Fehler: Die ZIP enthält keine Prüfliste (manifest.json).")
                shutil.rmtree(tmp, ignore_errors=True)
                return 1
            problems = verify_tree(new_root, manifest)
            if problems:
                say("Fehler: Die ZIP ist beschädigt oder unvollständig:")
                for line in problems[:10]:
                    say("   " + line)
                shutil.rmtree(tmp, ignore_errors=True)
                return 1
    else:
        say("Keine anime_astral_monitor*.zip gefunden (gesucht in Downloads, Desktop und Arbeitsordner).")
        say("Tipp: ZIP auf update.bat ziehen.")
        if not ask.confirm("Nur die EXE aus dem vorhandenen Stand neu bauen?", default=False):
            return 1

    wait_until_closed(ask, "die Dateien ersetzt werden")

    # 2) Dateien austauschen
    if new_root is not None:
        say("\n[1/4] Dateien aktualisieren …")
        updated, removed = sync_files(root, new_root, manifest)
        shutil.rmtree(tmp, ignore_errors=True)
        say(f"      {len(updated)} aktualisiert, {len(removed)} veraltete entfernt.")
        say(f"      Version jetzt: {current_version(root)}")
    else:
        say("\n[1/4] Dateien bleiben unverändert.")

    # 3) Pakete + Build
    if not args.no_pip:
        say("\n[2/4] Pakete prüfen …")
        pip_fn(root)
    if not args.no_build:
        say("\n[3/4] EXE bauen – das dauert einige Minuten …")
        build_fn(root)
    new_dir = root / "dist" / NAME
    if not args.no_build and not (new_dir / f"{NAME}.exe").exists() and sys.platform == "win32":
        say("Fehler: Die EXE wurde nicht erzeugt.")
        return 1

    # 4) Installieren
    say("\n[4/4] Programm installieren …")
    config = load_config(root)
    first_time = "install_dir" not in config and not args.install_dir
    target_text = args.install_dir or config.get("install_dir")
    if args.no_build and not target_text:
        say("      (übersprungen)")
        say("\nFertig.")
        return 0
    if not target_text:
        say("Wo soll das Programm liegen (Ordner mit AnimeAstralMonitor.exe)?")
        target_text = ask(f"Pfad eingeben oder Enter für {new_dir}:", str(new_dir))
    target = Path(target_text.strip('"'))
    if not args.install_dir:
        config["install_dir"] = str(target)
        save_config(config, root)

    if not args.no_build:
        wait_until_closed(ask, "das Programm ersetzt wird")
        try:
            backup = install_program(new_dir, target, ask)
        except Exception as exc:
            say(f"Installation fehlgeschlagen: {exc}\nDas Programm bleibt unverändert; neue Version: {new_dir}")
            return 1
        if backup:
            say(f"      Installiert in: {target}\n      Sicherung der alten Version: {backup}")
        else:
            say(f"      Programm liegt in: {new_dir}")
    exe = target / f"{NAME}.exe"

    if first_time and exe.exists() and ask.confirm("Verknüpfung auf dem Desktop anlegen?", default=True):
        say("      Verknüpfung angelegt." if make_shortcut(exe) else "      Verknüpfung konnte nicht angelegt werden.")

    say("\nFertig. Deine Einstellungen und der Verlauf bleiben erhalten.")
    if sys.platform == "win32" and exe.exists() and ask.confirm("Programm jetzt starten?", default=True):
        os.startfile(str(exe))  # type: ignore[attr-defined]
    return 0


def _relaunch_in_venv() -> None:
    """Stellt sicher, dass die Arbeitsumgebung (.venv_build) genutzt wird, falls vorhanden."""
    venv_py = ROOT / ".venv_build" / "Scripts" / "python.exe"
    if sys.platform == "win32" and venv_py.is_file() and Path(sys.executable).resolve() != venv_py.resolve():
        sys.exit(subprocess.call([str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]]))


if __name__ == "__main__":
    _relaunch_in_venv()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\nAbgebrochen.")
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        say(f"\nEin Schritt ist fehlgeschlagen ({exc.cmd[-2] if len(exc.cmd) > 1 else exc.cmd}). "
            "Bitte die Meldungen oben lesen.")
        sys.exit(1)
