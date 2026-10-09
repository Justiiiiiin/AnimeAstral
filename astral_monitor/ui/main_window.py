"""Main window: sidebar + pages, tick to refresh the display."""
from __future__ import annotations

import copy
import logging
import queue
import sys
import threading
import time
from typing import Callable, Optional

from PySide6.QtCore import (QEasingCurve, QEvent, QLibraryInfo, QLockFile, QProcess, QPropertyAnimation, QSize,
                            Qt, QTimer, QTranslator)
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy, QStackedWidget,
                               QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)

from .. import app_paths, i18n, messages, roblox_join, winapi
from ..i18n import tr
from ..version import __version__
from ..engine import Engine, EngineError
from ..hotkeys import HotkeyListener
from .. import updater
from ..discord_client import DiscordSender
from ..automonitor import AutoMonitor, phase_of
from ..settings import Settings, clean_favorites, is_valid_webhook
from . import theme
from .page_alerts import AlertsPage
from .page_monitor import MonitorPage
from .page_settings import SettingsPage
from .page_stats import StatsPage
from .widgets import ToggleSwitch, label, scroll_page


# Pages in the icon bar (since 0.9.0 without “Raids” and “Recognition”: raids are under Settings → Roblox,
# the recognition is built in)
PAGE_MONITOR, PAGE_STATS, PAGE_ALERTS, PAGE_SETTINGS = range(4)
PAGE_COUNT = 4


