"""Baut die Windows-EXE (Ordner-Variante) mit PyInstaller und packt sie als ZIP.

    python build_exe.py            (oder einfach build_exe.bat doppelklicken)
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "AnimeAstralMonitor"


TEXT_SUFFIXES = (".py", ".md", ".bat", ".txt", ".json")


def read_version() -> str:
    """Liest die Versionsnummer direkt aus der Datei (ohne das Programm zu importieren)."""
    try:
        text = (ROOT / "astral_monitor" / "version.py").read_text(encoding="utf-8", errors="replace")
        match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        if match:
            return match.group(1)
    except OSError:
        pass
    print("Hinweis: Versionsnummer nicht gefunden – verwende 0.0.0.")
    return "0.0.0"


def verify_package() -> None:
    """Vergleicht alle Dateien mit der Prüfliste des Pakets und meldet Abweichungen
    (z. B. wenn ein altes Verzeichnis nur teilweise überschrieben wurde)."""
    manifest = ROOT / "manifest.json"
    if not manifest.is_file():
        return
    try:
        expected = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        return
    problems = []
    for rel, digest in expected.items():
        path = ROOT / rel
        if not path.is_file():
            problems.append(f"fehlt:      {rel}")
            continue
        data = path.read_bytes()
        if rel.endswith(TEXT_SUFFIXES):
            data = data.replace(b"\r\n", b"\n")
        if hashlib.sha256(data).hexdigest() != digest:
            problems.append(f"abweichend: {rel}")
    if problems:
        print("\nACHTUNG: Der Ordner stimmt nicht mit dem Paket überein:")
        for line in problems:
            print("  ", line)
        print("Empfehlung: Den Ordner löschen und die ZIP-Datei komplett neu entpacken.\n")
    else:
        print("Paketprüfung: alle Dateien stimmen.")


def pe_imports(path: Path) -> list[str]:
    """DLL-Namen, die eine EXE/DLL lädt (normale und verzögerte Importe), klein geschrieben."""
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                           pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    entries = getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) + getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])
    names = [e.dll.decode("ascii", "replace").lower() for e in entries]
    pe.close()
    return names


def tesseract_dlls(folder: Path) -> set[str] | None:
    """Alle DLLs im Ordner, die tesseract.exe und libtesseract (rekursiv) brauchen. Die Installation von UB Mannheim
    enthält zusätzlich Pango/Cairo/ICU/GLib für Trainingswerkzeuge (~45 MB), die das Programm nie lädt.
    None = Analyse nicht möglich (dann alles kopieren)."""
    try:
        local = {p.name.lower(): p for p in folder.glob("*.dll")}
        todo = ["tesseract.exe"] + [n for n in local if n.startswith("libtesseract")]
        needed = set(todo[1:])
        while todo:
            name = todo.pop()
            for dep in pe_imports(folder / name if name == "tesseract.exe" else local[name]):
                if dep in local and dep not in needed:
                    needed.add(dep)
                    todo.append(dep)
        return needed
    except Exception as exc:                        # pefile fehlt o. Ä.: lieber zu viel mitliefern
        print(f"Hinweis: Tesseract-Abhängigkeiten nicht ermittelbar ({exc}) – kopiere alle DLLs.")
        return None


# Nach PyInstaller entfernen: wird nie geladen (das Programm nutzt nur QtCore/QtGui/QtWidgets, keine Videos,
# keine AVIF/WebP-Bilder). Pfade relativ zu _internal, Muster wie bei Path.glob.
PRUNE = [
    "PySide6/opengl32sw.dll", "PySide6/Qt6Quick*.dll", "PySide6/Qt6Qml*.dll", "PySide6/Qt6Pdf*.dll",
    "PySide6/Qt6Network.dll", "PySide6/QtNetwork.pyd", "PySide6/Qt6OpenGL*.dll", "PySide6/QtOpenGL*.pyd",
    "PySide6/Qt6VirtualKeyboard*.dll", "PySide6/Qt6Svg*.dll", "PySide6/QtSvg*.pyd",
    "PySide6/plugins/tls", "PySide6/plugins/networkinformation", "PySide6/plugins/platforminputcontexts",
    "PySide6/plugins/iconengines", "PySide6/plugins/generic",
    "PySide6/plugins/platforms/qdirect2d.dll", "PySide6/plugins/platforms/qminimal.dll",
    "PySide6/plugins/platforms/qoffscreen.dll",
    "cv2/opencv_videoio_ffmpeg*.dll",
    "PIL/_avif*.pyd", "PIL/_webp*.pyd", "PIL/_imagingtk*.pyd",
]
KEEP = {"PySide6/plugins/imageformats": {"qico.dll"},          # Programmsymbol
        "PySide6/translations": {"qtbase_de.qm", "qt_de.qm"}}   # deutsche Standard-Dialoge


def prune(out_dir: Path) -> None:
    """Entfernt unbenutzte Teile und prüft danach, dass keine verbleibende Datei eine entfernte DLL braucht."""
    internal = out_dir / "_internal"
    removed: list[Path] = []
    for pattern in PRUNE:
        for path in internal.glob(pattern):
            removed.append(path)
    for folder, keep in KEEP.items():
        if (internal / folder).is_dir():
            removed += [p for p in (internal / folder).iterdir() if p.is_file() and p.name.lower() not in keep]
    removed_dlls = {p.name.lower() for p in removed if p.suffix.lower() in (".dll", ".pyd")}
    for path in removed:
        if path.is_dir():
            removed_dlls |= {f.name.lower() for f in path.rglob("*.dll")}
    size = sum((f.stat().st_size for p in removed for f in ([p] if p.is_file() else p.rglob("*")) if f.is_file()))
    for path in removed:
        shutil.rmtree(path) if path.is_dir() else path.unlink()
    broken = []
    for binary in list(out_dir.rglob("*.dll")) + list(out_dir.rglob("*.pyd")) + [out_dir / f"{NAME}.exe"]:
        try:
            missing = [d for d in pe_imports(binary) if d in removed_dlls]
        except Exception:
            continue
        if missing:
            broken.append(f"{binary.relative_to(out_dir)} braucht {', '.join(missing)}")
    if broken:
        print("FEHLER: Aufräumen hat benötigte Dateien entfernt:\n  " + "\n  ".join(broken))
        raise SystemExit(1)
    print(f"Aufgeräumt: {len(removed)} unbenutzte Teile entfernt ({size / 1048576:.0f} MB).")


def bundle_tesseract(out_dir: Path) -> bool:
    """Kopiert eine vorhandene Tesseract-Installation (nur Englisch) neben die EXE: Nutzer müssen nichts installieren."""
    sys.path.insert(0, str(ROOT))
    from astral_monitor.ocr import find_tesseract
    exe = find_tesseract("")
    if not exe:
        print("Hinweis: Tesseract ist auf diesem PC nicht installiert – es wird NICHT mitgeliefert.")
        return False
    src = Path(exe).resolve().parent
    if src.resolve() == (out_dir / "tesseract").resolve():
        return True
    dst = out_dir / "tesseract"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    needed = tesseract_dlls(src)          # nur, was tesseract.exe/libtesseract laden (ohne Trainings-Bibliotheken)
    for item in src.iterdir():
        name = item.name.lower()
        if not item.is_file():
            continue
        if name == "tesseract.exe" or (item.suffix.lower() == ".dll" and (needed is None or name in needed)):
            shutil.copy2(item, dst / item.name)
        elif name in ("tesseract", "license", "licence", "license.txt"):
            shutil.copy2(item, dst / item.name)
    tessdata = src / "tessdata"
    (dst / "tessdata").mkdir()
    for name in ("eng.traineddata",):
        if (tessdata / name).is_file():
            shutil.copy2(tessdata / name, dst / "tessdata" / name)
    for folder in ("configs", "tessconfigs"):
        if (tessdata / folder).is_dir():
            shutil.copytree(tessdata / folder, dst / "tessdata" / folder)
    if not (dst / "tessdata" / "eng.traineddata").is_file():
        print("Warnung: eng.traineddata wurde nicht gefunden – Tesseract im Paket wäre unvollständig.")
        shutil.rmtree(dst)
        return False
    size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file()) / 1048576
    print(f"Tesseract mitgeliefert: {dst} ({size:.0f} MB)")
    return True


def write_manifest(out_dir: Path, version: str) -> None:
    """files.json: Prüfsumme jeder Datei. Damit erkennt der Updater, welche Dateien sich geändert haben, und lädt
    nur diese (tools/make_patch.py erzeugt daraus das Update-Paket)."""
    files = {}
    for path in sorted(out_dir.rglob("*")):
        rel = path.relative_to(out_dir).as_posix()
        if path.is_file() and rel != "files.json":
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out_dir / "files.json").write_text(json.dumps({"version": version, "files": files}, indent=1), encoding="utf-8")
    print(f"Dateiliste: {len(files)} Dateien.")


def write_third_party(out_dir: Path) -> None:
    (out_dir / "THIRD_PARTY.txt").write_text(THIRD_PARTY, encoding="utf-8")


THIRD_PARTY = """Anime Astral Monitor nutzt folgende freie Komponenten (Lizenzen laut Projektangaben, bitte vor einer
breiten Weitergabe selbst prüfen):

