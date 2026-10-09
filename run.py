"""Entry point:  python run.py   (or  pythonw run.py  without a console window)"""
import sys

from astral_monitor.ui.main_window import run

if __name__ == "__main__":
    sys.exit(run())
