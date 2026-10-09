"""Anime Astral Monitor – watches Roblox raids and reports them to Discord."""
import os

# Before the first import of numpy/OpenCV: limit the math libraries to one thread. Otherwise OpenBLAS creates
# a thread and buffers per CPU core (measured 257 instead of 32 MB private memory), although the program only processes
# small image crops. Tesseract (OpenMP) likewise – the game should get the cores.
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

from .version import __version__  # noqa: E402,F401

__all__ = ["__version__"]
