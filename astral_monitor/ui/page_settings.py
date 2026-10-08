"""Seite „Einstellungen": Roblox-Helfer, Überwachung, Programm."""
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
    """Neue GitHub-Meldung, vorausgefüllt mit Version und System – ohne persönliche Daten (keine IDs, Links, Pfade)."""
    body = "\n\n\n".join([f"**{tr('Was ist passiert?')}**", f"**{tr('Was hast du erwartet?')}**",
                          f"---\nVersion {__version__} · {platform.system()} {platform.release()} "
                          f"({platform.version()})"])
    return f"https://github.com/{repo}/issues/new?" + urlencode({"title": "", "body": body})


class SettingsPage(QWidget):
    SAVES = True                                   # Speichern-Leiste unten (main_window)

    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 14)
        self.search = short_field(QLineEdit(), 300)
        self.search.setPlaceholderText(tr("Einstellung suchen …"))
        self.search.setToolTip(tr("Sucht in allen Reitern – auch in den ⓘ-Erklärungen. Von überall: Strg+F"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        tabs = QHBoxLayout()
        theme.track_spacing(tabs, 4)
        tabs.addWidget(label(tr("Einstellungen"), "h1"))
        tabs.addSpacing(theme.px(14))
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for key in ("Roblox", "Makro", "Discord-Bot", "Überwachung", "Darstellung", "Programm", "Debug"):
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
        self.no_match = label(tr("Keine Einstellung gefunden."), "muted")
        self.no_match.setVisible(False)
        root.addWidget(self.no_match)

        def stack(*cards) -> QWidget:
            """Mehrere Karten untereinander als eine Spalte (für columns)."""
            col = QWidget()
            lay = QVBoxLayout(col)
            lay.setContentsMargins(0, 0, 0, 0)
            theme.track_spacing(lay, 14)
            for card in cards:
                lay.addWidget(card)
            return col

        # ------------------------------------------------------------------ Roblox
        root.addWidget(section(tr("Roblox")))
        ps = Card(tr("Privater Server und Auto-Rejoin"),
                  tr("Der markierte Server gilt für „Server beitreten“ (Kopfzeile, Tray) und für Auto-Rejoin. "
                     "Roblox startet ohne Browser; Teilen-Links und klassische Links funktionieren. Die Links "
                     "liegen verschlüsselt nur auf diesem PC.\n\nAuto-Rejoin (Schalter in der Kopfzeile): Nach "
                     "Verbindungsabbruch, Kick oder Absturz tritt das Programm nach 15 s wieder bei – bis zu 5 "
                     "Versuche. Wer Roblox selbst schließt, wird nicht zurückgeholt."))
        self.servers = QListWidget()
        smooth(self.servers)
        theme.track_fixed_height(self.servers, 132)
        self.servers.currentRowChanged.connect(self._server_selected)
        self.servers.itemDoubleClicked.connect(lambda _i: self._join_selected())
        self.servers.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.servers.customContextMenuRequested.connect(self._server_menu)
        ps.body.addWidget(self.servers)
        prow = QHBoxLayout()
        add = QPushButton(tr("Neu …"))
        add.clicked.connect(self._add_server)
        edit = QPushButton(tr("Ändern …"))
        edit.clicked.connect(self._edit_server)
        delete = QPushButton(tr("Löschen"))
        delete.clicked.connect(self._delete_server)
        join = QPushButton(tr("Beitreten"))
        join.setObjectName("primary")
        join.clicked.connect(self._join_selected)
        for btn in (add, edit, delete):
            prow.addWidget(btn)
        prow.addStretch(1)
        prow.addWidget(join)
        ps.body.addLayout(prow)
        ps.body.addStretch(1)

        afk = Card(tr("Anti-AFK"),
                   tr("Einschalten in der Kopfzeile. Holt alle paar Minuten jedes Roblox-Fenster kurz nach vorne "
                      "(minimierte werden wiederhergestellt und bleiben offen, damit die Erkennung läuft), drückt "
                      "4× Esc – das Roblox-Menü geht auf und wieder zu – und wechselt sofort zurück. Danach wird der "
                      "Arbeitsspeicher von Roblox geleert.\n\nHinweis: Makros sind laut Roblox-Regeln nicht erlaubt – "
                      "Nutzung auf eigene Verantwortung."))
        ag = form_grid()
        self.afk_minutes = SpinBox()
        self.afk_minutes.setRange(1, 19)
        self.afk_minutes.setSuffix(tr(" Min"))
        ag.addWidget(label(tr("Ausführen alle")), 0, 0)
        ag.addWidget(self.afk_minutes, 0, 1)
        afk.body.addLayout(ag)
        afk.body.addStretch(1)

        prof = Card(tr("Dein Roblox-Profil"),
                    tr("Nur dein Roblox-Name – Anzeigename und Avatar kommen über die öffentliche Roblox-Seite, ohne "
                       "Anmeldung. Der Avatar erscheint in der Seitenleiste und auf den Statistik-Karten. Leer lassen "
                       "= kein Profil."))
        frow = QHBoxLayout()
        theme.track_spacing(frow, 10)
        self.avatar_preview = QLabel()
        theme.track(self.avatar_preview, lambda o, f: o.setFixedSize(round(48 * f), round(48 * f)))
        frow.addWidget(self.avatar_preview)
        self.roblox_name = short_field(QLineEdit(), 200)
        self.roblox_name.setPlaceholderText(tr("Roblox-Name"))
        self.roblox_name.returnPressed.connect(self._apply_profile)
        frow.addWidget(self.roblox_name)
        apply_btn = QPushButton(tr("Übernehmen"))
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
                    tr("Wirken global, auch während des Spiels. Format: Ctrl+Alt+S, Shift+F9 … (Ctrl, Alt, Shift, "
                       "Win). Einzelne F-Tasten vermeiden, die Roblox selbst nutzt."))
        kg = form_grid()
        self.hk_toggle = short_field(QLineEdit())
        self.hk_pause = short_field(QLineEdit())
        self.hk_status_edit = short_field(QLineEdit())
        kg.addWidget(label(tr("Start / Stopp")), 0, 0)
        kg.addWidget(self.hk_toggle, 0, 1)
        kg.addWidget(label(tr("Pause / Fortsetzen")), 1, 0)
        kg.addWidget(self.hk_pause, 1, 1)
        kg.addWidget(label(tr("Status neu senden")), 2, 0)
        kg.addWidget(self.hk_status_edit, 2, 1)
        keys.body.addLayout(kg)
        self.hk_status = label("", "small", wrap=True)
        keys.body.addWidget(self.hk_status)
        keys.body.addStretch(1)
        # ------------------------------------------------------------------ Überwachung
        root.addWidget(section(tr("Überwachung")))
        perf = Card(tr("Leistung"),
                    tr("Wie oft der Wellenzähler gelesen wird – gleichmäßig, auch kurz vor Raid-Ende. "
                       "„Ausgewogen“ (alle 0,5 s) erkennt das Raid-Ende sicher und passt für die meisten. Die genauen "
                       "Zeiten zeigt die Auswahl, wenn du darüberfährst."))
        pg = form_grid()
        self.perf = ComboBox()
        for key, preset in PRESETS.items():
            self.perf.addItem(tr(preset["label"]), key)
        self.perf.currentIndexChanged.connect(self._show_preset)
        pg.addWidget(label(tr("Prüfrate")), 0, 0)
        pg.addWidget(self.perf, 0, 1)
        perf.body.addLayout(pg)
        self.low_priority = QCheckBox(tr("Niedrige Prozesspriorität (das Spiel hat Vorrang)"))
        perf.body.addWidget(self.low_priority)
        perf.body.addStretch(1)

        guard = Card(tr("Wächter"),
                     tr("Meldet Abstürze (Roblox-Prozess), Disconnects und Kicks (Roblox-Protokoll), einen "
                        "stehenden Zähler, zu lange kein beendeter Raid und zu hohen Speicherverbrauch von Roblox. "
                        "Was davon an Discord geht, stellst du unter „Meldungen“ ein."))
        self.guard_enabled = QCheckBox(tr("Wächter aktiv"))
        guard.body.addWidget(self.guard_enabled)
        gg = form_grid()
        self.stall = SpinBox()
        self.stall.setRange(1, 240)
        self.stall.setSuffix(tr(" Min"))
        self.no_raid = SpinBox()
        self.no_raid.setRange(0, 1440)
        self.no_raid.setSuffix(tr(" Min"))
        self.no_raid.setSpecialValueText(tr("aus"))
        self.ram = DoubleSpinBox()
        self.ram.setRange(0, 64)
        self.ram.setSingleStep(0.5)
        self.ram.setDecimals(1)
        self.ram.setSuffix(tr(" GB"))
        self.ram.setSpecialValueText(tr("aus"))
        gg.addWidget(label(tr("Stillstand nach")), 0, 0)
        gg.addWidget(self.stall, 0, 1)
        gg.addWidget(label(tr("Kein Raid beendet seit")), 1, 0)
        gg.addWidget(self.no_raid, 1, 1)
        gg.addWidget(label(tr("Roblox-Speicher über")), 2, 0)
        gg.addWidget(self.ram, 2, 1)
        guard.body.addLayout(gg)
        guard.body.addStretch(1)
        root.addLayout(columns(stack(perf, keys), guard))

        # ------------------------------------------------------------------ Programm
        ui = Card(tr("Oberfläche"),
                  tr("Ein Sprachwechsel gilt nach einem Neustart.\n\nSchließt du das Fenster, läuft das Programm "
                     "im Infobereich (Symbol neben der Uhr) weiter. Rechtsklick auf das Symbol: Öffnen, "
                     "Start/Stopp, Pause, Server beitreten, Anti-AFK, Auto-Rejoin, Auto-Start, Beenden."))
        ug = form_grid()
        self.language = ComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        ug.addWidget(label(tr("Sprache / Language")), 0, 0)
        ug.addWidget(self.language, 0, 1)
        ui.body.addLayout(ug)
        self.close_to_tray = QCheckBox(tr("Beim Schließen im Infobereich weiterlaufen"))
        ui.body.addWidget(self.close_to_tray)
        ui.body.addStretch(1)

        root.addWidget(section(tr("Darstellung")))
        look = Card(tr("Aussehen"),
                    tr("Änderungen gelten sofort. Ältere Designs bleiben hier auswählbar, mit der Version, in der "
                       "sie eingeführt wurden.\n\nUI-Größe: kleiner = mehr pro Seite sichtbar. „An die "
                       "Fenstergröße anpassen“ vergrößert bzw. verkleinert zusätzlich mit dem Fenster."))
        lg = form_grid()
        self.design = ComboBox()
        for key, info in theme.DESIGNS.items():
            self.design.addItem(tr("{name} (seit Version {version})", name=tr(info["name"]), version=info["since"]),
                                key)
        self.design.activated.connect(lambda _i: self.main.set_appearance(design=self.design.currentData()))
        lg.addWidget(label(tr("Design")), 0, 0)
        lg.addWidget(self.design, 0, 1)
        mode_row = QHBoxLayout()
        theme.track_spacing(mode_row, 6)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for mode, text in (("dark", tr("Dunkel")), ("light", tr("Hell")), ("system", tr("Wie Windows"))):
            btn = QPushButton(text)
            btn.setObjectName("chipbtn")
            btn.setCheckable(True)
            btn.setProperty("mode", mode)
            self.mode_group.addButton(btn)
            mode_row.addWidget(btn)
        mode_row.addStretch(1)
        self.mode_group.buttonClicked.connect(lambda b: self.main.set_appearance(mode=b.property("mode")))
        lg.addWidget(label(tr("Farbschema")), 1, 0)
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
        self.zoom.setKeyboardTracking(False)              # erst nach Enter/Verlassen anwenden, nicht bei jeder Ziffer
        self.zoom.setToolTip(tr("Eigener Wert von {min} bis {max} %", min=theme.ZOOM_MIN, max=theme.ZOOM_MAX))
        self.zoom.valueChanged.connect(self._set_zoom)
        zoom_row.addWidget(self.zoom)
        zoom_row.addStretch(1)
        lg.addWidget(label(tr("UI-Größe")), 2, 0)
        lg.addLayout(zoom_row, 2, 1, 1, 2)
        accent_row = QHBoxLayout()
        theme.track_spacing(accent_row, 6)
        self.accent_group = QButtonGroup(self)
        self.accent_group.setExclusive(True)
        auto = QPushButton(tr("Design"))
        auto.setObjectName("chipbtn")
        auto.setCheckable(True)
        auto.setProperty("accent", "")
        auto.setToolTip(tr("Farbe des gewählten Designs"))
        self.accent_group.addButton(auto)
        accent_row.addWidget(auto)
        for hex_color in theme.ACCENTS:
            accent_row.addWidget(self._swatch(hex_color))
        self.accent_image = QPushButton(tr("Aus Bild"))
        self.accent_image.setObjectName("chipbtn")
        self.accent_image.setToolTip(tr("Kräftigste Farbe aus deinem Hintergrundbild übernehmen"))
        self.accent_image.clicked.connect(self._accent_from_image)
        accent_row.addWidget(self.accent_image)
        self.accent_custom = QPushButton(tr("Eigene …"))
        self.accent_custom.setObjectName("chipbtn")
        self.accent_custom.setCheckable(True)
        self.accent_custom.clicked.connect(self._pick_accent)
        accent_row.addWidget(self.accent_custom)
        accent_row.addStretch(1)
        self.accent_group.buttonClicked.connect(
            lambda b: b is not self.accent_custom and self.main.set_appearance(accent=b.property("accent")))
        self.accent_group.addButton(self.accent_custom)
        lg.addWidget(label(tr("Akzentfarbe")), 3, 0)
        lg.addLayout(accent_row, 3, 1, 1, 2)
        bg_row = QHBoxLayout()
        theme.track_spacing(bg_row, 6)
        pick_bg = QPushButton(tr("Bild wählen …"))
        pick_bg.clicked.connect(self._pick_background)
        self.bg_remove = QPushButton(tr("Entfernen"))
        self.bg_remove.clicked.connect(lambda: self.main.set_appearance(background="") or self._sync_look(
            self.main.engine.settings))
        self.bg_dim = SpinBox()
        self.bg_dim.setRange(0, 95)
        self.bg_dim.setSingleStep(5)
        self.bg_dim.setSuffix(" %")
        self.bg_dim.setPrefix(tr("Abdunkeln "))
        self.bg_dim.setKeyboardTracking(False)
        self.bg_dim.valueChanged.connect(lambda v: self.main.set_appearance(background_dim=v))
        for w in (pick_bg, self.bg_remove, self.bg_dim):
            bg_row.addWidget(w)
        bg_row.addStretch(1)
        lg.addWidget(label(tr("Hintergrund")), 4, 0)
        lg.addLayout(bg_row, 4, 1, 1, 2)
        look.body.addLayout(lg)
        self.auto_fit = QCheckBox(tr("Zusätzlich an die Fenstergröße anpassen"))
        self.auto_fit.toggled.connect(lambda on: self.main.set_appearance(fit=on))
        look.body.addWidget(self.auto_fit)
        self.mode_hint = label("", "small", wrap=True)
        look.body.addWidget(self.mode_hint)
        look.body.addStretch(1)
        fx = Card(tr("Effekte"))
        mrow = QHBoxLayout()
        self.reduce_motion = QCheckBox(tr("Animationen reduzieren"))
        self.reduce_motion.toggled.connect(lambda on: self.main.set_appearance(reduce_motion=on))
        self.reduce_motion.toggled.connect(lambda on: self.intro.setEnabled(not on))
        mrow.addWidget(self.reduce_motion)
        mrow.addWidget(InfoButton(tr("Seiten erscheinen ohne Überblendung, Schalter springen sofort um. "
                                     "Spart etwas Leistung, z. B. wenn Roblox nebenher läuft.")))
        mrow.addStretch(1)
        fx.body.addLayout(mrow)
        srow = QHBoxLayout()
        self.seasonal = QCheckBox(tr("Saison-Designs automatisch"))
        self.seasonal.toggled.connect(lambda on: (self.main.set_appearance(seasonal=on),
                                                  self._sync_look(self.main.engine.settings)))
        srow.addWidget(self.seasonal)
        srow.addWidget(InfoButton(tr(
            "Saison-Designs erscheinen automatisch zur passenden Zeit: Kirschblüte (20.3.–30.4.), Sommer (21.6.–31.8.), "
            "Kürbisnacht (15.10.–2.11.), Frost (1.12.–6.1.) und Silvester (29.12.–2.1.) – danach wieder dein gewähltes "
            "Design. Alle gibt es auch jederzeit oben unter „Design“.")))
        srow.addStretch(1)
        fx.body.addLayout(srow)
        krow = QHBoxLayout()
        self.spooky = QCheckBox(tr("Kürbisnacht-Überraschung"))
        self.spooky.toggled.connect(lambda on: self.main.set_appearance(spooky=on))
        krow.addWidget(self.spooky)
        krow.addWidget(InfoButton(tr("Nur im Design „Kürbisnacht“: Ab und zu lugt kurz ein gruseliges Gesicht vom "
                                     "unteren Fensterrand hervor – höchstens einmal pro Stunde, nur bei offenem "
                                     "Fenster. Ein Klick darauf lässt es verschwinden.")))
        krow.addStretch(1)
        fx.body.addLayout(krow)
        self.intro = QCheckBox(tr("Logo-Animation beim Start"))
        self.intro.toggled.connect(lambda on: self.main.set_appearance(intro=on))
        fx.body.addWidget(self.intro)
        fx.body.addStretch(1)
        root.addLayout(columns(look, stack(fx, ui)))

        root.addWidget(section(tr("Programm")))

        rpc = Card(tr("Discord-Profilstatus"),
                   tr("Zeigt Raid und Welle als „Spielt …“ in deinem Discord-Profil.\n\nAnwendungs-ID: "
                      "discord.com/developers/applications → New Application (der Name erscheint im Profil) → "
                      "Application ID kopieren. Die Discord-Desktop-App muss laufen und das Teilen der Aktivität "
                      "an sein (Discord → Einstellungen → Aktivitäts-Privatsphäre)."))
        self.rpc_enabled = QCheckBox(tr("Aktuellen Raid und Fortschritt in meinem Discord-Profil anzeigen"))
        rpc.body.addWidget(self.rpc_enabled)
        self.rpc_state = label("", "muted", wrap=True)
        rpc.body.addWidget(self.rpc_state)
        rg = form_grid()
        rg.setColumnStretch(1, 1)
        rg.setColumnStretch(2, 0)
        self.rpc_id = QLineEdit()
        self.rpc_id.setPlaceholderText(tr("eigene Application ID aus dem Discord-Entwicklerportal"))
        self.rpc_link = QLineEdit()
        self.rpc_link.setPlaceholderText(tr("https://www.roblox.com/games/…"))
        rg.addWidget(label(tr("Anwendungs-ID")), 0, 0)
        rg.addWidget(self.rpc_id, 0, 1)
        rg.addWidget(label(tr("Spiel-Link (für das Bild)")), 1, 0)
        rg.addWidget(self.rpc_link, 1, 1)
        rpc.body.addLayout(rg)

        upd = Card(tr("Updates"),
                   tr("Neue Versionen kommen meist als kleines Paket (nur geänderte Dateien). Unter „Alle "
                      "Versionen“ liest du die Änderungen jeder Version und kannst bei Problemen zu einer älteren "
                      "zurückkehren – Einstellungen und Statistik bleiben erhalten."))
        upd.body.addWidget(label(tr("Installierte Version: {version}", version=__version__), "muted"))
        self.update_check = QCheckBox(tr("Automatisch nach Updates suchen (höchstens alle 6 Stunden)"))
        upd.body.addWidget(self.update_check)
        brow = QHBoxLayout()
        self.update_beta = QCheckBox(tr("Beta-Updates erhalten"))
        brow.addWidget(self.update_beta)
        brow.addWidget(InfoButton(tr("Neue Versionen kommen früher zu dir, können aber noch Fehler enthalten. "
                                     "Ausschalten und unter „Alle Versionen“ zur letzten stabilen Version "
                                     "zurückkehren geht jederzeit.")))
        brow.addStretch(1)
        upd.body.addLayout(brow)
        urow = QHBoxLayout()
        ubtn = QPushButton(tr("Jetzt nach Updates suchen"))
        ubtn.clicked.connect(lambda: self.main.check_updates(True))
        urow.addWidget(ubtn)
        vbtn = QPushButton(tr("Alle Versionen …"))
        vbtn.setToolTip(tr("Versionshinweise aller Versionen lesen oder eine ältere Version installieren"))
        vbtn.clicked.connect(self._versions)
        urow.addWidget(vbtn)
        urow.addStretch(1)
        upd.body.addLayout(urow)
        upd.body.addStretch(1)

        data = Card(tr("Daten"),
                    tr("Webhook-URL, Server-Links und IDs sind auf diesem PC mit deinem Windows-Konto "
                       "verschlüsselt. Für einen PC-Wechsel: hier exportieren (mit Passwort) und am neuen PC "
                       "importieren.\n\nDas Diagnose-Paket enthält Protokoll und Wertverlauf, aber keine "
                       "Webhook-URL und keine Links."))
        path = label(str(app_paths.data_dir()), "small", wrap=True)
        path.setToolTip(str(app_paths.data_dir()))
        data.body.addWidget(path)
        srow = QHBoxLayout()
        self.storage_label = label("", "small")
        clean_btn = QPushButton(tr("Aufräumen"))
        clean_btn.setToolTip(tr("Ältere Protokolle, Debug-Bilder und Update-Reste löschen – Statistik, Raids und "
                                "Einstellungen bleiben"))
        clean_btn.clicked.connect(self._clean_storage)
        srow.addWidget(self.storage_label)
        srow.addWidget(clean_btn)
        srow.addStretch(1)
        data.body.addLayout(srow)
        drow = QHBoxLayout()
        open_btn = QPushButton(tr("Ordner öffnen"))
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_paths.data_dir()))))
        diag_btn = QPushButton(tr("Diagnose-Paket"))
        diag_btn.setToolTip(tr("Protokoll, Wertverlauf und Einstellungen ohne Webhook und Links – für die Fehlersuche"))
        diag_btn.clicked.connect(lambda: self.main.create_diagnostics())
        wiz_btn = QPushButton(tr("Assistent"))
        wiz_btn.setToolTip(tr("Einrichtungsassistent erneut öffnen"))
        wiz_btn.clicked.connect(lambda: self.main.open_wizard())
        for btn in (open_btn, diag_btn, wiz_btn):
            drow.addWidget(btn)
        drow.addStretch(1)
        data.body.addLayout(drow)
        xrow = QHBoxLayout()
        exp_btn = QPushButton(tr("Exportieren …"))
        exp_btn.setToolTip(tr("Alle Einstellungen als passwortgeschützte Datei – für einen neuen PC"))
        exp_btn.clicked.connect(lambda: self.main.export_settings())
        imp_btn = QPushButton(tr("Importieren …"))
        imp_btn.clicked.connect(lambda: self.main.import_settings())
        safe_btn = QPushButton(tr("Abgesichert starten"))
        safe_btn.setToolTip(tr("Neustart mit Standard-Einstellungen, ohne deine zu löschen – hilft, wenn etwas "
                               "nicht mehr funktioniert. Geht auch: beim Start die Umschalttaste halten."))
        safe_btn.clicked.connect(lambda: self.main.restart_app(safe=True))
        xrow.addWidget(exp_btn)
        xrow.addWidget(imp_btn)
        xrow.addWidget(safe_btn)
        xrow.addStretch(1)
        data.body.addLayout(xrow)
        data.body.addStretch(1)
        root.addLayout(columns(stack(upd, rpc), data))
        root.addWidget(section(tr("Makro")))
        explore = Card(tr("Erkunden"),
                       tr("Das Makro übernimmt Roblox für die eingestellte Zeit und lernt das Spiel kennen: zuerst die "
                          "Knöpfe am Rand (Gilde, Pets, Achievements …) – Reiter durchklicken, scrollbare Bereiche "
                          "finden, reine Ansichts-Knöpfe testen –, dann im Teleporter neue Welten und Fenster mit "
                          "Problemen.\n\nNie gedrückt: Aktions-Knöpfe (Claim, Buy, Roll, Max …) und gefährliche "
                          "(Leave, Kick, Delete …) – um die bleibt eine Sperrzone, dort wird auch nicht gescrollt oder "
                          "gehovert; in der Gilde ist die ganze Ecke unten links gesperrt. Anti-AFK pausiert solange.\n\n"
                          "Not-Aus: Maus bewegen oder Esc."))
        eg = form_grid()
        self.explore_minutes = SpinBox()
        self.explore_minutes.setRange(1, 60)
        self.explore_minutes.setSuffix(tr(" Min"))
        eg.addWidget(label(tr("Höchstens")), 0, 0)
        eg.addWidget(self.explore_minutes, 0, 1)
        explore.body.addLayout(eg)
        self.explore_revisit = QCheckBox(tr("Fenster mit Problemen erneut öffnen (unbekannt, noch nicht gescrollt)"))
        explore.body.addWidget(self.explore_revisit)
        erow = QHBoxLayout()
        start_explore = QPushButton(tr("Jetzt erkunden …"))
        start_explore.setObjectName("primary")
        start_explore.clicked.connect(self._start_explore)
        report = QPushButton(tr("Bericht öffnen"))
        report.clicked.connect(lambda: self.main.pages[0].macro.open_report())
        forget = QPushButton(tr("Gelerntes vergessen …"))
        forget.setToolTip(tr("Vom Erkunden gelernte Fenster, Reiter und Drops löschen – die mitgelieferte Karte "
                             "bleibt"))
        forget.clicked.connect(self._forget_explore)
        check = QPushButton(tr("Funde prüfen …"))
        check.setToolTip(tr("Was das Erkunden gefunden hat, Fenster für Fenster bestätigen oder korrigieren"))
        check.clicked.connect(lambda: self.main.pages[0].macro.open_review(always=True))
        for btn in (start_explore, check, report, forget):
            erow.addWidget(btn)
        erow.addStretch(1)
        explore.body.addLayout(erow)
        explore.body.addStretch(1)
        root.addLayout(columns(explore, QWidget()))

        root.addWidget(section(tr("Discord-Bot")))
        bot = Card(tr("Discord-Bot"),
                   tr("Steuere das Programm aus Discord – mit deinem EIGENEN Bot (ein gemeinsamer Bot ginge nicht: "
                      "sein Schlüssel stünde sonst öffentlich im Programm). Der Bot läuft nur, solange das Programm "
                      "offen ist, und gehorcht nur den erlaubten Discord-IDs.\n\nEinrichten (2 Minuten): "
                      "discord.com/developers/applications → New Application → links „Bot“ → „Reset Token“ → Token "
                      "kopieren und hier eintragen, speichern. Dann „Einladungslink öffnen“ und den Bot in deinen "
                      "Server holen. Besondere Rechte (Intents) braucht er nicht.\n\nBefehle: /status, /start, "
                      "/stop, /pause, /screenshot, /raid, /makro, /antiafk, /autorejoin, /join, /pc, /hilfe."))
        self.bot_enabled = QCheckBox(tr("Discord-Bot aktiv"))
        bot.body.addWidget(self.bot_enabled)
        bg = form_grid()
        bg.setColumnStretch(1, 1)
        bg.setColumnStretch(2, 0)
        self.bot_token = QLineEdit()
        self.bot_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.bot_token.setPlaceholderText(tr("Token deines Bots (Entwicklerportal → Bot → Reset Token)"))
        self.bot_users = QLineEdit()
        self.bot_users.setPlaceholderText(tr("leer = deine Ping-ID aus „Meldungen“; mehrere mit Komma"))
        bg.addWidget(label(tr("Bot-Token")), 0, 0)
        bg.addWidget(self.bot_token, 0, 1)
        bg.addWidget(label(tr("Erlaubte Discord-IDs")), 1, 0)
        bg.addWidget(self.bot_users, 1, 1)
        bot.body.addLayout(bg)
        self.bot_power = QCheckBox(tr("/pc erlauben: PC herunterfahren oder neu starten (60 s, abbrechbar)"))
        bot.body.addWidget(self.bot_power)
        self.bot_state = label(tr("aus"), "small", wrap=True)
        bot.body.addWidget(self.bot_state)
        brow = QHBoxLayout()
        self.bot_invite = QPushButton(tr("Einladungslink öffnen"))
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
        self.events = EventsCard(main)                    # Debug: Protokoll live (an/aus)
        root.addWidget(self.events, 10)
        root.addStretch(1)
        root.addLayout(self._about_row())
        self._assign_groups(root)
        self.tab_group.buttons()[0].setChecked(True)
        self._show_group("Roblox")
        self._search_index: list = []               # (Karte, durchsuchbarer Text) – beim ersten Suchen gefüllt

    # ------------------------------------------------------------------ Roblox-Profil
    def _apply_profile(self) -> None:
        from .. import roblox_profile
        name = self.roblox_name.text().strip()
        if name and not roblox_profile.valid_name(name):
            self.profile_state.setText(tr("Kein gültiger Roblox-Name (3–20 Zeichen: Buchstaben, Ziffern, _)."))
            return
        self.main.set_roblox_name(name, self.show_profile)
        if name:
            self.profile_state.setText(tr("Wird geladen …"))

    def show_profile(self, error: str = "") -> None:
        """Vorschau und Status nach dem Laden (auch beim Start)."""
        from .. import roblox_profile
        from .widgets import round_pixmap
        info = roblox_profile.load_info() if self.main.engine.settings.roblox_username else None
        pix = round_pixmap(roblox_profile.avatar_file(), theme.px(48)) if info else None
        self.avatar_preview.setPixmap(pix) if pix else self.avatar_preview.clear()
        self.avatar_preview.setVisible(pix is not None)          # ohne Profil keine leere Lücke
        if error:
            self.profile_state.setText(error)
        elif info:
            self.profile_state.setText(tr("Verbunden: {display} (@{name})", display=info.get("display", ""),
                                          name=info.get("name", "")))
        else:
            self.profile_state.setText("")

    # ------------------------------------------------------------------ Reiter
    def _assign_groups(self, root) -> None:
        """Karten den Abschnitten zuordnen (Reihenfolge wie auf der Seite: Abschnittsüberschrift, dann ihre Karten)."""
        from PySide6.QtWidgets import QLabel
        self._groups: dict = {}
        self._holders: dict = {}                          # Abschnitt -> Zeilen-Widgets (ganz ausblenden, sonst
        current = None                                    # bleiben die Abstände leerer Zeilen stehen)
        for i in range(root.count()):
            item = root.itemAt(i)
            if item.layout() is not None and current is not None:   # Kartenreihe in ein Widget packen
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
            elif current is not None and w is not None:          # Karte oder Reihe mit mehreren Karten
                self._groups[current] += [w] if isinstance(w, Card) else w.findChildren(Card)
                self._holders[current].append(w)

    def _show_group(self, key: str) -> None:
        """Nur einen Abschnitt zeigen (weniger Scrollen); die Suche zeigt dagegen alle Treffer."""
        self._group = key
        if self.search.text().strip():
            return
        for sec, cards in self._groups.items():
            visible = sec.text() == tr(key).upper()
            sec.setVisible(False)                          # der Reiter ersetzt die Überschrift
            for card in cards:
                card.setVisible(visible)
            for holder in self._holders.get(sec, ()):
                holder.setVisible(visible)

    # ------------------------------------------------------------------ Suche
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
                parts.append(w.toolTip())                    # auch die Erklärungen hinter ⓘ
            self._search_index.append((card, Haystack(tags.sub(" ", " ".join(parts)))))

    def _filter(self, text: str) -> None:
        """Nur Karten zeigen, in denen alle Suchwörter vorkommen (Titel, Beschriftungen, ⓘ-Erklärungen) – tolerant
        gegen Umlaute, Bindestriche und kleine Tippfehler (search.py)."""
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
            for holder in holders:                         # Reihe zeigen, sobald eine ihrer Karten passt
                holder.setVisible(any(not c.isHidden() for c in self._groups[sec]
                                      if holder is c or holder.isAncestorOf(c)))
        for sec in self.findChildren(QLabel, "section"):
            sec.setVisible(not words)
        self.no_match.setVisible(bool(words) and not shown)

    # ------------------------------------------------------------------ Über (klein, ganz unten)
    def _about_row(self) -> QHBoxLayout:
        from .. import updater
        row = QHBoxLayout()
        theme.track_spacing(row, 14)
        row.addWidget(label(f"Anime Astral Monitor {__version__}", "small"))
        repo = updater.current_repo()
        links = []
        if repo:
            links.append((tr("GitHub"), f"https://github.com/{repo}"))
            links.append((tr("Fehler melden"), bug_report_url(repo)))
        third = Path(sys.executable).resolve().parent / "THIRD_PARTY.txt"
        if third.is_file():
            links.append((tr("Verwendete Komponenten"), QUrl.fromLocalFile(str(third)).toString()))
        for text, url in links:
            link = label(f"<a href='{url}'>{text}</a>", "small")
            link.setOpenExternalLinks(True)
            row.addWidget(link)
        row.addStretch(1)
        return row

    # ------------------------------------------------------------------ Server-Favoriten
    def load_servers(self, s) -> None:
        self.servers.blockSignals(True)
        self.servers.clear()
        for fav in s.server_favorites:
            active = fav["link"] == s.private_server_link
            item = QListWidgetItem(("● " if active else "    ") + fav["name"] + "   ·   "
                                   + roblox_join.explain(fav["link"]))
            item.setToolTip(tr("Markiert = wird für „Server beitreten“ und Auto-Rejoin verwendet") if active else "")
            self.servers.addItem(item)
            if active:
                self.servers.setCurrentItem(item)
        if not s.server_favorites:
            empty = QListWidgetItem(tr("Noch kein Server – mit „Neu …“ deinen Teilen-Link speichern."))
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
            self.main.set_server_favorites(favs, favs[row]["link"])      # Auswahl = markierter Server

    def _add_server(self) -> None:
        favs = self._favs()
        if len(favs) >= MAX_FAVORITES:
            QMessageBox.information(self, tr("Privater Server"), tr("Höchstens {n} Server.", n=MAX_FAVORITES))
            return
        dlg = ServerDialog(self, tr("Server hinzufügen"), taken=tuple(f["name"] for f in favs))
        if dlg.exec():
            favs.append({"name": dlg.result_name(), "link": dlg.result_link()})
            self.main.set_server_favorites(favs, dlg.result_link())

    def _edit_server(self) -> None:
        i, favs = self._selected(), self._favs()
        if i < 0:
            return
        old = favs[i]
        dlg = ServerDialog(self, tr("Server ändern"), old["name"], old["link"],
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
        if QMessageBox.question(self, tr("Server löschen"), tr("„{name}“ aus der Liste löschen?",
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
        menu.addAction(tr("Beitreten"), self._join_selected)
        menu.addAction(tr("Ändern …"), self._edit_server)
        menu.addAction(tr("Code zum Teilen kopieren"), self._share_server)
        menu.addSeparator()
        menu.addAction(tr("Löschen"), self._delete_server)
        menu.exec(self.servers.viewport().mapToGlobal(pos))

    def _share_server(self) -> None:
        from PySide6.QtWidgets import QApplication
        i = self._selected()
        if i < 0:
            return
        fav = self.main.engine.settings.server_favorites[i]
        QApplication.clipboard().setText(roblox_join.share_code(fav["name"], fav["link"]))
        self.main.show_toast(tr("Code kopiert – Freunde fügen ihn unter „Server hinzufügen“ als Link ein. Wer ihn "
                                "hat, kann beitreten."))

    def _versions(self) -> None:
        from .versions_dialog import VersionsDialog
        VersionsDialog(self.main).exec()

    # ------------------------------------------------------------------ Darstellung
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
        path, _ = QFileDialog.getOpenFileName(self, tr("Hintergrundbild wählen"), str(Path.home() / "Pictures"),
                                              tr("Bilder (*.png *.jpg *.jpeg *.webp *.bmp)"))
        if not path:
            return
        try:
            name = import_image(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Hintergrund"), tr("Das Bild konnte nicht geladen werden: {error}", error=exc))
            return
        self.main.set_appearance(background=name)
        self._sync_look(self.main.engine.settings)

    def _accent_from_image(self) -> None:
        from .backdrop import accent_from_image, stored_path
        path = stored_path(self.main.engine.settings.ui_background)
        color = accent_from_image(path) if path else None
        if not color:
            self.main.show_toast(tr("Im Bild ist keine kräftige Farbe – wähle eine Farbe von Hand"))
            return
        self.main.set_appearance(accent=color)
        self._sync_look(self.main.engine.settings)
        self.main.show_toast(tr("Akzentfarbe aus dem Bild: {color}", color=color))

    def _pick_accent(self) -> None:
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        s = self.main.engine.settings
        color = QColorDialog.getColor(QColor(s.ui_accent or theme.color("accent")), self, tr("Akzentfarbe"))
        if color.isValid():
            self.main.set_appearance(accent=color.name().upper())
        self._sync_look(s)

    def _set_zoom(self, value: int) -> None:
        self.main.set_appearance(zoom=value)
        self._sync_look(self.main.engine.settings)

    def _sync_look(self, s) -> None:
        """Bedienelemente der Darstellung auf den gespeicherten Stand setzen (ohne erneut auszulösen)."""
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
        self.accent_custom.setToolTip(s.ui_accent if s.ui_accent not in preset else tr("Eigene Farbe wählen"))
        light_ok = theme.has_mode(theme.design(), "light")      # wirksames Design (evtl. Saison)
        for btn in self.mode_group.buttons():
            mode = btn.property("mode")
            btn.setEnabled(light_ok or mode == "dark")
            btn.setChecked(mode == (s.ui_mode if light_ok else "dark"))
        self.mode_hint.setText("" if light_ok else tr("Das Design „{name}“ gibt es nur dunkel.",
                                                      name=tr(theme.design_info(s.ui_design)["name"])))
        self.mode_hint.setVisible(not light_ok)
        for w in widgets:
            w.blockSignals(False)

    def _show_preset(self) -> None:
        preset = PRESETS.get(self.perf.currentData(), PRESETS["balanced"])
        self.perf.setToolTip(tr("Wellenzähler alle {interval} s, Quests alle {quest} s.",
                                  interval=dec(f"{preset['interval']:g}"), quest=f"{preset['quest']:g}"))

    # ------------------------------------------------------------------ Speicher
    def refresh_storage(self) -> None:
        try:
            items = storage.usage()
        except OSError:
            return
        total = sum(u.size for u in items)
        self.storage_label.setText(tr("Belegt: {size}", size=storage.fmt_size(total)))
        self.storage_label.setToolTip("\n".join(f"{tr(u.label)}: {storage.fmt_size(u.size)}"
                                                for u in items if u.size))

    def _clean_storage(self) -> None:
        freed = storage.clean()
        self.refresh_storage()
        self.main.show_toast(tr("Aufgeräumt: {size} frei", size=storage.fmt_size(freed)))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_storage()

    def _bot_state_changed(self, state: str, app_id: str) -> None:
        # Vor dem ersten Verbinden: dieselbe Anwendung wie beim Discord-Profilstatus nutzen (gleiche Anwendungs-ID)
        app_id = app_id or (self.main.engine.settings.rpc_client_id or "").strip()
        self.bot_state.setText(tr("Zustand: {state}", state=state))
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
        self.main.pages[0].macro.start_explore()

    def _forget_explore(self) -> None:
        if QMessageBox.question(self, tr("Erkunden"), tr("Alles vergessen, was das Erkunden gelernt hat?")) \
                != QMessageBox.StandardButton.Yes:
            return
        from ..explorer import forget_local
        forget_local(app_paths.data_dir())
        (app_paths.data_dir() / "explore" / "deep_done.json").unlink(missing_ok=True)
        (app_paths.data_dir() / "explore" / "review.json").unlink(missing_ok=True)
        self.main.pages[0].macro.reload_map()

    def load(self, s) -> None:
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
        s.hotkey_toggle = self.hk_toggle.text().strip()
        s.hotkey_pause = self.hk_pause.text().strip()
        s.hotkey_status = self.hk_status_edit.text().strip()
        s.update_check = self.update_check.isChecked()
        s.update_beta = self.update_beta.isChecked()
        s.rpc_enabled = self.rpc_enabled.isChecked()
        s.rpc_client_id = self.rpc_id.text().strip()
        s.rpc_game_link = self.rpc_link.text().strip()

    def refresh(self) -> None:
        presence = self.main.engine.presence
        self.rpc_state.setText(("✅ " if presence.status_ok else "ℹ️ ") + presence.status_text)
