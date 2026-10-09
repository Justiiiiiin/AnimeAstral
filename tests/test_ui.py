"""UI smoke test (offscreen, no real window): build the main window, open every page, every settings tab and every
design – any error in the UI code fails the test. Skipped if PySide6 is not installed."""
import os
import sys
import time
import unittest

import _env  # noqa: F401

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication, QScrollArea
except ImportError:                                       # pragma: no cover – CI and the dev setup have PySide6
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class UiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from astral_monitor.engine import Engine
        from astral_monitor.settings import Settings
        from astral_monitor.ui import theme
        from astral_monitor.ui.main_window import MainWindow
        s = Settings()
        from astral_monitor.version import __version__
        s.wizard_done, s.update_check, s.ui_intro, s.seen_version = True, False, False, __version__
        s.save()
        cls.errors = []
        cls._hook = sys.excepthook
        sys.excepthook = lambda *exc: cls.errors.append(exc)    # errors in Qt slots end up here
        theme.apply(cls.app, s.ui_design, s.ui_mode)
        cls.win = MainWindow(Engine(Settings.load()))
        cls.win.resize(1180, 800)
        cls.win.show()
        cls.pump()

    @classmethod
    def tearDownClass(cls):
        sys.excepthook = cls._hook
        cls.win._force_close = True
        cls.win.close()
        cls.pump()

    @classmethod
    def pump(cls, seconds=0.05):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            cls.app.processEvents()

    def assertNoErrors(self, where):
        if self.errors:
            exc = self.errors[0]
            self.fail(f"{where}: {exc[0].__name__}: {exc[1]}")

    def test_every_page_and_tab(self):
        for i in range(len(self.win.pages)):
            self.win.nav.button(i).click()
            self.win._tick()
            self.pump()
            page = self.win.pages[i]
            for btn in getattr(page, "tab_group", None).buttons() if hasattr(page, "tab_group") else []:
                btn.click()
                self.pump()
            self.assertNoErrors(f"page {type(page).__name__}")

    def test_pages_fit_without_scrolling(self):
        """Owner's wish since 0.9.7: no page needs scrolling at the design size."""
        for i in range(len(self.win.pages)):
            self.win.nav.button(i).click()
            self.pump(0.1)
            area = self.win.stack.currentWidget()
            area = area if isinstance(area, QScrollArea) else area.findChild(QScrollArea)
            if area is not None and area.widget() is not None:
                self.assertLessEqual(area.verticalScrollBar().maximum(), 0, type(self.win.pages[i]).__name__)

    def test_every_design(self):
        from astral_monitor.ui import theme
        for key in theme.DESIGNS:
            for mode in ("dark", "light"):
                self.win.set_appearance(design=key, mode=mode)
                self.pump()
                self.assertNoErrors(f"design {key}/{mode}")
        self.win.set_appearance(design=theme.DEFAULT_DESIGN, mode="dark")


if __name__ == "__main__":
    unittest.main()
