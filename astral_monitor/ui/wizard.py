"""Setup wizard: connect Roblox, find the counter, connect Discord – in a few steps."""
from __future__ import annotations

import cv2
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..settings import is_valid_webhook
from ..i18n import N_, tr
from . import theme
from .widgets import bgr_to_pixmap, label


def set_chip(chip: QLabel, text: str, state: str = "") -> None:
    chip.setText(text)
    chip.setProperty("state", state)
    chip.style().unpolish(chip)
    chip.style().polish(chip)


def chip(text: str = "", state: str = "") -> QLabel:
    lbl = QLabel()
    lbl.setObjectName("chip")
    set_chip(lbl, text, state)
    return lbl


class SetupWizard(QDialog):
    """Five short pages. Nothing is saved until the end (or when continuing past the Discord page)."""

    STEPS = [N_("Welcome"), N_("Roblox"), N_("Counter"), N_("Discord"), N_("Done")]

    def __init__(self, main) -> None:
        super().__init__(main)
        self.main = main
        self.engine = main.engine
        self.setWindowTitle(tr("Setup"))
        self.setModal(True)
        self.resize(780, 600)
        self._frame_ok = False
        self._wave_ok = False
        self._webhook_ok = False

        root = QVBoxLayout(self)
        theme.track_margins(root, 36, 28, 36, 24)
        theme.track_spacing(root, 14)

        self.dots: list[QLabel] = []
        dots = QHBoxLayout()
        theme.track_spacing(dots, 6)
        for _ in self.STEPS:
            dot = QLabel()
            dot.setObjectName("stepdot")
            self.dots.append(dot)
            dots.addWidget(dot)
        dots.addStretch(1)
        self.step_label = label("", "muted")
        dots.addWidget(self.step_label)
        root.addLayout(dots)

        self.stack = QStackedWidget()
        for build in (self._page_welcome, self._page_roblox, self._page_wave, self._page_discord, self._page_done):
            self.stack.addWidget(build())
        root.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        self.btn_skip = QPushButton(tr("Skip"))
        self.btn_skip.clicked.connect(self._skip)
        self.btn_back = QPushButton(tr("Back"))
        self.btn_back.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.btn_next = QPushButton(tr("Next"))
        self.btn_next.setObjectName("primary")
        self.btn_next.clicked.connect(self._next)
        nav.addWidget(self.btn_skip)
        nav.addStretch(1)
        nav.addWidget(self.btn_back)
        nav.addWidget(self.btn_next)
        root.addLayout(nav)
        self._go(0)

    # ------------------------------------------------------------------ Pages
    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        lay = QVBoxLayout(page)
        theme.track_margins(lay, 0, 8, 0, 0)
        theme.track_spacing(lay, 12)
        lay.addWidget(label(title, "hero"))
        lay.addWidget(label(subtitle, "muted", wrap=True))
        return page, lay

    def _page_welcome(self) -> QWidget:
        page, lay = self._page(tr("Welcome 👋"), tr("Four short steps and you are ready. This takes about a "
                                                      "minute."))
        lay.addSpacing(8)
        for text in (tr("Connect the Roblox window"), tr("Find the wave counter automatically"),
                     tr("Set up Discord webhook"), tr("Start monitoring")):
            row = QHBoxLayout()
            row.addWidget(chip("✓", "ok"))
            row.addWidget(label(text))
            row.addStretch(1)
            lay.addLayout(row)
        lay.addStretch(1)
        return page

    def _page_roblox(self) -> QWidget:
        page, lay = self._page(tr("Connect Roblox"), tr("Start Roblox and Anime Astral. The window may also be "
                                                          "covered."))
        row = QHBoxLayout()
        self.chip_window = chip(tr("Window: not checked"))
        self.chip_frame = chip(tr("Image: not checked"))
        row.addWidget(self.chip_window)
        row.addWidget(self.chip_frame)
        row.addStretch(1)
        lay.addLayout(row)
        self.preview_roblox = label("", "preview")
        self.preview_roblox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.track_min_height(self.preview_roblox, 260)
        lay.addWidget(self.preview_roblox, 1)
        btn = QPushButton(tr("Check"))
        btn.clicked.connect(self._check_roblox)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        return page

    def _page_wave(self) -> QWidget:
        page, lay = self._page(tr("Find the wave counter"),
                               tr("Start a raid until “Wave x/100” is visible at the top, then click “Search”."))
        row = QHBoxLayout()
        self.chip_wave = chip(tr("Counter: not checked"))
        row.addWidget(self.chip_wave)
        row.addStretch(1)
        lay.addLayout(row)
        self.preview_wave = label("", "preview")
        self.preview_wave.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.track_min_height(self.preview_wave, 150)
        lay.addWidget(self.preview_wave, 1)
        btn = QPushButton(tr("Search"))
        btn.clicked.connect(self._check_wave)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        return page

    def _page_discord(self) -> QWidget:
        page, lay = self._page(tr("Connect Discord"),
                               tr("Channel settings → Integrations → Webhooks → New webhook → “Copy webhook URL”."))
        self.url = QLineEdit()
        self.url.setPlaceholderText(tr("https://discord.com/api/webhooks/…"))
        self.url.setText(self.engine.settings.webhook_url)
        lay.addWidget(self.url)
        row = QHBoxLayout()
        btn = QPushButton(tr("Send test message"))
        btn.clicked.connect(self._check_webhook)
        self.chip_webhook = chip(tr("Webhook: not checked"))
        row.addWidget(btn)
        row.addWidget(self.chip_webhook)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    def _page_done(self) -> QWidget:
        page, lay = self._page(tr("All set ✨"), tr("You can change the settings at any time. Good luck!"))
        self.summary = QVBoxLayout()
        lay.addLayout(self.summary)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------------ Actions
    def _check_roblox(self) -> None:
        from ..engine import EngineError
        from ..winapi import find_window
        self.main.apply_form()
        title = self.engine.settings.window_title
        found = find_window(title) is not None
        set_chip(self.chip_window, (tr("Window “{title}” found", title=title) if found else tr("Window “{title}” not found", title=title)),
                 "ok" if found else "bad")
        self._frame_ok = False
        set_chip(self.chip_frame, tr("Image: not checked"))
        self.preview_roblox.clear()
        if found:
            try:
                res = self.engine.grab_for_ui(full=True)
            except EngineError as exc:
                set_chip(self.chip_frame, str(exc)[:70], "bad")
                res = None
            else:
                if res is None or res.full is None:
                    set_chip(self.chip_frame, tr("No image received (window minimized?)"), "bad")
                else:
                    set_chip(self.chip_frame, tr("Image {w} × {h} ✓", w=res.size[0], h=res.size[1]), "ok")
                    self.preview_roblox.setPixmap(bgr_to_pixmap(res.full, 620))
                    self._frame_ok = True
        self._update_nav()

    def _check_wave(self) -> None:
        from ..engine import EngineError
        self.main.apply_form()
        self._wave_ok = False
        self.preview_wave.clear()
        try:
            result = self.engine.test_wave()
        except EngineError as exc:
            set_chip(self.chip_wave, str(exc)[:80], "bad")
            self._update_nav()
            return
        if not result["ok"]:
            set_chip(self.chip_wave, result["error"][:80], "bad")
        else:
            reading = result["reading"]
            preview = result["crop"].copy()
            if result.get("box"):
                x0, y0, x1, y1 = result["box"]
                cv2.rectangle(preview, (x0, y0), (x1 - 1, y1 - 1), (80, 214, 61), 2)
            self.preview_wave.setPixmap(bgr_to_pixmap(preview, 640))
            if reading:
                set_chip(self.chip_wave, tr("Counter found: {value}/{total} ✓", value=reading.value, total=reading.total), "ok")
                self._wave_ok = True
            else:
                set_chip(self.chip_wave, tr("No counter detected – is a raid running?"), "bad")
        self._update_nav()

    def _check_webhook(self) -> None:
        url = self.url.text().strip()
        if not is_valid_webhook(url):
            set_chip(self.chip_webhook, tr("This does not look like a webhook URL"), "bad")
            return
        set_chip(self.chip_webhook, tr("Sending …"))
        self.main.test_webhook(url, self._webhook_done)

    def _webhook_done(self, ok: bool, info: str) -> None:
        self._webhook_ok = ok
        set_chip(self.chip_webhook, tr("Test message sent ✓") if ok else tr("Failed: {error}", error=info[:60]),
                 "ok" if ok else "bad")
        if ok:
            self.main.set_webhook(self.url.text().strip())
        self._update_nav()

    # ------------------------------------------------------------------ Navigation
    def _update_nav(self) -> None:
        i = self.stack.currentIndex()
        needs = {1: self._frame_ok, 2: self._wave_ok, 3: self._webhook_ok}
        self.btn_next.setEnabled(needs.get(i, True))

    def _go(self, index: int) -> None:
        index = max(0, min(len(self.STEPS) - 1, index))
        self.stack.setCurrentIndex(index)
        for k, dot in enumerate(self.dots):
            dot.setProperty("state", "active" if k == index else ("done" if k < index else ""))
            dot.style().unpolish(dot)
            dot.style().polish(dot)
        last = index == len(self.STEPS) - 1
        self.step_label.setText(tr("Step {n} of {count} · {name}", n=index + 1, count=len(self.STEPS), name=tr(self.STEPS[index])))
        self.btn_back.setVisible(index > 0)
        self.btn_skip.setVisible(0 < index)
        self.btn_skip.setText(tr("Save only") if last else tr("Skip"))
        self.btn_next.setText(tr("Let’s go") if index == 0 else (tr("Start monitoring") if last else tr("Next")))
        if last:
            self._fill_summary()
        self._update_nav()

    def _fill_summary(self) -> None:
        while self.summary.count():
            item = self.summary.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for text, ok in ((tr("Roblox connected"), self._frame_ok), (tr("Wave counter found"), self._wave_ok),
                         (tr("Discord connected"), self._webhook_ok or is_valid_webhook(self.engine.settings.webhook_url))):
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(chip("✓" if ok else "–", "ok" if ok else ""))
            lay.addWidget(label(text if ok else text + tr(" (later under “Alerts”)")))
            lay.addStretch(1)
            self.summary.addWidget(row)

    def _skip(self) -> None:
        if self.stack.currentIndex() == len(self.STEPS) - 1:
            self.main.finish_wizard(start=False)
            self.accept()
        else:
            self._go(self.stack.currentIndex() + 1)

    def _next(self) -> None:
        i = self.stack.currentIndex()
        if i == len(self.STEPS) - 1:
            self.main.finish_wizard(start=True)
            self.accept()
        else:
            self._go(i + 1)

    def reject(self) -> None:                    # closing the window = continue later (wizard stays “open”)
        super().reject()
