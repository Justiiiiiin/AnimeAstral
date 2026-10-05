"""Gemeinsame Testumgebung: eigener Datenordner, Paket im Suchpfad."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = tempfile.mkdtemp(prefix="astral_test_")
os.environ["ASTRAL_DATA_DIR"] = DATA
atexit.register(shutil.rmtree, DATA, True)
