"""Anime Astral Monitor – überwacht Roblox-Raids und meldet sie an Discord."""
import os

# Vor dem ersten Import von numpy/OpenCV: Rechenbibliotheken auf einen Thread begrenzen. Sonst legt OpenBLAS je
# Prozessorkern Thread und Puffer an (gemessen 257 statt 32 MB privater Speicher), obwohl das Programm nur kleine
# Bildausschnitte verarbeitet. Tesseract (OpenMP) ebenso – das Spiel soll die Kerne bekommen.
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

from .version import __version__  # noqa: E402,F401
