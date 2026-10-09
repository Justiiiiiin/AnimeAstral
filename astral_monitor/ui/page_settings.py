"""Page “Settings”: Roblox helpers, monitoring, program."""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget)

from .. import app_paths, roblox_join, storage
from ..i18n import LANGUAGES, dec, tr
from ..settings import MAX_FAVORITES, PRESETS
from ..version import __version__
from . import theme
from .server_dialog import ServerDialog
from .widgets import (Card, ComboBox, DoubleSpinBox, InfoButton, SpinBox, columns, form_grid, label, section,
                      short_field, smooth)



def bug_report_url(repo: str) -> str:
    """New GitHub issue, pre-filled with version and system – without personal data (no IDs, links, paths)."""
    body = "\n\n\n".join([f"**{tr("What happened?")}**", f"**{tr("What did you expect?")}**",
                          f"---\nVersion {__version__} · {platform.system()} {platform.release()} "
                          f"({platform.version()})"])
    return f"https://github.com/{repo}/issues/new?" + urlencode({"title": "", "body": body})


class SettingsPage(QWidget):
    SAVES = True                                   # save bar at the bottom (main_window)

    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 14)
        self.search = short_field(QLineEdit(), 300)
        self.search.setPlaceholderText(tr("Search settings …"))
        self.search.setToolTip(tr("Searches all tabs – including the ⓘ explanations. From anywhere: Ctrl+F"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        tabs = QHBoxLayout()
        theme.track_spacing(tabs, 4)
        tabs.addWidget(label(tr("Settings"), "h1"))
        tabs.addSpacing(theme.px(14))
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for key in ("Roblox", "Macro", "Discord bot", "Monitoring", "Appearance", "Program", "Debug"):
            btn = QPushButton(tr(key))
            btn.setObjectName("tab")
            btn.setCheckable(True)
            btn.setProperty("group", key)
            self.tab_group.addButton(btn)
            tabs.addWidget(btn)
        tabs.addStretch(1)
        tabs.addWidget(self.search)
        self.tab_group.buttonClicked.connect(lambda b: (self._show_group(b.property("group")),
                                                        self.main.new_dots.seen(f"tab:{b.property('group')}")))
        root.addLayout(tabs)
        self.no_match = label(tr("No setting found."), "muted")
        self.no_match.setVisible(False)
        root.addWidget(self.no_match)

        def stack(*cards) -> QWidget:
            """Several cards one below the other as one column (for columns)."""
            col = QWidget()
            lay = QVBoxLayout(col)
            lay.setContentsMargins(0, 0, 0, 0)
            theme.track_spacing(lay, 14)
            for card in cards:
                lay.addWidget(card)
            return col

        # ------------------------------------------------------------------ Roblox
        root.addWidget(section(tr("Roblox")))
        ps = Card(tr("Private server and auto-rejoin"),
                  tr("The marked server is used for “Join server” (header, tray) and for auto-rejoin. Roblox starts "
                     "without a browser; share links and classic links work. The links are stored encrypted on this "
                     "PC only.\n\nAuto-rejoin (switch in the header): after a disconnect, kick or crash the program "
                     "rejoins after 15 s – up to 5 attempts. If you close Roblox yourself, it does not bring you "
                     "back."))
        self.servers = QListWidget()
        smooth(self.servers)
        theme.track_fixed_height(self.servers, 132)
        self.servers.currentRowChanged.connect(self._server_selected)
        self.servers.itemDoubleClicked.connect(lambda _i: self._join_selected())
        self.servers.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.servers.customContextMenuRequested.connect(self._server_menu)
        ps.body.addWidget(self.servers)
        prow = QHBoxLayout()
        add = QPushButton(tr("New …"))
        add.clicked.connect(self._add_server)
        edit = QPushButton(tr("Edit …"))
        edit.clicked.connect(self._edit_server)
        delete = QPushButton(tr("Delete"))
        delete.clicked.connect(self._delete_server)
        join = QPushButton(tr("Join"))
        join.setObjectName("primary")
        join.clicked.connect(self._join_selected)
        for btn in (add, edit, delete):
            prow.addWidget(btn)
        prow.addStretch(1)
        prow.addWidget(join)
        ps.body.addLayout(prow)
        ps.body.addStretch(1)

        afk = Card(tr("Anti-AFK"),
                   tr("Turn it on in the header. Every few minutes briefly brings each Roblox window to the front "
                      "(minimized ones are restored and stay open so recognition keeps working), presses Esc 4 "
                      "times – the Roblox menu opens and closes again – and switches right back. Afterwards "
                      "Roblox's memory is trimmed.\n\nNote: macros are not allowed by the Roblox rules – use at "
                      "your own risk."))
        ag = form_grid()
        self.afk_minutes = SpinBox()
        self.afk_minutes.setRange(1, 19)
        self.afk_minutes.setSuffix(tr(" min"))
        ag.addWidget(label(tr("Run every")), 0, 0)
        ag.addWidget(self.afk_minutes, 0, 1)
        afk.body.addLayout(ag)
        afk.body.addStretch(1)

        prof = Card(tr("Your Roblox profile"),
                    tr("Just your Roblox name – display name and avatar come from Roblox's public site, no login. "
                       "The avatar appears in the sidebar and on the statistics cards. Leave empty = no profile."))
        frow = QHBoxLayout()
        theme.track_spacing(frow, 10)
        self.avatar_preview = QLabel()
        theme.track(self.avatar_preview, lambda o, f: o.setFixedSize(round(48 * f), round(48 * f)))
        frow.addWidget(self.avatar_preview)
        self.roblox_name = short_field(QLineEdit(), 200)
        self.roblox_name.setPlaceholderText(tr("Roblox name"))
        self.roblox_name.returnPressed.connect(self._apply_profile)
        frow.addWidget(self.roblox_name)
        apply_btn = QPushButton(tr("Apply"))
        apply_btn.clicked.connect(self._apply_profile)
        frow.addWidget(apply_btn)
        frow.addStretch(1)
        prof.body.addLayout(frow)
        self.profile_state = label("", "small", wrap=True)
        prof.body.addWidget(self.profile_state)
        prof.body.addStretch(1)
        from .raids_card import RaidsCard
        self.raids = RaidsCard(main)
        left, right = QWidget(), QWidget()
        for col, cards in ((left, (ps, self.raids)), (right, (afk, prof))):
            lay = QVBoxLayout(col)
            lay.setContentsMargins(0, 0, 0, 0)
            theme.track_spacing(lay, 14)
            for card in cards:
                lay.addWidget(card)
        root.addLayout(columns(left, right))

        keys = Card(tr("Hotkeys"),
                    tr("Work globally, also in-game. Format: Ctrl+Alt+S, Shift+F9 … (Ctrl, Alt, Shift, Win). Avoid "
                       "single F keys that Roblox uses itself."))
        kg = form_grid()
        self.hk_toggle = short_field(QLineEdit())
        self.hk_pause = short_field(QLineEdit())
        self.hk_status_edit = short_field(QLineEdit())
        kg.addWidget(label(tr("Start / stop")), 0, 0)
        kg.addWidget(self.hk_toggle, 0, 1)
        kg.addWidget(label(tr("Pause / resume")), 1, 0)
        kg.addWidget(self.hk_pause, 1, 1)
        kg.addWidget(label(tr("Resend status")), 2, 0)
        kg.addWidget(self.hk_status_edit, 2, 1)
        keys.body.addLayout(kg)
        self.hk_status = label("", "small", wrap=True)
        keys.body.addWidget(self.hk_status)
        keys.body.addStretch(1)
        # ------------------------------------------------------------------ Monitoring
        root.addWidget(section(tr("Monitoring")))
        perf = Card(tr("Performance"),
                    tr("How often the wave counter is read. “Balanced” (every 0.5 s) reliably detects the end of a "
                       "raid and suits almost everyone. Hover over the selection to see the exact times."))
        pg = form_grid()
        self.perf = ComboBox()
        for key, preset in PRESETS.items():
            self.perf.addItem(tr(preset["label"]), key)
        self.perf.currentIndexChanged.connect(self._show_preset)
        pg.addWidget(label(tr("Check rate")), 0, 0)
        pg.addWidget(self.perf, 0, 1)
        perf.body.addLayout(pg)
        self.low_priority = QCheckBox(tr("Low process priority (the game comes first)"))
        perf.body.addWidget(self.low_priority)
        perf.body.addStretch(1)

        guard = Card(tr("Guard"),
                     tr("Speaks up when Roblox crashes, the connection drops or you get kicked, the counter gets "
                        "stuck, no raid ends for a long time or Roblox uses too much memory. Choose under “Alerts” "
                        "what is sent to Discord."))
        self.guard_enabled = QCheckBox(tr("Guard active"))
        guard.body.addWidget(self.guard_enabled)
        gg = form_grid()
        self.stall = SpinBox()
        self.stall.setRange(1, 240)
        self.stall.setSuffix(tr(" min"))
        self.no_raid = SpinBox()
        self.no_raid.setRange(0, 1440)
        self.no_raid.setSuffix(tr(" min"))
        self.no_raid.setSpecialValueText(tr("off"))
        self.ram = DoubleSpinBox()
        self.ram.setRange(0, 64)
        self.ram.setSingleStep(0.5)
        self.ram.setDecimals(1)
        self.ram.setSuffix(tr(" GB"))
        self.ram.setSpecialValueText(tr("off"))
        gg.addWidget(label(tr("Stall after")), 0, 0)
        gg.addWidget(self.stall, 0, 1)
        gg.addWidget(label(tr("No raid finished for")), 1, 0)
        gg.addWidget(self.no_raid, 1, 1)
        gg.addWidget(label(tr("Roblox memory above")), 2, 0)
        gg.addWidget(self.ram, 2, 1)
        guard.body.addLayout(gg)
        guard.body.addStretch(1)
        root.addLayout(columns(stack(perf, keys), guard))

        # ------------------------------------------------------------------ Program
        ui = Card(tr("Interface"),
                  tr("A language change applies after a restart.\n\nIf you close the window, the program keeps "
                     "running in the tray (icon next to the clock). Right-click the icon: open, start/stop, pause, "
                     "join server, anti-AFK, auto-rejoin, auto-start, quit."))
        ug = form_grid()
        self.language = ComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        ug.addWidget(label(tr("Sprache / Language")), 0, 0)
        ug.addWidget(self.language, 0, 1)
        ui.body.addLayout(ug)
        self.close_to_tray = QCheckBox(tr("Keep running in the tray when closed"))
        ui.body.addWidget(self.close_to_tray)
        ui.body.addStretch(1)

        root.addWidget(section(tr("Appearance")))
        look = Card(tr("Look"),
                    tr("Changes apply immediately. Older designs stay selectable here, with the version that "
                       "introduced them.\n\nUI size: smaller = more visible per page. “Adapt to the window size” "
                       "additionally scales with the window."))
        lg = form_grid()
        self.design = ComboBox()
        for key, info in theme.DESIGNS.items():
            self.design.addItem(tr("{name} (since version {version})", name=tr(info["name"]), version=info["since"]),
                                key)
        self.design.activated.connect(lambda _i: self.main.set_appearance(design=self.design.currentData()))
        lg.addWidget(label(tr("Design")), 0, 0)
        lg.addWidget(self.design, 0, 1)
        mode_row = QHBoxLayout()
        theme.track_spacing(mode_row, 6)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for mode, text in (("dark", tr("Dark")), ("light", tr("Light")), ("system", tr("Like Windows"))):
            btn = QPushButton(text)
            btn.setObjectName("chipbtn")
            btn.setCheckable(True)
            btn.setProperty("mode", mode)
            self.mode_group.addButton(btn)
            mode_row.addWidget(btn)
        mode_row.addStretch(1)
        self.mode_group.buttonClicked.connect(lambda b: self.main.set_appearance(mode=b.property("mode")))
        lg.addWidget(label(tr("Color scheme")), 1, 0)
        lg.addLayout(mode_row, 1, 1, 1, 2)
        zoom_row = QHBoxLayout()
        theme.track_spacing(zoom_row, 6)
        self.zoom_buttons = []
        for pct in (50, 75, 100, 125, 150):
            btn = QPushButton(f"{pct} %")
            btn.setObjectName("chipbtn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _c, v=pct: self._set_zoom(v))
            self.zoom_buttons.append((pct, btn))
            zoom_row.addWidget(btn)
        self.zoom = SpinBox()
        self.zoom.setRange(theme.ZOOM_MIN, theme.ZOOM_MAX)
        self.zoom.setSuffix(" %")
        self.zoom.setSingleStep(5)
        self.zoom.setKeyboardTracking(False)              # apply only after Enter/leaving the field, not on every digit
        self.zoom.setToolTip(tr("Custom value from {min} to {max} %", min=theme.ZOOM_MIN, max=theme.ZOOM_MAX))
        self.zoom.valueChanged.connect(self._set_zoom)
        zoom_row.addWidget(self.zoom)
        zoom_row.addStretch(1)
        lg.addWidget(label(tr("UI size")), 2, 0)
        lg.addLayout(zoom_row, 2, 1, 1, 2)
        accent_row = QHBoxLayout()
        theme.track_spacing(accent_row, 6)
        self.accent_group = QButtonGroup(self)
        self.accent_group.setExclusive(True)
        auto = QPushButton(tr("Design"))
        auto.setObjectName("chipbtn")
        auto.setCheckable(True)
        auto.setProperty("accent", "")
        auto.setToolTip(tr("Color of the selected design"))
        self.accent_group.addButton(auto)
        accent_row.addWidget(auto)
        for hex_color in theme.ACCENTS:
            accent_row.addWidget(self._swatch(hex_color))
        self.accent_image = QPushButton(tr("From image"))
        self.accent_image.setObjectName("chipbtn")
        self.accent_image.setToolTip(tr("Use the strongest color from your background image"))
        self.accent_image.clicked.connect(self._accent_from_image)
        accent_row.addWidget(self.accent_image)
        self.accent_custom = QPushButton(tr("Custom …"))
        self.accent_custom.setObjectName("chipbtn")
        self.accent_custom.setCheckable(True)
        self.accent_custom.clicked.connect(self._pick_accent)
        accent_row.addWidget(self.accent_custom)
        accent_row.addStretch(1)
        self.accent_group.buttonClicked.connect(
            lambda b: b is not self.accent_custom and self.main.set_appearance(accent=b.property("accent")))
        self.accent_group.addButton(self.accent_custom)
        lg.addWidget(label(tr("Accent color")), 3, 0)
        lg.addLayout(accent_row, 3, 1, 1, 2)
        bg_row = QHBoxLayout()
        theme.track_spacing(bg_row, 6)
        pick_bg = QPushButton(tr("Choose image …"))
        pick_bg.clicked.connect(self._pick_background)
        self.bg_remove = QPushButton(tr("Remove"))
        self.bg_remove.clicked.connect(lambda: self.main.set_appearance(background="") or self._sync_look(
            self.main.engine.settings))
        self.bg_dim = SpinBox()
        self.bg_dim.setRange(0, 95)
        self.bg_dim.setSingleStep(5)
        self.bg_dim.setSuffix(" %")
        self.bg_dim.setPrefix(tr("Dim "))
        self.bg_dim.setKeyboardTracking(False)
        self.bg_dim.valueChanged.connect(lambda v: self.main.set_appearance(background_dim=v))
        for w in (pick_bg, self.bg_remove, self.bg_dim):
            bg_row.addWidget(w)
        bg_row.addStretch(1)
        lg.addWidget(label(tr("Background")), 4, 0)
        lg.addLayout(bg_row, 4, 1, 1, 2)
        look.body.addLayout(lg)
        self.auto_fit = QCheckBox(tr("Also adapt to the window size"))
        self.auto_fit.toggled.connect(lambda on: self.main.set_appearance(fit=on))
        look.body.addWidget(self.auto_fit)
        self.mode_hint = label("", "small", wrap=True)
        look.body.addWidget(self.mode_hint)
        look.body.addStretch(1)
        fx = Card(tr("Effects"))
        mrow = QHBoxLayout()
        self.reduce_motion = QCheckBox(tr("Reduce animations"))
        self.reduce_motion.toggled.connect(lambda on: self.main.set_appearance(reduce_motion=on))
        self.reduce_motion.toggled.connect(lambda on: self.intro.setEnabled(not on))
        mrow.addWidget(self.reduce_motion)
        mrow.addWidget(InfoButton(tr("Pages appear without fading and switches flip instantly. Saves a little "
                                     "performance, e.g. while Roblox is running.")))
        mrow.addStretch(1)
        fx.body.addLayout(mrow)
        srow = QHBoxLayout()
        self.seasonal = QCheckBox(tr("Seasonal designs automatically"))
        self.seasonal.toggled.connect(lambda on: (self.main.set_appearance(seasonal=on),
                                                  self._sync_look(self.main.engine.settings)))
        srow.addWidget(self.seasonal)
        srow.addWidget(InfoButton(tr(
            "Seasonal designs appear automatically at the right time: Cherry Blossom (Mar 20 – Apr 30), Summer (Jun "
            "21 – Aug 31), Pumpkin Night (Oct 15 – Nov 2), Frost (Dec 1 – Jan 6) and New Year's Eve (Dec 29 – Jan "
            "2) – afterwards your chosen design returns. All are also available any time under “Design” above.")))
        srow.addStretch(1)
        fx.body.addLayout(srow)
        krow = QHBoxLayout()
        self.spooky = QCheckBox(tr("Pumpkin Night surprise"))
        self.spooky.toggled.connect(lambda on: self.main.set_appearance(spooky=on))
        krow.addWidget(self.spooky)
        krow.addWidget(InfoButton(tr("Only in the “Pumpkin Night” design: now and then a creepy face briefly peeks "
                                     "up from the bottom edge of the window – at most once an hour, only while the "
                                     "window is open. Click it to make it vanish.")))
        krow.addStretch(1)
        fx.body.addLayout(krow)
        self.intro = QCheckBox(tr("Logo animation at startup"))
        self.intro.toggled.connect(lambda on: self.main.set_appearance(intro=on))
        fx.body.addWidget(self.intro)
        fx.body.addStretch(1)
        root.addLayout(columns(look, stack(fx, ui)))

        root.addWidget(section(tr("Program")))

        rpc = Card(tr("Discord profile status"),
                   tr("Shows raid and wave as “Playing …” in your Discord profile.\n\nApplication ID: "
                      "discord.com/developers/applications → New Application (its name appears in the profile) → "
                      "copy the Application ID. The Discord desktop app must be running and activity sharing must "
                      "be on (Discord → Settings → Activity Privacy)."))
        self.rpc_enabled = QCheckBox(tr("Show the current raid and progress in my Discord profile"))
        rpc.body.addWidget(self.rpc_enabled)
        self.rpc_state = label("", "muted", wrap=True)
        rpc.body.addWidget(self.rpc_state)
        rg = form_grid()
        rg.setColumnStretch(1, 1)
        rg.setColumnStretch(2, 0)
        self.rpc_id = QLineEdit()
        self.rpc_id.setPlaceholderText(tr("your own Application ID from the Discord developer portal"))
        self.rpc_link = QLineEdit()
        self.rpc_link.setPlaceholderText(tr("https://www.roblox.com/games/…"))
        rg.addWidget(label(tr("Application ID")), 0, 0)
        rg.addWidget(self.rpc_id, 0, 1)
        rg.addWidget(label(tr("Game link (for the image)")), 1, 0)
        rg.addWidget(self.rpc_link, 1, 1)
        rpc.body.addLayout(rg)

        upd = Card(tr("Updates"),
                   tr("New versions usually arrive as a small package (changed files only). Under “All versions” "
                      "you can read the changes of every version and go back to an older one if something breaks – "
                      "settings and statistics are kept."))
        upd.body.addWidget(label(tr("Installed version: {version}", version=__version__), "muted"))
        self.update_check = QCheckBox(tr("Check for updates automatically (at most every 6 hours)"))
        upd.body.addWidget(self.update_check)
        brow = QHBoxLayout()
        self.update_beta = QCheckBox(tr("Receive beta updates"))
        brow.addWidget(self.update_beta)
        brow.addWidget(InfoButton(tr("You get new versions earlier, but they may still contain bugs. You can switch "
                                     "this off and return to the latest stable version under “All versions” at any "
                                     "time.")))
        brow.addStretch(1)
        upd.body.addLayout(brow)
        urow = QHBoxLayout()
        ubtn = QPushButton(tr("Check for updates now"))
        ubtn.clicked.connect(lambda: self.main.check_updates(True))
        urow.addWidget(ubtn)
        vbtn = QPushButton(tr("All versions …"))
        vbtn.setToolTip(tr("Read the release notes of every version or install an older one"))
        vbtn.clicked.connect(self._versions)
        urow.addWidget(vbtn)
        urow.addStretch(1)
        upd.body.addLayout(urow)
        upd.body.addStretch(1)

        data = Card(tr("Data"),
                    tr("Webhook URL, server links and IDs are encrypted on this PC with your Windows account. To "
                       "move to a new PC: export here (with a password) and import on the new PC.\n\nThe "
                       "diagnostics package contains the log and value history, but no webhook URL and no links."))
        path = label(str(app_paths.data_dir()), "small", wrap=True)
        path.setToolTip(str(app_paths.data_dir()))
        data.body.addWidget(path)
        srow = QHBoxLayout()
        self.storage_label = label("", "small")
        clean_btn = QPushButton(tr("Clean up"))
        clean_btn.setToolTip(tr("Delete older logs, debug images and update leftovers – statistics, raids and "
                                "settings stay"))
        clean_btn.clicked.connect(self._clean_storage)
        srow.addWidget(self.storage_label)
        srow.addWidget(clean_btn)
        srow.addStretch(1)
        data.body.addLayout(srow)
        drow = QHBoxLayout()
        open_btn = QPushButton(tr("Open folder"))
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_paths.data_dir()))))
        diag_btn = QPushButton(tr("Diagnostics package"))
        diag_btn.setToolTip(tr("Log, value history and settings without webhook and links – for troubleshooting"))
        diag_btn.clicked.connect(lambda: self.main.create_diagnostics())
        wiz_btn = QPushButton(tr("Wizard"))
        wiz_btn.setToolTip(tr("Open the setup wizard again"))
        wiz_btn.clicked.connect(lambda: self.main.open_wizard())
        for btn in (open_btn, diag_btn, wiz_btn):
            drow.addWidget(btn)
        drow.addStretch(1)
        data.body.addLayout(drow)
        xrow = QHBoxLayout()
        exp_btn = QPushButton(tr("Export …"))
        exp_btn.setToolTip(tr("All settings as a password-protected file – for a new PC"))
        exp_btn.clicked.connect(lambda: self.main.export_settings())
        imp_btn = QPushButton(tr("Import …"))
        imp_btn.clicked.connect(lambda: self.main.import_settings())
        safe_btn = QPushButton(tr("Safe start"))
        safe_btn.setToolTip(tr("Restart with default settings without deleting yours – helps when something stops "
                               "working. Also possible: hold Shift while starting."))
        safe_btn.clicked.connect(lambda: self.main.restart_app(safe=True))
        xrow.addWidget(exp_btn)
        xrow.addWidget(imp_btn)
        xrow.addWidget(safe_btn)
        xrow.addStretch(1)
        data.body.addLayout(xrow)
        data.body.addStretch(1)
        root.addLayout(columns(stack(upd, rpc), data))
        root.addWidget(section(tr("Macro")))
        macro = Card(tr("Macro (beta)"),
                     tr("The macro clicks in Roblox by itself: farm routine (start page), auto collect and "
                        "exploring. It opens menus using the UI map – no walking, no teleporting.\n\nEmergency "
                        "stop: move the mouse, Esc or “Stop”. Roblox must be visible (not minimized) and is brought "
                        "to the front.\n\nMacros are against the Roblox rules – use at your own risk."))
        self.macro_on = QCheckBox(tr("Allow macro"))
        self.macro_on.setChecked(bool(main.engine.settings.automation_enabled))
        self.macro_on.toggled.connect(self._toggle_macro)
        macro.body.addWidget(self.macro_on)
        self.macro_log_home = QCheckBox(tr("Also show the macro log on the start page"))
        self.macro_log_home.setChecked(bool(main.engine.settings.macro_log_home))
        self.macro_log_home.toggled.connect(self._toggle_log_home)
        macro.body.addWidget(self.macro_log_home)
        mrow = QHBoxLayout()
        stop_macro = QPushButton(tr("■ Stop macro"))
        stop_macro.clicked.connect(main.macro.stop)
        mrow.addWidget(stop_macro)
        mrow.addStretch(1)
        macro.body.addLayout(mrow)
        explore = Card(tr("Explore"),
                       tr("The macro takes over Roblox for the set time and learns the game: first the worlds in "
                          "the teleporter (pets, crafting, raids, gachas), then the buttons at the screen edge "
                          "(shop, guild, achievements …). It clicks through tabs, looks for scrollable lists and "
                          "tests view-only buttons. Windows you already checked are skipped.\n\nIt never presses "
                          "action buttons (Claim, Buy, Roll, Max …) or dangerous ones (Leave, Kick, Delete …) – "
                          "nothing is clicked or scrolled around them; in the guild the whole bottom-left corner is "
                          "off limits. Anti-AFK pauses meanwhile.\n\nEmergency stop: move the mouse or Esc."))
        eg = form_grid()
        self.explore_minutes = SpinBox()
        self.explore_minutes.setRange(1, 60)
        self.explore_minutes.setSuffix(tr(" min"))
        eg.addWidget(label(tr("At most")), 0, 0)
        eg.addWidget(self.explore_minutes, 0, 1)
        explore.body.addLayout(eg)
        self.explore_revisit = QCheckBox(tr("Reopen windows that aren't checked yet"))
        explore.body.addWidget(self.explore_revisit)
        erow = QHBoxLayout()
        start_explore = QPushButton(tr("Explore now …"))
        start_explore.setObjectName("primary")
        start_explore.clicked.connect(self._start_explore)
        report = QPushButton(tr("Open report"))
        report.clicked.connect(main.macro.open_report)
        forget = QPushButton(tr("Forget what was learned …"))
        forget.setToolTip(tr("Delete windows, tabs and drops learned by exploring – the bundled map stays"))
        forget.clicked.connect(self._forget_explore)
        check = QPushButton(tr("Check findings …"))
        check.setToolTip(tr("Confirm or correct what exploring found, window by window"))
        check.clicked.connect(lambda: self.main.macro.open_review(always=True))
        for btn in (start_explore, check, report, forget):
            erow.addWidget(btn)
        erow.addStretch(1)
        explore.body.addLayout(erow)
        explore.body.addStretch(1)
        from .macro_log import MacroLogCard
        self.macro_log = MacroLogCard(main.macro)
        root.addLayout(columns(stack(macro, explore), self.macro_log), 10)

        root.addWidget(section(tr("Discord bot")))
        bot = Card(tr("Discord bot"),
                   tr("Control the program from Discord – with your own bot. A shared bot isn't possible because "
                      "its key would be public in the program. The bot only runs while the program is open and only "
                      "listens to the allowed Discord IDs.\n\nSetup (2 minutes): "
                      "discord.com/developers/applications → New Application → “Bot” on the left → “Reset Token” → "
                      "copy the token, enter it here and save. Then “Open invite link” and add the bot to your "
                      "server. It needs no special permissions (intents).\n\nCommands: /status, /start, /stop, "
                      "/pause, /screenshot, /raid, /macro, /antiafk, /autorejoin, /join, /pc, /help."))
        self.bot_enabled = QCheckBox(tr("Discord bot active"))
        bot.body.addWidget(self.bot_enabled)
        bg = form_grid()
        bg.setColumnStretch(1, 1)
        bg.setColumnStretch(2, 0)
        self.bot_token = QLineEdit()
        self.bot_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.bot_token.setPlaceholderText(tr("Your bot's token (developer portal → Bot → Reset Token)"))
        self.bot_users = QLineEdit()
        self.bot_users.setPlaceholderText(tr("empty = your ping ID from “Alerts”; several separated by commas"))
        bg.addWidget(label(tr("Bot token")), 0, 0)
        bg.addWidget(self.bot_token, 0, 1)
        bg.addWidget(label(tr("Allowed Discord IDs")), 1, 0)
        bg.addWidget(self.bot_users, 1, 1)
        bot.body.addLayout(bg)
        self.bot_power = QCheckBox(tr("Allow /pc: shut down or restart the PC (60 s, can be cancelled)"))
        bot.body.addWidget(self.bot_power)
        self.bot_state = label(tr("off"), "small", wrap=True)
        bot.body.addWidget(self.bot_state)
        brow = QHBoxLayout()
        self.bot_invite = QPushButton(tr("Open invite link"))
        self.bot_invite.setEnabled(False)
        self.bot_invite.clicked.connect(self._open_bot_invite)
        brow.addWidget(self.bot_invite)
        brow.addStretch(1)
        bot.body.addLayout(brow)
        bot.body.addStretch(1)
        root.addLayout(columns(bot, QWidget()))
        main.bot.listeners.append(self._bot_state_changed) if hasattr(main, "bot") else None

        root.addWidget(section(tr("Debug")))
        from .events_card import EventsCard
        self.events = EventsCard(main)                    # debug: live log (on/off)
        root.addWidget(self.events, 10)
        root.addStretch(1)
        root.addLayout(self._about_row())
        self._assign_groups(root)
        self.tab_group.buttons()[0].setChecked(True)
        self._show_group("Roblox")
        self._search_index: list = []               # (card, searchable text) – filled at the first search

    # ------------------------------------------------------------------ Roblox profile
    def _apply_profile(self) -> None:
        from .. import roblox_profile
        name = self.roblox_name.text().strip()
        if name and not roblox_profile.valid_name(name):
            self.profile_state.setText(tr("Not a valid Roblox name (3–20 characters: letters, digits, _)."))
            return
        self.main.set_roblox_name(name, self.show_profile)
        if name:
            self.profile_state.setText(tr("Loading …"))

    def show_profile(self, error: str = "") -> None:
        """Preview and status after loading (also at start-up)."""
        from .. import roblox_profile
        from .widgets import round_pixmap
        info = roblox_profile.load_info() if self.main.engine.settings.roblox_username else None
        pix = round_pixmap(roblox_profile.avatar_file(), theme.px(48)) if info else None
        self.avatar_preview.setPixmap(pix) if pix else self.avatar_preview.clear()
        self.avatar_preview.setVisible(pix is not None)          # no empty gap without a profile
        if error:
            self.profile_state.setText(error)
        elif info:
            self.profile_state.setText(tr("Connected: {display} (@{name})", display=info.get("display", ""),
                                          name=info.get("name", "")))
        else:
            self.profile_state.setText("")

    # ------------------------------------------------------------------ Tabs
    def _assign_groups(self, root) -> None:
        """Assign cards to the sections (order as on the page: section heading, then its cards)."""
        from PySide6.QtWidgets import QLabel
        self._groups: dict = {}
        self._holders: dict = {}                          # section -> row widgets (hide them entirely, otherwise
        current = None                                    # the spacing of empty rows stays)
        for i in range(root.count()):
            item = root.itemAt(i)
            if item.layout() is not None and current is not None:   # pack a row of cards into a widget
                stretch = root.stretch(i)
                root.takeAt(i)
                lay = item.layout()
                lay.setParent(None)
                holder = QWidget()
                lay.setContentsMargins(0, 0, 0, 0)
                holder.setLayout(lay)
                root.insertWidget(i, holder, stretch)
                item = root.itemAt(i)
            w = item.widget()
            if isinstance(w, QLabel) and w.objectName() == "section":
                current = w
                self._groups[w] = []
                self._holders[w] = []
            elif current is not None and w is not None:          # card or row with several cards
                self._groups[current] += [w] if isinstance(w, Card) else w.findChildren(Card)
                self._holders[current].append(w)

    def _show_group(self, key: str) -> None:
        """Show only one section (less scrolling); the search shows all matches instead."""
        self._group = key
        if self.search.text().strip():
            return
        for sec, cards in self._groups.items():
            visible = sec.text() == tr(key).upper()
            sec.setVisible(False)                          # the tab replaces the heading
            for card in cards:
                card.setVisible(visible)
            for holder in self._holders.get(sec, ()):
                holder.setVisible(visible)

    # ------------------------------------------------------------------ Search
    def _build_index(self) -> None:
        from ..search import Haystack
        import re
        from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel
        tags = re.compile(r"<[^>]+>")
        for card in self.findChildren(Card):
            parts = []
            for w in [card] + card.findChildren(QWidget):
                if isinstance(w, QLabel):
                    parts.append(w.text())
                elif isinstance(w, QAbstractButton):
                    parts.append(w.text())
                elif isinstance(w, QLineEdit):
                    parts.append(w.placeholderText())
                elif isinstance(w, QComboBox):
                    parts += [w.itemText(i) for i in range(w.count())]
                parts.append(w.toolTip())                    # also the explanations behind ⓘ
            self._search_index.append((card, Haystack(tags.sub(" ", " ".join(parts)))))

    def _filter(self, text: str) -> None:
        """Only show cards containing all search words (title, labels, ⓘ explanations) – tolerant of umlauts,
        hyphens and small typos (search.py)."""
        from PySide6.QtWidgets import QLabel

        from ..search import matches
        if not self._search_index:
            self._build_index()
        words = text.casefold().split()
        if not words:
            self.no_match.setVisible(False)
            self._show_group(getattr(self, "_group", "Roblox"))
            return
        shown = 0
        for card, haystack in self._search_index:
            match = matches(text, haystack)
            card.setVisible(match)
            shown += match
        for sec, holders in self._holders.items():
            for holder in holders:                         # show a row as soon as one of its cards matches
                holder.setVisible(any(not c.isHidden() for c in self._groups[sec]
                                      if holder is c or holder.isAncestorOf(c)))
        for sec in self.findChildren(QLabel, "section"):
            sec.setVisible(not words)
        self.no_match.setVisible(bool(words) and not shown)

    # ------------------------------------------------------------------ About (small, at the very bottom)
    def _about_row(self) -> QHBoxLayout:
        from .. import updater
        row = QHBoxLayout()
        theme.track_spacing(row, 14)
        row.addWidget(label(f"Anime Astral Monitor {__version__}", "small"))
        repo = updater.current_repo()
        links = []
        if repo:
            links.append((tr("GitHub"), f"https://github.com/{repo}"))
            links.append((tr("Report a bug"), bug_report_url(repo)))
        third = Path(sys.executable).resolve().parent / "THIRD_PARTY.txt"
        if third.is_file():
            links.append((tr("Third-party components"), QUrl.fromLocalFile(str(third)).toString()))
        for text, url in links:
            link = label(f"<a href='{url}'>{text}</a>", "small")
            link.setOpenExternalLinks(True)
            row.addWidget(link)
        row.addStretch(1)
        return row

    # ------------------------------------------------------------------ Server favorites
    def load_servers(self, s) -> None:
        self.servers.blockSignals(True)
        self.servers.clear()
        for fav in s.server_favorites:
            active = fav["link"] == s.private_server_link
            item = QListWidgetItem(("● " if active else "    ") + fav["name"] + "   ·   "
                                   + roblox_join.explain(fav["link"]))
            item.setToolTip(tr("Marked = used for “Join server” and auto-rejoin") if active else "")
            self.servers.addItem(item)
            if active:
                self.servers.setCurrentItem(item)
        if not s.server_favorites:
            empty = QListWidgetItem(tr("No server yet – save your share link with “New …”."))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.servers.addItem(empty)
        self.servers.blockSignals(False)

    def _favs(self) -> list:
        return [dict(f) for f in self.main.engine.settings.server_favorites]

    def _selected(self) -> int:
        row = self.servers.currentRow()
        return row if 0 <= row < len(self.main.engine.settings.server_favorites) else -1

    def _server_selected(self, row: int) -> None:
        favs = self._favs()
        if 0 <= row < len(favs) and favs[row]["link"] != self.main.engine.settings.private_server_link:
            self.main.set_server_favorites(favs, favs[row]["link"])      # selection = marked server

    def _add_server(self) -> None:
        favs = self._favs()
        if len(favs) >= MAX_FAVORITES:
            QMessageBox.information(self, tr("Private server"), tr("At most {n} servers.", n=MAX_FAVORITES))
            return
        dlg = ServerDialog(self, tr("Add server"), taken=tuple(f["name"] for f in favs))
        if dlg.exec():
            favs.append({"name": dlg.result_name(), "link": dlg.result_link()})
            self.main.set_server_favorites(favs, dlg.result_link())

    def _edit_server(self) -> None:
        i, favs = self._selected(), self._favs()
        if i < 0:
            return
        old = favs[i]
        dlg = ServerDialog(self, tr("Edit server"), old["name"], old["link"],
                           taken=tuple(f["name"] for j, f in enumerate(favs) if j != i))
        if dlg.exec():
            was_active = old["link"] == self.main.engine.settings.private_server_link
            favs[i] = {"name": dlg.result_name(), "link": dlg.result_link()}
            self.main.set_server_favorites(favs, favs[i]["link"] if was_active
                                           else self.main.engine.settings.private_server_link)

    def _delete_server(self) -> None:
        i, favs = self._selected(), self._favs()
        if i < 0:
            return
        if QMessageBox.question(self, tr("Delete server"), tr("Delete “{name}” from the list?",
                                                               name=favs[i]["name"])) != QMessageBox.StandardButton.Yes:
            return
        del favs[i]
        self.main.set_server_favorites(favs, self.main.engine.settings.private_server_link)

    def _join_selected(self) -> None:
        i = self._selected()
        if i >= 0:
            self.main.join_favorite(i)
        else:
            self.main.join_private_server()

    def _server_menu(self, pos) -> None:
        item = self.servers.itemAt(pos)
        if item is None or self.servers.row(item) >= len(self.main.engine.settings.server_favorites):
            return
        self.servers.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction(tr("Join"), self._join_selected)
        menu.addAction(tr("Edit …"), self._edit_server)
        menu.addAction(tr("Copy code to share"), self._share_server)
        menu.addSeparator()
        menu.addAction(tr("Delete"), self._delete_server)
        menu.exec(self.servers.viewport().mapToGlobal(pos))

    def _share_server(self) -> None:
        from PySide6.QtWidgets import QApplication
        i = self._selected()
        if i < 0:
            return
        fav = self.main.engine.settings.server_favorites[i]
        QApplication.clipboard().setText(roblox_join.share_code(fav["name"], fav["link"]))
        self.main.show_toast(tr("Code copied – friends paste it as the link under “Add server”. Anyone who has it "
                                "can join."))

    def _versions(self) -> None:
        from .versions_dialog import VersionsDialog
        VersionsDialog(self.main).exec()

    # ------------------------------------------------------------------ Appearance
    def _swatch(self, hex_color: str) -> QToolButton:
        btn = QToolButton()
        btn.setCheckable(True)
        btn.setProperty("accent", hex_color)
        btn.setToolTip(hex_color)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        size = theme.px(24)
        btn.setFixedSize(size, size)
        btn.setStyleSheet(f"QToolButton {{ background: {hex_color}; border-radius: {size // 2}px; padding: 0; "
                          f"min-width: {size - 4}px; max-width: {size - 4}px; min-height: {size - 4}px; "
                          f"max-height: {size - 4}px; border: 2px solid transparent; }}"
                          "QToolButton:checked { border: 2px solid palette(window-text); }")
        self.accent_group.addButton(btn)
        return btn

    def _pick_background(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from .backdrop import import_image
        path, _ = QFileDialog.getOpenFileName(self, tr("Choose background image"), str(Path.home() / "Pictures"),
                                              tr("Images (*.png *.jpg *.jpeg *.webp *.bmp)"))
        if not path:
            return
        try:
            name = import_image(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Background"), tr("The image could not be loaded: {error}", error=exc))
            return
        self.main.set_appearance(background=name)
        self._sync_look(self.main.engine.settings)

    def _accent_from_image(self) -> None:
        from .backdrop import accent_from_image, stored_path
        path = stored_path(self.main.engine.settings.ui_background)
        color = accent_from_image(path) if path else None
        if not color:
            self.main.show_toast(tr("The image has no strong color – pick a color by hand"))
            return
        self.main.set_appearance(accent=color)
        self._sync_look(self.main.engine.settings)
        self.main.show_toast(tr("Accent color from the image: {color}", color=color))

    def _pick_accent(self) -> None:
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        s = self.main.engine.settings
        color = QColorDialog.getColor(QColor(s.ui_accent or theme.color("accent")), self, tr("Accent color"))
        if color.isValid():
            self.main.set_appearance(accent=color.name().upper())
        self._sync_look(s)

    def _set_zoom(self, value: int) -> None:
        self.main.set_appearance(zoom=value)
        self._sync_look(self.main.engine.settings)

    def _sync_look(self, s) -> None:
        """Set the appearance controls to the saved state (without triggering again)."""
        widgets = [self.design, self.zoom, self.auto_fit, self.reduce_motion, self.intro, self.bg_dim, self.seasonal,
                   self.spooky] + [b for _p, b in self.zoom_buttons]
        widgets += self.mode_group.buttons() + self.accent_group.buttons()
        for w in widgets:
            w.blockSignals(True)
        self.design.setCurrentIndex(max(0, self.design.findData(s.ui_design)))
        self.zoom.setValue(s.ui_zoom)
        self.auto_fit.setChecked(s.ui_auto_fit)
        self.reduce_motion.setChecked(s.ui_reduce_motion)
        self.intro.setChecked(s.ui_intro)
        self.seasonal.setChecked(s.ui_seasonal)
        self.spooky.setChecked(s.ui_spooky)
        self.bg_dim.setValue(s.ui_background_dim)
        self.bg_dim.setEnabled(bool(s.ui_background))
        self.bg_remove.setEnabled(bool(s.ui_background))
        self.accent_image.setEnabled(bool(s.ui_background))
        self.intro.setEnabled(not s.ui_reduce_motion)
        for pct, btn in self.zoom_buttons:
            btn.setChecked(pct == s.ui_zoom)
        preset = {b.property("accent") for b in self.accent_group.buttons() if b is not self.accent_custom}
        for btn in self.accent_group.buttons():
            btn.setChecked(btn.property("accent") == s.ui_accent if btn is not self.accent_custom
                           else s.ui_accent not in preset)
        self.accent_custom.setToolTip(s.ui_accent if s.ui_accent not in preset else tr("Choose a custom color"))
        light_ok = theme.has_mode(theme.design(), "light")      # effective design (maybe seasonal)
        for btn in self.mode_group.buttons():
            mode = btn.property("mode")
            btn.setEnabled(light_ok or mode == "dark")
            btn.setChecked(mode == (s.ui_mode if light_ok else "dark"))
        self.mode_hint.setText("" if light_ok else tr("The “{name}” design is only available in dark.",
                                                      name=tr(theme.design_info(s.ui_design)["name"])))
        self.mode_hint.setVisible(not light_ok)
        for w in widgets:
            w.blockSignals(False)

    def _show_preset(self) -> None:
        preset = PRESETS.get(self.perf.currentData(), PRESETS["balanced"])
        self.perf.setToolTip(tr("Wave counter every {interval} s, quests every {quest} s.",
                                  interval=dec(f"{preset['interval']:g}"), quest=f"{preset['quest']:g}"))

    # ------------------------------------------------------------------ Storage
    def refresh_storage(self) -> None:
        try:
            items = storage.usage()
        except OSError:
            return
        total = sum(u.size for u in items)
        self.storage_label.setText(tr("Used: {size}", size=storage.fmt_size(total)))
        self.storage_label.setToolTip("\n".join(f"{tr(u.label)}: {storage.fmt_size(u.size)}"
                                                for u in items if u.size))

    def _clean_storage(self) -> None:
        freed = storage.clean()
        self.refresh_storage()
        self.main.show_toast(tr("Cleaned up: {size} freed", size=storage.fmt_size(freed)))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_storage()

    def _bot_state_changed(self, state: str, app_id: str) -> None:
        # before the first connect: use the same application as the Discord profile status (same application ID)
        app_id = app_id or (self.main.engine.settings.rpc_client_id or "").strip()
        self.bot_state.setText(tr("State: {state}", state=state))
        self.bot_invite.setEnabled(app_id.isdigit())
        self._bot_app_id = app_id

    def _open_bot_invite(self) -> None:
        from ..discord_bot import invite_url
        app_id = getattr(self, "_bot_app_id", "")
        if app_id:
            QDesktopServices.openUrl(QUrl(invite_url(app_id)))

    def _start_explore(self) -> None:
        s = self.main.engine.settings
        s.explore_minutes, s.explore_revisit = self.explore_minutes.value(), self.explore_revisit.isChecked()
        self.main.macro.start_explore(self)

    def _toggle_macro(self, on: bool) -> None:
        if self.main.macro.set_enabled(on, self) != on:      # warning declined
            self.macro_on.blockSignals(True)
            self.macro_on.setChecked(False)
            self.macro_on.blockSignals(False)

    def _toggle_log_home(self, on: bool) -> None:
        s = self.main.engine.settings
        s.macro_log_home = bool(on)
        try:
            s.save()                                      # right away, without the save bar
        except OSError:
            pass
        self.main.pages[0].set_log_visible(bool(on))

    def _forget_explore(self) -> None:
        if QMessageBox.question(self, tr("Explore"), tr("Forget everything exploring has learned?")) \
                != QMessageBox.StandardButton.Yes:
            return
        from ..explorer import forget_local
        forget_local(app_paths.data_dir())
        (app_paths.data_dir() / "explore" / "deep_done.json").unlink(missing_ok=True)
        (app_paths.data_dir() / "explore" / "review.json").unlink(missing_ok=True)
        self.main.macro.reload_map()

    def load(self, s) -> None:
        for box, value in ((self.macro_on, s.automation_enabled), (self.macro_log_home, s.macro_log_home)):
            box.blockSignals(True)
            box.setChecked(bool(value))
            box.blockSignals(False)
        self.bot_enabled.setChecked(bool(s.bot_enabled))
        self.bot_token.setText(s.bot_token)
        self.bot_users.setText(s.bot_users)
        self.bot_power.setChecked(bool(s.bot_power))
        if hasattr(self.main, "bot"):
            self._bot_state_changed(self.main.bot.state, self.main.bot.app_id)
        self.explore_minutes.setValue(int(s.explore_minutes))
        self.explore_revisit.setChecked(bool(s.explore_revisit))
        self.roblox_name.setText(s.roblox_username)
        self._sync_look(s)
        self.language.setCurrentIndex(max(0, self.language.findData(s.language)))
        self.close_to_tray.setChecked(s.close_to_tray)
        self.afk_minutes.setValue(s.anti_afk_minutes)
        self.load_servers(s)
        self.perf.setCurrentIndex(max(0, self.perf.findData(s.performance)))
        self._show_preset()
        self.low_priority.setChecked(s.low_priority)
        self.guard_enabled.setChecked(s.guard_enabled)
        self.stall.setValue(s.stall_minutes)
        self.no_raid.setValue(s.no_raid_minutes)
        self.ram.setValue(s.ram_alert_gb)
        self.hk_toggle.setText(s.hotkey_toggle)
        self.hk_pause.setText(s.hotkey_pause)
        self.hk_status_edit.setText(s.hotkey_status)
        self.update_check.setChecked(s.update_check)
        self.update_beta.setChecked(s.update_beta)
        self.rpc_enabled.setChecked(s.rpc_enabled)
        self.rpc_id.setText(s.rpc_client_id)
        self.rpc_link.setText(s.rpc_game_link)

    def set_hotkey_status(self, text: str, ok: bool) -> None:
        self.hk_status.setText(text)
        self.hk_status.setObjectName("good" if ok else "bad")
        self.hk_status.style().unpolish(self.hk_status)
        self.hk_status.style().polish(self.hk_status)

    def apply(self, s) -> None:
        s.bot_enabled = self.bot_enabled.isChecked()
        s.bot_token = self.bot_token.text().strip()
        s.bot_users = self.bot_users.text().strip()
        s.bot_power = self.bot_power.isChecked()
        s.explore_minutes = self.explore_minutes.value()
        s.explore_revisit = self.explore_revisit.isChecked()
        s.language = self.language.currentData() or "de"
        s.close_to_tray = self.close_to_tray.isChecked()
        s.anti_afk_minutes = self.afk_minutes.value()
        s.performance = self.perf.currentData()
        s.low_priority = self.low_priority.isChecked()
        s.guard_enabled = self.guard_enabled.isChecked()
        s.stall_minutes = self.stall.value()
        s.no_raid_minutes = self.no_raid.value()
        s.ram_alert_gb = self.ram.value()
        from ..hotkeys import english_hotkey
        s.hotkey_toggle = english_hotkey(self.hk_toggle.text().strip())
        s.hotkey_pause = english_hotkey(self.hk_pause.text().strip())
        s.hotkey_status = english_hotkey(self.hk_status_edit.text().strip())
        s.update_check = self.update_check.isChecked()
        s.update_beta = self.update_beta.isChecked()
        s.rpc_enabled = self.rpc_enabled.isChecked()
        s.rpc_client_id = self.rpc_id.text().strip()
        s.rpc_game_link = self.rpc_link.text().strip()

    def refresh(self) -> None:
        presence = self.main.engine.presence
        self.rpc_state.setText(("✅ " if presence.status_ok else "ℹ️ ") + presence.status_text)
