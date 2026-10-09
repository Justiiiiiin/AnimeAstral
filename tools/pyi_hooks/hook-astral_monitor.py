"""PyInstaller hook: the program's own code as separate .pyc files next to the EXE instead of inside it.

Otherwise every small code change rebuilds AnimeAstralMonitor.exe (~9 MB, the whole code sits in its archive) and
every update package contains it. With the code outside, an update only carries the changed .pyc files (KB); the EXE
only changes with Python or a library."""
module_collection_mode = "pyc"
