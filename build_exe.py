"""Builds the Windows EXE (folder variant) with PyInstaller and packs it as a ZIP.

    python build_exe.py            (or simply double-click build_exe.bat)"""
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
    """Reads the version number directly from the file (without importing the program)."""
    try:
        text = (ROOT / "astral_monitor" / "version.py").read_text(encoding="utf-8", errors="replace")
        match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        if match:
            return match.group(1)
    except OSError:
        pass
    print("Note: version number not found – using 0.0.0.")
    return "0.0.0"


def verify_package() -> None:
    """Compares all files with the package's checklist and reports differences
    (e.g. if an old folder was only partly overwritten)."""
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
        print("\nWARNING: the folder does not match the package:")
        for line in problems:
            print("  ", line)
        print("Recommendation: delete the folder and unpack the ZIP file again completely.\n")
    else:
        print("Package check: all files match.")


def pe_imports(path: Path) -> list[str]:
    """DLL names an EXE/DLL loads (normal and delayed imports), lower case."""
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                           pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    entries = getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) + getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])
    names = [e.dll.decode("ascii", "replace").lower() for e in entries]
    pe.close()
    return names


def tesseract_dlls(folder: Path) -> set[str] | None:
    """All DLLs in the folder that tesseract.exe and libtesseract need (recursively). The UB Mannheim installation
    also contains Pango/Cairo/ICU/GLib for training tools (~45 MB) that the program never loads.
    None = analysis not possible (then copy everything)."""
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
    except Exception as exc:                        # pefile missing or similar: rather ship too much
        print(f"Hinweis: Tesseract-Abhängigkeiten nicht ermittelbar ({exc}) – kopiere alle DLLs.")
        return None


# Remove after PyInstaller: never loaded (the program only uses QtCore/QtGui/QtWidgets, no videos,
# no AVIF/WebP images). Paths relative to _internal, patterns like Path.glob.
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
KEEP = {"PySide6/plugins/imageformats": {"qico.dll"},          # program icon
        "PySide6/translations": {"qtbase_de.qm", "qt_de.qm"}}   # German standard dialogs


def prune(out_dir: Path) -> None:
    """Removes unused parts and then checks that no remaining file needs a removed DLL."""
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
        print("ERROR: clean-up removed required files:\n  " + "\n  ".join(broken))
        raise SystemExit(1)
    print(f"Aufgeräumt: {len(removed)} unbenutzte Teile entfernt ({size / 1048576:.0f} MB).")


def bundle_tesseract(out_dir: Path) -> bool:
    """Copies an existing Tesseract installation (English only) next to the EXE: users don't have to install anything."""
    sys.path.insert(0, str(ROOT))
    from astral_monitor.ocr import find_tesseract
    exe = find_tesseract("")
    if not exe:
        print("Note: Tesseract is not installed on this PC – it will NOT be bundled.")
        return False
    src = Path(exe).resolve().parent
    if src.resolve() == (out_dir / "tesseract").resolve():
        return True
    dst = out_dir / "tesseract"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    needed = tesseract_dlls(src)          # only what tesseract.exe/libtesseract load (without training libraries)
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
        print("Warning: eng.traineddata was not found – Tesseract in the package would be incomplete.")
        shutil.rmtree(dst)
        return False
    size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file()) / 1048576
    print(f"Tesseract mitgeliefert: {dst} ({size:.0f} MB)")
    return True


def write_manifest(out_dir: Path, version: str) -> None:
    """files.json: checksum of every file. With it the updater sees which files changed and loads only those
    (tools/make_patch.py creates the update package from it)."""
    files = {}
    for path in sorted(out_dir.rglob("*")):
        rel = path.relative_to(out_dir).as_posix()
        if path.is_file() and rel != "files.json":
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out_dir / "files.json").write_text(json.dumps({"version": version, "files": files}, indent=1), encoding="utf-8")
    print(f"Dateiliste: {len(files)} Dateien.")


def write_third_party(out_dir: Path) -> None:
    (out_dir / "THIRD_PARTY.txt").write_text(THIRD_PARTY, encoding="utf-8")


THIRD_PARTY = """Anime Astral Monitor uses the following free components (licenses as stated by the projects, please check
yourself before distributing widely):

- Tesseract OCR           Apache License 2.0   https://github.com/tesseract-ocr/tesseract
- Qt for Python (PySide6) LGPL v3 / GPL        https://doc.qt.io/qtforpython-6/  (libraries are included as separate
                                               files and can be replaced)
- OpenCV                  Apache License 2.0   https://opencv.org
- NumPy                   BSD-3-Clause         https://numpy.org
- Pillow                  HPND                 https://python-pillow.org
- requests                Apache License 2.0   https://requests.readthedocs.io
- psutil                  BSD-3-Clause         https://github.com/giampaolo/psutil
- pytesseract             Apache License 2.0   https://github.com/madmaze/pytesseract
- windows-capture         MIT                  https://github.com/NiiightmareXD/windows-capture

The program only sends data to the Discord webhook URL you enter yourself.
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
        "--windowed",                         # no console window
        "--onedir",                           # folder instead of a single file: starts faster, fewer antivirus alarms
        "--icon", str(ROOT / "assets" / "app.ico"),
        "--add-data", f"{ROOT / 'assets'}{os.pathsep}assets",
        "--add-data", f"{ROOT / 'CHANGELOG.md'}{os.pathsep}.",      # “What's new” after an update
        "--add-data", f"{ROOT / 'astral_monitor' / 'uimap'}{os.pathsep}astral_monitor/uimap",   # map (automation)
        "--add-data", f"{ROOT / 'astral_monitor' / 'uimap_static'}{os.pathsep}astral_monitor/uimap_static",  # gear …
        "--add-data", f"{ROOT / 'astral_monitor' / 'regions.json'}{os.pathsep}astral_monitor",  # recognition areas
        "--collect-submodules", "astral_monitor",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    if importlib.util.find_spec("windows_capture") is not None:
        args += ["--collect-all", "windows_capture"]
    else:
        print("Note: “windows-capture” is not installed – the EXE then only uses screen capture.")
    for module in ("cryptography.hazmat.primitives.ciphers.aead", "cryptography.hazmat.primitives.kdf.scrypt",
                   "discord", "discord.app_commands"):
        args += ["--hidden-import", module]   # only imported when used (password export, Discord bot)
    for module in ("tkinter", "matplotlib", "scipy", "pandas", "IPython", "PyQt5", "PyQt6", "PySide2"):
        args += ["--exclude-module", module]

    print("Baue", NAME, __version__, "– this takes a few minutes …")
    pyi.run(args)

    out_dir = ROOT / "dist" / NAME
    exe = out_dir / f"{NAME}.exe"
    if not exe.exists() and not (out_dir / NAME).exists():
        print("Error: the EXE was not created.")
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
