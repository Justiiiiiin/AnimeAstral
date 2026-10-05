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
    for item in src.iterdir():
        if item.is_file() and (item.suffix.lower() in (".dll", ".exe") and (item.name.lower() == "tesseract.exe"
                                                                            or item.suffix.lower() == ".dll")):
            shutil.copy2(item, dst / item.name)
        elif item.is_file() and item.name.lower() in ("tesseract", "license", "licence", "license.txt"):
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
        "--collect-submodules", "astral_monitor",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    if importlib.util.find_spec("windows_capture") is not None:
        args += ["--collect-all", "windows_capture"]
    else:
        print("Hinweis: „windows-capture“ ist nicht installiert – die EXE nutzt dann nur die Bildschirm-Aufnahme.")
    for module in ("tkinter", "matplotlib", "scipy", "pandas", "IPython", "PyQt5", "PyQt6", "PySide2"):
        args += ["--exclude-module", module]

    print("Baue", NAME, __version__, "– das dauert einige Minuten …")
    pyi.run(args)

    out_dir = ROOT / "dist" / NAME
    exe = out_dir / f"{NAME}.exe"
    if not exe.exists() and not (out_dir / NAME).exists():
        print("Fehler: Die EXE wurde nicht erzeugt.")
        return 1
    shutil.copy(ROOT / "README.md", out_dir / "LIESMICH.md")
    write_third_party(out_dir)
    if "--no-bundle-tesseract" not in sys.argv:
        bundle_tesseract(out_dir)
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
