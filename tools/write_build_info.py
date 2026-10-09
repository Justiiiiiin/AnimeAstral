"""Writes version and repository details into the package (called by the GitHub build).

    python tools/write_build_info.py <version> [<user/repo>] [<discord application id>]"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    version = sys.argv[1].lstrip("vV")
    if not re.fullmatch(r"\d+(\.\d+){1,3}(-beta\.\d+)?", version):
        print(f"Ungültige Versionsnummer: {version!r} (erwartet z. B. 0.5.1 oder 0.5.1-beta.1)")
        return 2
    repo = sys.argv[2] if len(sys.argv) > 2 else ""
    rpc_id = sys.argv[3] if len(sys.argv) > 3 else ""
    (ROOT / "astral_monitor" / "version.py").write_text(
        f'"""Versionsnummer (eigene Datei, damit der Build sie ohne Import des Programms lesen kann)."""\n\n'
        f'__version__ = "{version}"\n', encoding="utf-8")
    (ROOT / "astral_monitor" / "build_info.py").write_text(
        '"""Build-Angaben. Der GitHub-Build überschreibt diese Datei (tools/write_build_info.py)."""\n\n'
        f'GITHUB_REPO = "{repo}"\nRPC_CLIENT_ID = "{rpc_id}"\n', encoding="utf-8")
    print(f"Version {version}, Repository {repo or '(keins)'} geschrieben.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