class PageList:
    """Build pages only when first opened: fewer controls = faster start and design switch (Qt restyles every element
    on a switch, ~0.35 ms each). Index access builds the page; loops only see built pages (e.g. applying the
    settings – pages never opened changed nothing)."""

    def __init__(self, build) -> None:
        self._build = build
        self._pages: list = [None] * PAGE_COUNT

    def __len__(self) -> int:
        return len(self._pages)

    def __getitem__(self, index: int):
        if self._pages[index] is None:
            self._pages[index] = self._build(index)
        return self._pages[index]

    def __iter__(self):
        return (p for p in self._pages if p is not None)

    def built(self, index: int):
        """Page if already built – otherwise None (for hints like “reload statistics”)."""
        return self._pages[index]


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine
        self._ui_calls: "queue.Queue[Callable[[], None]]" = queue.Queue()
        if engine.settings.debug_view:                   # the debug view only collects when switched on
            from .events_card import set_debug
            set_debug(True)
        self._status_key = None
        self.setWindowTitle(f"Anime Astral Monitor {__version__}")
        # a bit larger than the design (1180 × 800), especially taller: that way everything fits on the start page
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        width, height = 1260, 900
        if avail is not None:
            width, height = min(width, int(avail.width() * 0.95)), min(height, int(avail.height() * 0.92))
        self.resize(width, height)
        self.setMinimumSize(760, 520)              # smaller works because the UI scales along (theme.set_scale)
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.setInterval(150)         # rescale only after dragging (smooth)
        self._scale_timer.timeout.connect(self._apply_scale)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # header: program name, Anti-AFK switch with countdown
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        self._top = top
        theme.track_margins(top, 16, 8, 16, 8)
        theme.track_spacing(top, 10)
        self.brandmark = label("", "brandmark")
        top.addWidget(self.brandmark)
        self.brand = brand = label(tr("Anime Astral Monitor"), "brand")
        brand.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # shorten when space is tight,
        brand.setMinimumWidth(theme.px(40))                                    # not the buttons
        top.addWidget(brand, 1)
        self.pill = QFrame()                           # Nebula: status as a pill instead of a box in the sidebar
        self.pill.setObjectName("pill")
        pill_row = QHBoxLayout(self.pill)
        theme.track_margins(pill_row, 12, 4, 14, 4)
        theme.track_spacing(pill_row, 6)
        self.pill_text = label(tr("Stopped"), "muted")
        pill_row.addWidget(self.pill_text)
        top.addWidget(self.pill)
        self.top_toast = label("", "small")
        self.top_toast.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.top_toast, 1)
        top.addStretch(1)
        afk_label = label(tr("Anti-AFK"), "muted")
        afk_label.setToolTip(tr("Every few minutes briefly brings each Roblox window to the front (minimized ones "
                                "stay open afterwards), presses Esc 4 times and switches back – against the "
                                "disconnect after 20 minutes. Interval: Settings → Anti-AFK."))
        self.afk_info = label("", "small")
        self.afk_switch = ToggleSwitch()
        self.afk_switch.setToolTip(afk_label.toolTip())
        self.afk_switch.setChecked(engine.settings.anti_afk_enabled)
        self.afk_switch.toggled.connect(self.set_anti_afk)
        self.join_btn = QToolButton()
        self.join_btn.setObjectName("slim")
        self.join_btn.setText(tr("Join server"))
        self.join_btn.setToolTip(tr("Click: join the marked server. Arrow: choose another saved server (manage "
                                    "under Settings → Private server)."))
        self.join_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        join_menu = QMenu(self.join_btn)
        join_menu.aboutToShow.connect(lambda: self._fill_server_menu(join_menu))
        self.join_btn.setMenu(join_menu)
        self.join_btn.clicked.connect(lambda: self.join_private_server())
        top.addWidget(self.join_btn)
        top.addSpacing(theme.px(12))
        top.addWidget(afk_label)
        top.addLayout(self._stacked(self.afk_info, self.afk_switch))   # countdown small above the switch
        top.addSpacing(theme.px(12))
        rejoin_label = label(tr("Auto-rejoin"), "muted")
        rejoin_label.setToolTip(tr("Automatically rejoins your private server after a disconnect, kick or crash "
                                   "(link under Settings → Private server). If you close Roblox or leave the game "
                                   "yourself, it does not bring you back."))
        self.rejoin_info = label("", "small")
        self.rejoin_switch = ToggleSwitch()
        self.rejoin_switch.setToolTip(rejoin_label.toolTip())
        self.rejoin_switch.setChecked(engine.settings.auto_rejoin_enabled)
        self.rejoin_switch.toggled.connect(self.set_auto_rejoin)
        top.addWidget(rejoin_label)
        top.addLayout(self._stacked(self.rejoin_info, self.rejoin_switch))
        top.addSpacing(theme.px(12))
        auto_label = label(tr("Auto-start"), "muted")
        auto_label.setToolTip(tr("Starts monitoring as soon as you enter Anime Astral, pauses on a disconnect and "
                                 "stops when you leave the game. Starting/stopping it yourself always takes "
                                 "priority."))
        self.auto_info = label("", "small")
        self.auto_switch = ToggleSwitch()
        self.auto_switch.setToolTip(auto_label.toolTip())
        self.auto_switch.setChecked(engine.settings.auto_monitor)
        self.auto_switch.toggled.connect(self.set_auto_monitor)
        top.addWidget(auto_label)
        top.addLayout(self._stacked(self.auto_info, self.auto_switch))
        self.auto = AutoMonitor()
        self._auto_error = ""
        outer.addWidget(topbar)

        body = QWidget()
        root = QHBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        outer.addWidget(body, 1)

        self.sidebar = sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        theme.track(sidebar, lambda o, f: o.setFixedWidth(round((76 if theme.design_info().get("rail") else 208) * f)))
        side = QVBoxLayout(sidebar)
        theme.track_margins(side, 12, 16, 12, 16)
        theme.track_spacing(side, 4)
        self.rail_logo = label("", "brandmark")        # Nebula: logo at the top of the icon bar
        self.rail_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.track(self.rail_logo, lambda o, f: o.setContentsMargins(0, 0, 0, round(12 * f)))   # spacing only with the logo
        side.addWidget(self.rail_logo)

        from .macro_controller import MacroController
        self.macro = MacroController(self)                # macro: map, navigator, log (before the pages)
        self.stack = QStackedWidget()
        self._page_classes = [MonitorPage, StatsPage, AlertsPage, SettingsPage]
        self._hotkey_status: Optional[tuple] = None
        self.pages = PageList(self._build_page)
        names = [tr("Monitoring"), tr("Statistics"), tr("Alerts"), tr("Settings")]
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self._nav_icons = ["monitor", "stats", "alerts", "settings"]
        self._nav_names = names
        for i, name in enumerate(names):
            btn = QPushButton(name)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            theme.track(btn, lambda o, f: o.setIconSize(QSize(round(18 * f), round(18 * f))))
            self.nav.addButton(btn, i)
            side.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
            placeholder = QWidget()                       # replaced by the page when opened for the first time
            placeholder.setProperty("glass", True)
            self.stack.addWidget(placeholder)
        self.nav.button(0).setChecked(True)
        self.nav.idClicked.connect(self._go)
        self._fade = None
        self._mount_controls()
        side.addStretch(1)

        self.toast = label("", "small", wrap=True)
        side.addWidget(self.toast)
        bottom = QHBoxLayout()
        theme.track_spacing(bottom, 6)
        self.status_box = QFrame()
        self.status_box.setObjectName("statusbox")
        box = QVBoxLayout(self.status_box)
        theme.track_margins(box, 12, 10, 12, 10)
        theme.track_spacing(box, 2)
        self.status_title = label(tr("Stopped"), "muted")
        self.status_sub = label("", "small")
        box.addWidget(self.status_title)
        box.addWidget(self.status_sub)
        bottom.addWidget(self.status_box, 1)
        self.gear = QToolButton()                      # design “Astral”: settings as a gear at the bottom left
        self.gear.setObjectName("gear")
        self.gear.setCheckable(True)
        self.gear.setToolTip(tr("Settings"))
        self.gear.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.track(self.gear, lambda o, f: o.setIconSize(QSize(round(22 * f), round(22 * f))))
        self.gear.clicked.connect(lambda: self.nav.button(PAGE_SETTINGS).click())
        self.notes_btn = QToolButton()                 # notebook (only with beta updates)
        self.notes_btn.setObjectName("gear")
        self.notes_btn.setToolTip(tr("Notebook (beta)"))
        self.notes_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.track(self.notes_btn, lambda o, f: o.setIconSize(QSize(round(22 * f), round(22 * f))))
        self.notes_btn.clicked.connect(self.open_notes)
        self._notes = None
        self._intro_done = False
        from .spooky import SpookyScheduler
        self._spooky = SpookyScheduler(self, lambda: self.engine.settings.ui_spooky)
        from .newdots import NewDots
        self.new_dots = NewDots(engine.settings, self._save_quietly)
        self.avatar = QLabel()                          # own Roblox profile (avatar)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setVisible(False)
        side.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignHCenter)
        self.season_mark = QLabel()                     # seasonal decoration in the sidebar (e.g. pumpkin)
        self.season_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.season_mark.setVisible(False)
        side.addWidget(self.season_mark, 0, Qt.AlignmentFlag.AlignHCenter)
        side.addWidget(self.notes_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        bottom.addWidget(self.gear, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        side.addLayout(bottom)

        root.addWidget(sidebar)
        from .backdrop import Backdrop, mark_glass
        self.backdrop = Backdrop(self.stack)
        root.addWidget(self.backdrop, 1)
        mark_glass(self.stack)
        self.backdrop.set_image(engine.settings.ui_background, engine.settings.ui_background_dim)
        self.setCentralWidget(central)
        self.pages[0]                                     # start page right away, all others when first opened
        self._update_join_btn()
        theme.on_change(self._apply_design)
        self._apply_design()
        try:                                       # “Like Windows”: apply light/dark changes right away
            QApplication.styleHints().colorSchemeChanged.connect(lambda _s: self._follow_system())
        except Exception:
            pass

        self._hotkeys: Optional[HotkeyListener] = None
        self._hotkey_sig = None
        self._setup_hotkeys()
        self._force_close = False
        if not engine.settings.wizard_done:
            QTimer.singleShot(500, self.open_wizard)        # at the first start: setup wizard
        else:
            QTimer.singleShot(1500, self._whats_new)        # after an update: a short “What's new”
            QTimer.singleShot(600, self._attach_new_dots)
        QTimer.singleShot(4000, updater.cleanup_downloads)               # remove leftovers of earlier updates
        QTimer.singleShot(5000, self._refresh_icons_once)
        QTimer.singleShot(2500, lambda: self.set_roblox_name(self.engine.settings.roblox_username, quiet=True))
        QTimer.singleShot(6000, lambda: self.check_updates(False))     # quietly in the background (at most every 6 hours)

        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        from .bot_bridge import BotBridge
        self.bot = BotBridge(self)                         # the user's own Discord bot (off by default)
        QTimer.singleShot(3000, self.bot.apply_settings)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.open_search)   # Ctrl+F: search settings

        # Clean up memory: after the start, then every 10 minutes and when minimizing (see winapi.trim_memory)
        self.trim_timer = QTimer(self)
        self.trim_timer.setInterval(10 * 60 * 1000)
        self.trim_timer.timeout.connect(winapi.trim_memory)
        self.trim_timer.start()
        QTimer.singleShot(30_000, winapi.trim_memory)
        self._quitting = False
        self._tray_hint_shown = False
        self.tray = self._setup_tray()
        show_request_file().unlink(missing_ok=True)          # leftover of an earlier run

    def _build_page(self, index: int) -> QWidget:
        """Build a page, put it at its place in the stack and fill it with the current settings."""
        from .backdrop import mark_glass
        page = self._page_classes[index](self)
        page.setProperty("page", True)
        wrapper = self._with_savebar(page) if getattr(page, "SAVES", False) else scroll_page(page)
        old = self.stack.widget(index)
        self.stack.insertWidget(index, wrapper)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()
        mark_glass(wrapper)
        page.load(self.engine.settings)
        if index == PAGE_SETTINGS:
            if self._hotkey_status is not None:
                page.set_hotkey_status(*self._hotkey_status)
            if hasattr(page, "show_profile"):
                page.show_profile()
            if self.engine.settings.wizard_done:
                for btn in page.tab_group.buttons():
                    self.new_dots.attach(f"tab:{btn.property('group')}", btn)
        return page

    def _with_savebar(self, page: QWidget) -> QWidget:
        """Page with settings: scrolls, the save bar always stays visible at the bottom."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        area = scroll_page(page)
        lay.addWidget(area, 1)
        bar = QFrame()
        bar.setObjectName("savebar")
        row = QHBoxLayout(bar)
        theme.track_margins(row, 28, 10, 28, 10)
        row.addWidget(label(tr("Changes apply after saving."), "small"))
        row.addStretch(1)
        save = QPushButton(tr("Save"))
        save.setObjectName("primary")
        theme.track_min_width(save, 140)
        save.clicked.connect(lambda: self.save_settings())
        row.addWidget(save)
        lay.addWidget(bar)
        box.widget = lambda: page                  # like QScrollArea.widget() (check tools)
        return box

    # --------------------------------------------------------------- Tray
    def _setup_tray(self) -> Optional[QSystemTrayIcon]:
        """Icon next to the clock: closing the window = keep running in the background (no autostart)."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(self.windowIcon() if not self.windowIcon().isNull()
                               else QApplication.windowIcon(), self)
        menu = QMenu(self)
        menu.addAction(tr("Open"), self.show_from_tray)
        self.tray_toggle = menu.addAction(tr("Start monitoring"), self.toggle_monitoring)
        self.tray_pause = menu.addAction(tr("Pause"), self.toggle_pause)
        servers = menu.addMenu(tr("Join server"))
        servers.aboutToShow.connect(lambda: self._fill_server_menu(servers))
        self.tray_afk = menu.addAction(tr("Anti-AFK"))
        self.tray_afk.setCheckable(True)
        self.tray_afk.toggled.connect(lambda on: self.afk_switch.setChecked(on))
        self.tray_rejoin = menu.addAction(tr("Auto-rejoin"))
        self.tray_rejoin.setCheckable(True)
        self.tray_rejoin.toggled.connect(lambda on: self.rejoin_switch.setChecked(on))
        self.tray_auto = menu.addAction(tr("Auto-start"))
        self.tray_auto.setCheckable(True)
        self.tray_auto.toggled.connect(lambda on: self.auto_switch.setChecked(on))
        self.tray_notes = menu.addAction(tr("Notebook"), self.open_notes)
        menu.addSeparator()
        menu.addAction(tr("Quit"), self.quit_app)
        menu.aboutToShow.connect(self._update_tray_menu)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self.show_from_tray()
                               if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                                             QSystemTrayIcon.ActivationReason.Trigger) else None)
        tray.setToolTip(f"Anime Astral Monitor {__version__}")
        tray.show()
        return tray

    def _save_quietly(self) -> None:
        try:
            self.engine.settings.save()
        except OSError:
            pass

    def _attach_new_dots(self) -> None:
        """“New” dots on the icon bar (or the gear) and the settings tabs."""
        if not self.engine.settings.wizard_done:
            return
        for i in range(self.nav.buttons().__len__()):
            self.new_dots.attach(f"nav:{i}", self.gear if i == PAGE_SETTINGS and self.gear.isVisible()
                                 else self.nav.button(i))
        settings_page = self.pages.built(PAGE_SETTINGS)               # otherwise tab dots when building the page
        if settings_page is not None:
            for btn in settings_page.tab_group.buttons():
                self.new_dots.attach(f"tab:{btn.property('group')}", btn)

    def _whats_new(self) -> None:
        if self.isVisible():                            # don't push it when the program starts in the tray
            from .whats_new import show_if_updated
            show_if_updated(self)

    # --------------------------------------------------------------- Roblox profile
    def set_roblox_name(self, name: str, done: Optional[Callable] = None, quiet: bool = False) -> None:
        """Set/refresh the profile: saves the name, loads the avatar in the background (at most once a day)."""
        from .. import roblox_profile
        s = self.engine.settings
        if name != s.roblox_username:
            s.roblox_username = name
            try:
                s.save()
            except OSError:
                pass
        if not name:
            roblox_profile.clear()
            self._show_avatar()
            if done:
                done()
            return
        if quiet and not roblox_profile.needs_refresh(name, roblox_profile.load_info()):
            self._show_avatar()
            return

        def work() -> None:
            try:
                roblox_profile.refresh(name)
                error = ""
            except roblox_profile.ProfileError as exc:
                error = str(exc)
            self.post(lambda: (self._show_avatar(), done(error) if done else None))

        threading.Thread(target=work, daemon=True).start()
        self._show_avatar()

    def _show_avatar(self) -> None:
        from .. import roblox_profile
        from .widgets import round_pixmap
        info = roblox_profile.load_info() if self.engine.settings.roblox_username else None
        pix = round_pixmap(roblox_profile.avatar_file(), theme.px(38)) if info else None
        self.avatar.setVisible(pix is not None)
        if pix is not None:
            self.avatar.setPixmap(pix)
            self.avatar.setToolTip(f"{info.get('display', '')} (@{info.get('name', '')})")
        if self.pages.built(PAGE_SETTINGS) is not None:
            self.pages.built(PAGE_SETTINGS).show_profile()

    def _refresh_icons_once(self) -> None:
        """Once after every update: refresh the Windows icon cache (otherwise shortcuts keep the old logo)."""
        s = self.engine.settings
        if not getattr(sys, "frozen", False) or s.icons_refreshed == __version__:
            return
        winapi.refresh_shell_icons()
        s.icons_refreshed = __version__
        try:
            s.save()
        except OSError:
            pass

    def open_notes(self) -> None:
        from .notes_window import NotesWindow
        if self._notes is None:
            self._notes = NotesWindow(self)
        self._notes.show()
        self._notes.raise_()
        self._notes.activateWindow()

    def _update_tray_menu(self) -> None:
        self.tray_notes.setVisible(self.engine.settings.update_beta)
        running = self.engine.running
        self.tray_toggle.setText(tr("Stop the monitoring") if running else tr("Start monitoring"))
        self.tray_pause.setEnabled(running)
        self.tray_pause.setText(tr("Resume") if self.engine.state.paused else tr("Pause"))
        self.tray_afk.blockSignals(True)
        self.tray_afk.setChecked(self.afk_switch.isChecked())
        self.tray_afk.blockSignals(False)
        self.tray_rejoin.blockSignals(True)
        self.tray_rejoin.setChecked(self.rejoin_switch.isChecked())
        self.tray_rejoin.blockSignals(False)
        self.tray_auto.blockSignals(True)
        self.tray_auto.setChecked(self.auto_switch.isChecked())
        self.tray_auto.blockSignals(False)

    # --------------------------------------------------------------- Private server
    def join_private_server(self) -> None:
        """Start Roblox directly in the marked server favorite."""
        s = self.engine.settings
        if not s.private_server_link:
            self.show_from_tray()
            self.nav.button(PAGE_SETTINGS).click()                  # open the settings
            QMessageBox.information(self, tr("Private server"),
                                    tr("Please add a server first under Settings → Private server."))
            return
        ok, info = roblox_join.join(s.private_server_link)
        name = self.active_server_name()
        if ok and name:
            info = tr("Roblox is starting and joining “{name}” …", name=name)
        self.engine._event(info, "info" if ok else "warn")
        if ok:
            self.show_toast(info)
        else:
            QMessageBox.warning(self, tr("Private server"), info)

    def active_server_name(self) -> str:
        s = self.engine.settings
        return next((f["name"] for f in s.server_favorites if f["link"] == s.private_server_link), "")

    def join_favorite(self, index: int) -> None:
        """Server from the menu: becomes the marked server (also for auto-rejoin) and is joined right away."""
        favs = self.engine.settings.server_favorites
        if 0 <= index < len(favs):
            self.set_server_favorites(favs, favs[index]["link"])
            self.join_private_server()

    def set_server_favorites(self, favorites: list, active_link: str) -> None:
        """Change favorites (saved right away – like the raids, without the save bar)."""
        s = self.engine.settings
        s.server_favorites = clean_favorites(favorites)
        links = [f["link"] for f in s.server_favorites]
        s.private_server_link = active_link if active_link in links else (links[0] if links else "")
        try:
            s.save()
        except OSError as exc:
            QMessageBox.critical(self, tr("Save"), tr("Could not save: {error}", error=exc))
        if self.pages.built(PAGE_SETTINGS) is not None:
            self.pages.built(PAGE_SETTINGS).load_servers(s)
        self._update_join_btn()

    def _update_join_btn(self) -> None:
        name = self.active_server_name()
        self.join_btn.setText(tr("Join: {name}", name=name) if name else tr("Join server"))

    def _fill_server_menu(self, menu: QMenu) -> None:
        menu.clear()
        s = self.engine.settings
        for i, fav in enumerate(s.server_favorites):
            act = menu.addAction(fav["name"], lambda i=i: self.join_favorite(i))
            act.setCheckable(True)
            act.setChecked(fav["link"] == s.private_server_link)
        if not s.server_favorites:
            menu.addAction(tr("No servers saved yet")).setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Manage servers …"), self._manage_servers)

    def _manage_servers(self) -> None:
        self.show_from_tray()
        self.nav.button(PAGE_SETTINGS).click()

    # --------------------------------------------------------------- Raid selection
    def select_raid(self, name: str) -> None:
        """Set the current raid (start page, raids page) – effective and saved right away."""
        self.engine.set_current_raid(name)
        try:
            self.engine.settings.save()
        except OSError:
            pass
        self.pages[0].reload_raids()
        self.show_toast(tr("Current raid: {name}", name=name) if name else tr("No raid selected"))

    def raids_changed(self) -> None:
        """After creating/renaming/deleting: refresh the selection and the statistics."""
        self.pages[0].reload_raids()
        if self.pages.built(1) is not None:
            self.pages.built(1).mark_dirty()
        if self.pages.built(PAGE_SETTINGS) is not None:
            self.pages.built(PAGE_SETTINGS).raids.refresh_list()

    # --------------------------------------------------------------- Anti-AFK
    def open_search(self) -> None:
        """Ctrl+F from every page: open the settings and jump into the search field."""
        self.nav.button(PAGE_SETTINGS).click()
        search = self.pages[PAGE_SETTINGS].search
        search.setFocus()
        search.selectAll()

    def open_settings_tab(self, key: str) -> None:
        """Open the settings on a tab (e.g. “Macro” from the farm routine's hint)."""
        self.nav.button(PAGE_SETTINGS).click()
        page = self.pages[PAGE_SETTINGS]
        for btn in page.tab_group.buttons():
            if btn.property("group") == key:
                btn.click()
                break

    def set_anti_afk(self, on: bool) -> None:
        """Switch at the top / in the tray menu: effective and saved right away."""
        if self.engine.settings.anti_afk_enabled == on:
            return
        self.engine.settings.anti_afk_enabled = on
        try:
            self.engine.settings.save()
        except OSError:
            pass
        if self.afk_switch.isChecked() != on:
            self.afk_switch.setChecked(on)
        self.show_toast(tr("Anti-AFK on – every {minutes} min briefly to Roblox, Esc 4× and back.",
                           minutes=self.engine.settings.anti_afk_minutes) if on else tr("Anti-AFK off"))
        self._update_afk_info()

    def _update_afk_info(self) -> None:
        left = self.engine.anti_afk.seconds_left()
        text = "" if left is None else f"{int(left) // 60}:{int(left) % 60:02d}"    # only the time (above the switch)
        if self.afk_info.text() != text:
            self.afk_info.setText(text)
        text = self.engine.rejoin.info()
        if self.rejoin_info.text() != text:
            self.rejoin_info.setText(text)

    # --------------------------------------------------------------- Auto-Rejoin
    def set_auto_rejoin(self, on: bool) -> None:
        """Switch at the top / in the tray menu: effective and saved right away."""
        s = self.engine.settings
        if s.auto_rejoin_enabled == on:
            return
        s.auto_rejoin_enabled = on
        try:
            s.save()
        except OSError:
            pass
        if self.rejoin_switch.isChecked() != on:
            self.rejoin_switch.setChecked(on)
        if not on:
            self.show_toast(tr("Auto-rejoin off"))
        elif roblox_join.deep_link(s.private_server_link):
            self.show_toast(tr("Auto-rejoin on – after a disconnect, kick or crash you go back to your private "
                               "server."))
        else:
            self.show_toast(tr("Auto-rejoin on – without a private server link you go to a public server (link "
                               "under Settings → Private server)."))

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        """Really quit (from the tray menu)."""
        self._quitting = True
        self.show_from_tray() if self.engine.running else None     # the question needs a visible window
        self.close()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_timer.start()

    def _apply_scale(self) -> None:
        """Fonts, spacing and fixed sizes: UI size (50–200 %) × optionally fitting to the window size."""
        if self.isMinimized():
            return
        s = self.engine.settings
        if theme.set_scale(QApplication.instance(),
                           theme.factor_for(self.width(), self.height(), s.ui_zoom, s.ui_auto_fit)):
            self._status_key = None                 # redraw the status field
            self._apply_design()                    # logo/icons at the new size

    # --------------------------------------------------------------- Appearance
    def _go(self, index: int) -> None:
        """Page switch; in the design “Astral” with a short cross-fade (afterwards without effect – costs performance
        otherwise)."""
        self.pages[index]                                  # build when first opened
        self.stack.setCurrentIndex(index)
        self.gear.setChecked(index == PAGE_SETTINGS)
        self.new_dots.seen(f"nav:{index}")
        if not theme.animations():
            return
        widget = self.stack.currentWidget()
        if self._fade is not None:
            self._fade.stop()
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(120)                         # short = snappy, but still smooth
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda w=widget: w.setGraphicsEffect(None))
        self._fade = anim
        anim.start()

    def _apply_design(self) -> None:
        """Parts the stylesheet doesn't cover: icons, gear, title bar, colors of drawn content."""
        info = theme.design_info()
        if hasattr(self, "backdrop"):
            self.backdrop.refresh_decor()
            if info.get("decor") == "halloween":
                from .seasonal import pumpkin_pixmap
                self.season_mark.setPixmap(pumpkin_pixmap(theme.px(40)))
            self.season_mark.setVisible(info.get("decor") == "halloween")
        for i, key in enumerate(self._nav_icons):
            self.nav.button(i).setIcon(theme.glyph_icon(key) if info["icons"] else QIcon())
        self.nav.button(PAGE_SETTINGS).setVisible(not info["gear"])
        self.gear.setVisible(info["gear"])
        self.gear.setIcon(theme.glyph_icon("settings", 22))
        self.notes_btn.setIcon(theme.glyph_icon("notes", 22))
        self.notes_btn.setVisible(self.engine.settings.update_beta)
        self.gear.setChecked(self.stack.currentIndex() == 5)
        rail = bool(info.get("rail"))
        for i, name in enumerate(self._nav_names):    # slim bar: icons only, name as tooltip
            self.nav.button(i).setText("" if rail else name)
            self.nav.button(i).setToolTip(name if rail else "")
        self.sidebar.setFixedWidth(theme.px(76 if rail else 208))
        self.status_box.setVisible(not rail)
        self.toast.setVisible(not rail)
        self.pill.setVisible(rail)
        self.top_toast.setVisible(rail)
        self.rail_logo.setVisible(rail)
        self.brandmark.setVisible(info["icons"] and not rail)
        self.brand.setVisible(False)                 # header: start/pause/status on the left (since 0.9.5-beta.4)
        logo = app_paths.resource_path("assets/app.png")
        if info["icons"] and logo.is_file():
            self.brandmark.setPixmap(QIcon(str(logo)).pixmap(QSize(theme.px(22), theme.px(22))))
            self.rail_logo.setPixmap(QIcon(str(logo)).pixmap(QSize(theme.px(38), theme.px(38))))
        self.pages[0].recolor()
        if self.pages.built(PAGE_SETTINGS) is not None:
            self.pages.built(PAGE_SETTINGS).events.recolor()
        for page in self.pages:
            page.update()
        self._status_key = None
        winapi.set_titlebar(int(self.winId()), theme.is_dark(), theme.color("topbar"))

    def set_appearance(self, design: Optional[str] = None, mode: Optional[str] = None,
                       zoom: Optional[int] = None, fit: Optional[bool] = None,
                       reduce_motion: Optional[bool] = None, accent: Optional[str] = None,
                       intro: Optional[bool] = None, background: Optional[str] = None,
                       background_dim: Optional[int] = None, seasonal: Optional[bool] = None,
                       spooky: Optional[bool] = None) -> None:
        """Design, color scheme and UI size – visible and saved right away (without the save bar)."""
        s = self.engine.settings
        if design is not None:
            s.ui_design = design
        if mode is not None:
            s.ui_mode = mode
        if zoom is not None:
            s.ui_zoom = min(theme.ZOOM_MAX, max(theme.ZOOM_MIN, int(zoom)))
        if fit is not None:
            s.ui_auto_fit = fit
        if background is not None or background_dim is not None:
            if background is not None:
                s.ui_background = background
            if background_dim is not None:
                s.ui_background_dim = int(background_dim)
            self.backdrop.set_image(s.ui_background, s.ui_background_dim)
        if intro is not None:
            s.ui_intro = intro
        if seasonal is not None:
            s.ui_seasonal = seasonal
        if spooky is not None:
            s.ui_spooky = spooky
        if accent is not None:
            s.ui_accent = accent
            theme.set_accent(accent)
            theme._mode = ""                          # forces the palette to be recalculated
        if reduce_motion is not None:
            s.ui_reduce_motion = reduce_motion
            theme.set_motion(not reduce_motion)
            self.backdrop.refresh_decor()
        try:
            s.save()
        except OSError:
            pass
        theme.set_appearance(QApplication.instance(), theme.effective_design(s.ui_design, s.ui_seasonal),
                             s.ui_mode)
        self._apply_scale()

    def _follow_system(self) -> None:
        s = self.engine.settings
        if s.ui_mode == "system":
            theme._mode = ""                          # forces the palette to be recalculated
            theme.set_appearance(QApplication.instance(), theme.effective_design(s.ui_design, s.ui_seasonal),
                                 s.ui_mode)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_scale()
        winapi.set_titlebar(int(self.winId()), theme.is_dark(), theme.color("topbar"))
        if not self._intro_done:                      # logo animation only on the first show
            self._intro_done = True
            if self.engine.settings.ui_intro and theme.animations():
                from .intro import IntroOverlay
                IntroOverlay(self).start()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.backdrop._sync_timer()                 # seasonal decoration: no motion while minimized
            if self.isMinimized():
                QTimer.singleShot(1000, winapi.trim_memory)

    # --------------------------------------------------------------- Settings
    def collect_settings(self) -> Optional[Settings]:
        s = copy.deepcopy(self.engine.settings)
        try:
            for page in self.pages:
                page.apply(s)
        except ValueError as exc:
            QMessageBox.warning(self, tr("Invalid input"), str(exc))
            return None
        return s

    def apply_form(self) -> Optional[Settings]:
        """Apply the form values right away (without saving), e.g. for tests."""
        s = self.collect_settings()
        if s is not None:
            self.engine.apply_settings(s)
        return s

    def save_settings(self, show_message: bool = True) -> bool:
        s = self.collect_settings()
        if s is None:
            return False
        error = s.validate_detection()
        if error:
            QMessageBox.warning(self, tr("Settings"), error)
            return False
        self.engine.apply_settings(s)
        try:
            s.save()
        except OSError as exc:
            QMessageBox.critical(self, tr("Save"), tr("Could not save: {error}", error=exc))
            return False
        self._setup_hotkeys()
        self.bot.apply_settings()                         # bot on/off or reconnect with a new token
        self.notes_btn.setVisible(s.update_beta)
        if show_message:
            self.show_toast(tr("Saved ✓"))
        if s.language != i18n.language() and show_message:
            answer = QMessageBox.question(self, tr("Sprache / Language"),
                                          tr("The language changes after restarting the program. Restart now?"))
            if answer == QMessageBox.StandardButton.Yes:
                self.restart_app()
        return True

    def restart_app(self, safe: bool = False) -> None:
        """Restart the program (e.g. after a language change); the new instance waits until this one has ended.
        safe=True: safe mode (default settings), otherwise normal."""
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        args = [a for a in args if a not in ("--restart", "--safe")] + ["--restart"] + (["--safe"] if safe else [])
        QProcess.startDetached(sys.executable, args)
        self._quitting = True
        self.close()

    def _setup_hotkeys(self) -> None:
        s = self.engine.settings
        signature = (s.hotkey_toggle, s.hotkey_pause, s.hotkey_status)
        if signature == self._hotkey_sig:
            return
        self._hotkey_sig = signature
        if self._hotkeys is not None:
            self._hotkeys.stop()
        listener = HotkeyListener({
            tr("Start/stop"): (s.hotkey_toggle, lambda: self.post(self.toggle_monitoring)),
            tr("Pause"): (s.hotkey_pause, lambda: self.post(self.toggle_pause)),
            tr("Resend status"): (s.hotkey_status, lambda: self.post(self.resend_status)),
        })
        listener.start()
        listener.ready.wait(2.0)
        self._hotkeys = listener
        if listener.failed:
            self._hotkey_status = (tr("Not registered: {keys}", keys="; ".join(listener.failed)), False)
        else:
            self._hotkey_status = (tr("Active: {toggle} (start/stop), {pause} (pause), {status} (resend status)",
                                      toggle=s.hotkey_toggle, pause=s.hotkey_pause, status=s.hotkey_status), True)
        if self.pages.built(PAGE_SETTINGS) is not None:                # otherwise when building the page
            self.pages.built(PAGE_SETTINGS).set_hotkey_status(*self._hotkey_status)

    # --------------------------------------------------------------- Transfer settings
    def export_settings(self) -> None:
        """All settings as a password-protected file (for a new PC)."""
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from .. import secure
        from .transfer_dialog import PasswordDialog
        if not self.save_settings(show_message=False):   # take over the current input first
            return
        dlg = PasswordDialog(self, export=True)
        if not dlg.exec():
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Export settings"),
                                              str(Path.home() / f"Anime-Astral-Einstellungen{secure.EXPORT_SUFFIX}"),
                                              tr("Settings file") + f" (*{secure.EXPORT_SUFFIX})")
        if not path:
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            target = secure.export_settings(self.engine.settings.to_dict(), dlg.value(), Path(path))
        except (secure.SecureError, OSError) as exc:
            QMessageBox.warning(self, tr("Export settings"), str(exc))
            return
        finally:
            self.unsetCursor()
        self.show_toast(tr("Exported: {name} ✓", name=target.name))

    def import_settings(self) -> None:
        """Read a password-protected file, replace the settings and restart the program."""
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from .. import secure
        from .transfer_dialog import PasswordDialog
        path, _ = QFileDialog.getOpenFileName(self, tr("Import settings"), str(Path.home()),
                                              tr("Settings file") + f" (*{secure.EXPORT_SUFFIX})")
        if not path:
            return
        while True:
            dlg = PasswordDialog(self, export=False)
            if not dlg.exec():
                return
            self.setCursor(Qt.CursorShape.WaitCursor)
            try:
                data = secure.import_settings(Path(path), dlg.value())
                break
            except secure.SecureError as exc:
                QMessageBox.warning(self, tr("Import settings"), str(exc))
            finally:
                self.unsetCursor()
        if self.engine.running:
            self.engine.stop()
        settings = Settings.from_dict(data)
        try:
            settings.save()
        except OSError as exc:
            QMessageBox.critical(self, tr("Save"), tr("Could not save: {error}", error=exc))
            return
        QMessageBox.information(self, tr("Import settings"),
                                tr("Settings applied. The program restarts now."))
        self.restart_app()

    def create_diagnostics(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from pathlib import Path
        from ..diagnostics import build_report
        self.apply_form()
        desktop = Path.home() / "Desktop"
        dest = desktop if desktop.is_dir() else app_paths.data_dir()
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            path = build_report(self.engine, dest)
        except Exception as exc:
            QMessageBox.critical(self, tr("Diagnostics"), tr("The package could not be created:\n{error}", error=exc))
            return
        finally:
            self.unsetCursor()
        QMessageBox.information(self, tr("Diagnostics package created"),
                                tr("Saved:\n{path}\n\nThe file contains the log, value history, settings (without "
                                   "webhook) and a screenshot of the Roblox window.", path=path))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def explain_safe_mode(self) -> None:
        box = QMessageBox(QMessageBox.Icon.Information, tr("Safe mode"), tr(
            "The program is running with default settings. Your own settings are unchanged and return on the next "
            "normal start – changes made in this mode are not saved.\n\nStatistics and raids are kept as usual."), parent=self)
        normal = box.addButton(tr("Restart normally"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Stay in safe start"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is normal:
            self.restart_app()

    def show_toast(self, text: str) -> None:
        for lbl in (self.toast, self.top_toast):
            lbl.setText(text)
        QTimer.singleShot(3000, lambda: [lbl.setText("") for lbl in (self.toast, self.top_toast)])

    @staticmethod
    def _stacked(info, switch) -> QVBoxLayout:
        """Short extra info (e.g. Anti-AFK countdown) small above the switch instead of beside it – saves width."""
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        info.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(info, 0, Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(switch, 0, Qt.AlignmentFlag.AlignHCenter)
        return box

    def _mount_controls(self) -> None:
        """Start/stop, pause and “Resend status” as buttons at the top left of the header (owner's wish
        07.10.2026). The buttons belong to the start page, which keeps their state in refresh()."""
        page = self.pages[PAGE_MONITOR]
        for i, btn in enumerate((page.btn_start, page.btn_pause, page.btn_status), start=1):
            self._top.insertWidget(i, btn)
        self.brand.setVisible(False)                      # the name is in the window title, the logo in the sidebar

    def post(self, call: Callable[[], None]) -> None:
        """From background threads: have a call run in the GUI thread."""
        self._ui_calls.put(call)

    # --------------------------------------------------------------- Control
    def toggle_monitoring(self) -> None:
        if self.engine.running:
            self.auto.user_stopped()                # stopped yourself: auto-start waits until the next time you enter
            self.setCursor(Qt.CursorShape.WaitCursor)
            try:
                self.engine.stop()
            finally:
                self.unsetCursor()
            return
        if not self.save_settings(show_message=False):
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self.engine.start()
        except EngineError as exc:
            QMessageBox.critical(self, tr("Cannot start"), str(exc))
        finally:
            self.unsetCursor()

    def toggle_pause(self) -> None:
        self.auto.user_paused()
        self.engine.toggle_pause()

    # --------------------------------------------------------------- Auto-Start
    def set_auto_monitor(self, on: bool) -> None:
        """Switch at the top / in the tray menu: effective and saved right away."""
        s = self.engine.settings
        if s.auto_monitor == on:
            return
        s.auto_monitor = on
        try:
            s.save()
        except OSError:
            pass
        if self.auto_switch.isChecked() != on:
            self.auto_switch.setChecked(on)
        self.auto.reset()
        self.show_toast(tr("Auto-start on – monitoring starts as soon as you enter Anime Astral.") if on
                        else tr("Auto-start off"))

    def _auto_tick(self) -> None:
        """Also runs in the background (tray), carries out AutoMonitor's decisions."""
        s, engine = self.engine.settings, self.engine
        if not s.auto_monitor:
            if self.auto_info.text():
                self.auto_info.setText("")
            return
        rj = engine.rejoin
        phase = phase_of(rj.status, rj.place)
        now = time.monotonic()
        for act in self.auto.tick(now, phase, engine.running, engine.state.paused, s.auto_rejoin_enabled,
                                  rj.status == "gave_up"):
            if act == "start":
                try:
                    engine.start()
                    self._auto_error = ""
                    engine._event(tr("Auto-start: entered Anime Astral – monitoring started"), "info")
                except EngineError as exc:
                    self.auto.start_failed(now)
                    if str(exc) != self._auto_error:      # report the same reason only once
                        self._auto_error = str(exc)
                        engine._event(tr("Auto-start: not possible yet ({error}) – retrying in 30 s",
                                         error=exc), "warn")
            elif act == "pause" and not engine.state.paused:
                engine.toggle_pause()
                engine._event(tr("Auto-start: connection lost – monitoring paused"), "warn")
            elif act == "resume" and engine.state.paused:
                engine.toggle_pause()
                engine._event(tr("Auto-start: back in the game – monitoring continues"), "ok")
            elif act == "stop" and engine.running:
                engine.stop()
                engine._event(tr("Auto-start: left the game – monitoring stopped"), "info")
        text = self.auto.info(now, phase, engine.running)
        if self.auto_info.text() != text:
            self.auto_info.setText(text)

    # --------------------------------------------------------------- Discord / status / wizard
    def resend_status(self) -> None:
        s = self.engine.settings
        if not s.status_enabled or not is_valid_webhook(s.webhook_url):
            QMessageBox.information(self, tr("Live status"), tr("The live status message is not active. Enter a "
                                                                "webhook and enable it under “Alerts”."))
            return
        self.engine.resend_status()
        self.show_toast(tr("Resending status …"))

    def test_webhook(self, url: str, done: Callable[[bool, str], None]) -> None:
        """Sends a test message in the background; `done(ok, info)` runs afterwards in the GUI thread."""
        tmp = copy.deepcopy(self.engine.settings)
        tmp.webhook_url = url
        payload, _files = messages.build_message(tmp, "start_stop", tr("🔔 Test message"), messages.COLOR_INFO,
                                                 [(tr("Status"), tr("Connection to the webhook works."), False)])

        def work() -> None:
            ok, info = DiscordSender(lambda: tmp).send_now(payload)
            self.post(lambda: done(ok, info))

        threading.Thread(target=work, daemon=True).start()

    def set_webhook(self, url: str) -> None:
        self.pages[2].url.setText(url)
        self.save_settings(show_message=False)

    # --------------------------------------------------------------- Updates
    def check_updates(self, manual: bool = False) -> None:
        s = self.engine.settings
        repo = updater.current_repo()
        if not repo:
            if manual:
                QMessageBox.information(self, tr("Updates"), tr("This version has no update source. Automatic "
                                                                "updates are only available in the installed "
                                                                "version (download via GitHub)."))
            return
        if not manual and (not s.update_check or not updater.due(s.update_last_check)):
            return

        def work() -> None:
            try:
                info, error = updater.check_latest(repo, beta=s.update_beta), None
            except updater.UpdateError as exc:
                info, error = None, str(exc)
            self.post(lambda: self._update_result(info, error, manual))

        threading.Thread(target=work, daemon=True).start()

    def _update_result(self, info, error: Optional[str], manual: bool) -> None:
        if error:
            if manual:
                QMessageBox.warning(self, tr("Updates"), tr("Checking for updates failed:\n{error}",
                                                            error=error))
            return
        self.engine.settings.update_last_check = time.time()
        try:
            self.engine.settings.save()
        except OSError:
            pass
        if info is None or not updater.is_newer(info.version):
            if manual:
                QMessageBox.information(self, tr("Updates"), tr("You have the latest version ({version}).",
                                                                version=__version__))
            return
        if not manual and info.version == self.engine.settings.update_skip:
            return
        if not updater.is_installed_build():
            if manual:
                QMessageBox.information(self, tr("Updates"), tr("Version {version} is available:\n{url}\n\nOnly the "
                                                                "installed version updates itself.",
                                                                version=info.version, url=info.page_url))
            return
        from .update_dialog import UpdateDialog
        UpdateDialog(self, info).exec()

    def skip_version(self, version: str) -> None:
        self.engine.settings.update_skip = version
        try:
            self.engine.settings.save()
        except OSError:
            pass

    def quit_for_update(self) -> None:
        """Ends the program cleanly so the installer can replace the files."""
        self._force_close = True
        self.close()

    def open_wizard(self) -> None:
        from .wizard import SetupWizard
        SetupWizard(self).exec()

    def finish_wizard(self, start: bool) -> None:
        self.engine.settings.wizard_done = True
        self.engine.settings.seen_version = __version__        # new install: no “What's new”
        self.new_dots.mark_all_seen()                             # … and no “New” dots
        self.save_settings(show_message=False)
        if start:
            self.toggle_monitoring()

    # --------------------------------------------------------------- Tick
    def _tray_tick(self) -> None:
        """About every second: update the icon tooltip, fulfill a second instance's request to show the window."""
        self._tray_count = getattr(self, "_tray_count", 0) + 1
        if self._tray_count % 3:
            return
        request = show_request_file()
        if request.exists():
            try:
                request.unlink()
            except OSError:
                pass
            self.show_from_tray()
        if self.isVisible() and not self.isMinimized():
            self._update_afk_info()
        if self.tray is not None:
            st = self.engine.state
            if not st.running:
                state = tr("Stopped")
            elif st.paused:
                state = tr("Paused")
            elif st.wave_value is not None:
                state = tr("Wave {wave}", wave=messages.fmt_wave(st.wave_value, st.wave_total))
            else:
                state = tr("Running")
            text = f"Anime Astral Monitor – {state}" + (f" · {st.profile}" if st.profile else "")
            if text != self.tray.toolTip():
                self.tray.setToolTip(text)

    def _tick(self) -> None:
        refresh_stats = False
        for _ in range(200):
            try:
                kind, data = self.engine.events.get_nowait()
            except queue.Empty:
                break
            if kind == "event":
                refresh_stats = True               # reload the statistics on the next display (only a flag)
        for _ in range(20):
            try:
                self._ui_calls.get_nowait()()
            except queue.Empty:
                break
        if refresh_stats and self.pages.built(1) is not None:
            self.pages.built(1).mark_dirty()
        self._tray_tick()
        self._auto_tick()
        if self.isMinimized() or not self.isVisible():
            self._status_key = None                 # redraw everything after restoring
            return                                  # minimized: draw nothing (saves CPU)

        st = self.engine.state
        key = "paused" if (st.running and st.paused) else ("on" if st.running else "off")
        if st.running:
            elapsed = time.monotonic() - (st.started_at or time.monotonic())
            self.status_sub.setText(tr("Running {time}", time=messages.fmt_duration(elapsed)))
        elif key != self._status_key:
            self.status_sub.setText("")
        title = {"paused": tr("Paused"), "on": tr("Running"), "off": tr("Stopped")}[key]
        if self.pill.isVisible():                  # Nebula: status + running time in the pill
            pill = "● " + title + (f"  ·  {messages.fmt_duration(elapsed)}" if st.running else "")
            if self.pill_text.text() != pill:
                self.pill_text.setText(pill)
        if key != self._status_key:               # recompute the style only on change (saves CPU)
            self._status_key = key
            self.status_title.setText("● " + title)
            self.status_title.setObjectName({"paused": "warn", "on": "good", "off": "muted"}[key])
            self.pill_text.setObjectName(self.status_title.objectName())
            self.status_box.setProperty("state", "off" if key == "off" else "on")
            self.pill.setProperty("state", key)
            for widget in (self.status_title, self.status_box, self.pill_text, self.pill):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

        self.pages[0].refresh_controls()            # keep the header buttons current on every page
        self.pages[self.stack.currentIndex()].refresh()

    def closeEvent(self, event) -> None:
        if (self.tray is not None and self.engine.settings.close_to_tray
                and not self._quitting and not self._force_close):
            event.ignore()                          # keep running in the tray
            self.hide()
            QTimer.singleShot(1000, winapi.trim_memory)
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(tr("Anime Astral Monitor"),
                                      tr("Keeps running in the background. Right-click the icon next to the clock → "
                                         "“Quit” closes the program."),
                                      QSystemTrayIcon.MessageIcon.Information, 6000)
            return
        if self.engine.running and not self._force_close:
            answer = QMessageBox.question(self, tr("Quit"), tr("Monitoring is still running. Really quit?"))
            if answer != QMessageBox.StandardButton.Yes:
                self._quitting = False
                event.ignore()
                return
        for page in self.pages:
            if hasattr(page, "save_ui"):
                page.save_ui()
        if self._hotkeys is not None:
            self._hotkeys.stop()
        self.bot.stop()
        self.engine.shutdown()
        if self.tray is not None:
            self.tray.hide()
        event.accept()
        QApplication.quit()                         # the program ends (otherwise it keeps running with a hidden window)


def show_request_file():
    """File with which a second started instance asks the running program to show its window."""
    return app_paths.data_dir() / "show.request"


def _install_qt_translation(app: QApplication, lang: str) -> None:
    """Qt's own texts (Yes/No, Cancel …) in the chosen language; English is Qt's default."""
    if lang != "de":
        return
    translator = QTranslator(app)
    if translator.load("qtbase_de", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
        app._qt_translator = translator             # keep a reference


def _install_crash_logging() -> None:
    """Write unhandled errors to the log (in the EXE's windowed mode there would otherwise be no trace)."""
    log = logging.getLogger("crash")

    def handle(exc_type, exc, tb) -> None:
        log.critical("Unbehandelte Ausnahme", exc_info=(exc_type, exc, tb))
        try:
            QMessageBox.critical(None, tr("Unexpected error"),
                                 f"{exc_type.__name__}: {exc}\n\n"
                                 + tr("Details are in monitor.log ({path}).", path=app_paths.log_file()))
        except Exception:
            pass

    sys.excepthook = handle
    threading.excepthook = lambda args: log.critical(
        "Ausnahme im Thread %s", getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def run() -> int:
    if sys.platform == "win32":
        try:    # own taskbar icon instead of “python.exe”
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AnimeAstralMonitor")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Anime Astral Monitor")
    app.setQuitOnLastWindowClosed(False)            # window closed = keep running in the tray
    icon = app_paths.resource_path("assets/app.ico")
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    safe = "--safe" in sys.argv or bool(
        QApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)    # hold Shift at start-up
    try:
        settings = Settings.safe_defaults() if safe else Settings.load()
    except Exception:
        settings = Settings()
    if safe:
        try:
            settings.language = Settings.load().language    # the language may stay
        except Exception:
            pass
    i18n.set_language(settings.language)            # before building the UI
    _install_qt_translation(app, settings.language)
    theme.set_accent(settings.ui_accent)
    theme.apply(app, theme.effective_design(settings.ui_design, settings.ui_seasonal), settings.ui_mode)
    theme.set_motion(not settings.ui_reduce_motion)

    lock = QLockFile(str(app_paths.data_dir() / "app.lock"))       # only one instance at a time
    if not lock.tryLock(10_000 if "--restart" in sys.argv else 300):   # on restart: wait for the old instance
        # already running (maybe invisible in the tray): let it show its window
        try:
            show_request_file().write_text("1", encoding="utf-8")
        except OSError:
            QMessageBox.information(None, tr("Already open"), tr("Anime Astral Monitor is already running."))
        return 0
    try:
        engine = Engine(settings)
        if settings.low_priority:                       # the game comes first – also for the macro and the UI,
            Engine._lower_priority()                    # not only once monitoring runs (weak PCs)
    except Exception as exc:
        QMessageBox.critical(None, tr("Start failed"), f"{type(exc).__name__}: {exc}")
        return 1
    _install_crash_logging()
    window = MainWindow(engine)
    window.show()
    if safe:
        window.setWindowTitle(window.windowTitle() + " – " + tr("Safe mode"))
        QTimer.singleShot(300, window.explain_safe_mode)
    code = app.exec()
    lock.unlock()
    return code
