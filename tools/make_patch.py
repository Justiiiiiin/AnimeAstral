"""Creates the file list and update package for a release (called by the GitHub build).

    python tools/make_patch.py <version> <program folder> <output folder> [<file list of the previous version>]

Output: files-<version>.json (checksums of all files) and – if the previous file list is available –
AnimeAstralMonitor-Update-<version>.zip with only the files that changed since then. Installed programs
of the previous version then load only this small package instead of the full installer."""
import json
import sys
import zipfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    version, app, out = sys.argv[1].lstrip("vV"), Path(sys.argv[2]), Path(sys.argv[3])
    prev_path = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    manifest = json.loads((app / "files.json").read_text(encoding="utf-8"))
    files: dict = manifest["files"]
    out.mkdir(parents=True, exist_ok=True)

    prev = None
    if prev_path and prev_path.is_file():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except ValueError:
            prev = None
    if prev and isinstance(prev.get("files"), dict) and str(prev.get("version")) != version:
        changed = sorted(p for p, digest in files.items() if prev["files"].get(p) != digest)
        zip_path = out / f"AnimeAstralMonitor-Update-{version}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for rel in changed:
                zf.write(app / rel, rel)
        manifest["patch"] = {"base": prev.get("version"), "contains": changed}
        full = sum((app / p).stat().st_size for p in files) / 1048576
        print(f"Update-Paket {prev.get('version')} -> {version}: {len(changed)} von {len(files)} Dateien, "
              f"{zip_path.stat().st_size / 1048576:.1f} MB (Programm gesamt {full:.0f} MB)")
    else:
        print("No file list of the previous version – full installer only.")
    (out / f"files-{version}.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