- Tesseract OCR           Apache License 2.0   https://github.com/tesseract-ocr/tesseract
- Qt für Python (PySide6) LGPL v3 / GPL        https://doc.qt.io/qtforpython-6/  (Bibliotheken liegen als einzelne
                                               Dateien bei und können ersetzt werden)
- OpenCV                  Apache License 2.0   https://opencv.org
- NumPy                   BSD-3-Clause         https://numpy.org
- Pillow                  HPND                 https://python-pillow.org
- requests                Apache License 2.0   https://requests.readthedocs.io
- psutil                  BSD-3-Clause         https://github.com/giampaolo/psutil
- pytesseract             Apache License 2.0   https://github.com/madmaze/pytesseract
- windows-capture         MIT                  https://github.com/NiiightmareXD/windows-capture

Das Programm sendet Daten ausschließlich an die von dir eingetragene Discord-Webhook-URL.
"""


def main() -> int:
    print("Python", sys.version.split()[0], "·", sys.platform)
    print("Ordner:", ROOT)
    verify_package()
    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller fehlt:  pip install pyinstaller")
        return 1
    import PyInstaller.__main__ as pyi

    __version__ = read_version()

    args = [
        str(ROOT / "run.py"),
        "--name", NAME,
        "--noconfirm", "--clean",
        "--windowed",                         # kein Konsolenfenster
        "--onedir",                           # Ordner statt Einzeldatei: startet schneller, weniger Virenscanner-Alarme
        "--icon", str(ROOT / "assets" / "app.ico"),
        "--add-data", f"{ROOT / 'assets'}{os.pathsep}assets",
        "--add-data", f"{ROOT / 'CHANGELOG.md'}{os.pathsep}.",      # „Was ist neu“ nach einem Update
        "--collect-submodules", "astral_monitor",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    if importlib.util.find_spec("windows_capture") is not None:
        args += ["--collect-all", "windows_capture"]
    else:
        print("Hinweis: „windows-capture“ ist nicht installiert – die EXE nutzt dann nur die Bildschirm-Aufnahme.")
    for module in ("cryptography.hazmat.primitives.ciphers.aead", "cryptography.hazmat.primitives.kdf.scrypt"):
        args += ["--hidden-import", module]   # Export mit Passwort (secure.py) – erst beim Gebrauch importiert
    for module in ("tkinter", "matplotlib", "scipy", "pandas", "IPython", "PyQt5", "PyQt6", "PySide2"):
        args += ["--exclude-module", module]

    print("Baue", NAME, __version__, "– das dauert einige Minuten …")
    pyi.run(args)

    out_dir = ROOT / "dist" / NAME
    exe = out_dir / f"{NAME}.exe"
    if not exe.exists() and not (out_dir / NAME).exists():
        print("Fehler: Die EXE wurde nicht erzeugt.")
        return 1
    prune(out_dir)
    shutil.copy(ROOT / "README.md", out_dir / "LIESMICH.md")
    write_third_party(out_dir)
    if "--no-bundle-tesseract" not in sys.argv:
        bundle_tesseract(out_dir)
    write_manifest(out_dir, __version__)
    if "--no-zip" in sys.argv:
        print(f"\nFertig:\n  Programm: {exe}")
        return 0

    zip_path = ROOT / "dist" / f"{NAME}-{__version__}-win64.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(out_dir.rglob("*")):
            if file.is_file():
                zf.write(file, Path(NAME) / file.relative_to(out_dir))
    size_mb = zip_path.stat().st_size / 1048576
    print(f"\nFertig:\n  Programm: {exe}\n  ZIP:      {zip_path} ({size_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
