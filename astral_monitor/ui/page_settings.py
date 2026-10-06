"""Seite „Einstellungen": Roblox-Helfer, Überwachung, Programm."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .. import app_paths, roblox_join
from ..i18n import LANGUAGES, tr
from ..settings import PRESETS
from ..version import __version__
from . import theme
from .widgets import Card, ComboBox, DoubleSpinBox, SpinBox, columns, form_grid, label, section, short_field


class SettingsPage(QWidget):
    SAVES = True                                   # Speichern-Leiste unten (main_window)

    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 14)
        root.addWidget(label(tr("Einstellungen"), "h1"))
        root.addWidget(label(tr("Roblox-Helfer, Überwachung und Programm."), "muted"))

        # ------------------------------------------------------------------ Roblox
        root.addWidget(section(tr("Roblox")))
        ps = Card(tr("Privater Server und Auto-Rejoin"))
        prow = QHBoxLayout()
        self.ps_link = QLineEdit()
        self.ps_link.setPlaceholderText("https://www.roblox.com/share?code=…&type=Server")
        self.ps_link.textChanged.connect(lambda text: self.ps_state.setText(roblox_join.explain(text)))
        prow.addWidget(self.ps_link, 1)
        ps_btn = QPushButton(tr("Beitreten"))
        ps_btn.clicked.connect(lambda: self.main.join_private_server(self.ps_link.text()))
        prow.addWidget(ps_btn)
        ps.body.addLayout(prow)
        self.ps_state = label("", "small", wrap=True)
        ps.body.addWidget(self.ps_state)
        ps.body.addWidget(label(tr("Startet Roblox ohne Browser direkt in deinem privaten Server. Teilen-Links "
                                   "(„roblox.com/share?code=…“) und klassische Links funktionieren. Der Link bleibt nur "
                                   "auf diesem PC."), "small", wrap=True))
        ps.body.addWidget(label(tr("Auto-Rejoin (Schalter in der Kopfzeile): Nach Verbindungsabbruch, Kick oder Absturz "
                                   "tritt das Programm nach 15 s wieder bei – bis zu 5 Versuche. Wer Roblox selbst "
                                   "schließt, wird nicht zurückgeholt."), "small", wrap=True))
        ps.body.addStretch(1)

        afk = Card(tr("Anti-AFK"))
        ag = form_grid()
        self.afk_minutes = SpinBox()
        self.afk_minutes.setRange(1, 19)
        self.afk_minutes.setSuffix(tr(" Min"))
        ag.addWidget(label(tr("Springen alle")), 0, 0)
        ag.addWidget(self.afk_minutes, 0, 1)
        afk.body.addLayout(ag)
        afk.body.addWidget(label(tr("Schalter in der Kopfzeile. Holt Roblox kurz nach vorne, drückt die Leertaste und "
                                    "wechselt zurück. Während du tippst oder klickst, wartet es. Roblox darf nicht "
                                    "minimiert sein."), "small", wrap=True))
        afk.body.addWidget(label(tr("Hinweis: Makros sind laut Roblox-Regeln nicht erlaubt – Nutzung auf eigene "
                                    "Verantwortung."), "small", wrap=True))
        afk.body.addStretch(1)
        root.addLayout(columns(ps, afk))

        # ------------------------------------------------------------------ Überwachung
        root.addWidget(section(tr("Überwachung")))
        perf = Card(tr("Leistung"))
        pg = form_grid()
        self.perf = ComboBox()
        for key, preset in PRESETS.items():
            self.perf.addItem(tr(preset["label"]), key)
        self.perf.currentIndexChanged.connect(self._show_preset)
        pg.addWidget(label(tr("Prüfrate")), 0, 0)
        pg.addWidget(self.perf, 0, 1)
        perf.body.addLayout(pg)
        self.perf_info = label("", "small", wrap=True)
        perf.body.addWidget(self.perf_info)
        self.low_priority = QCheckBox(tr("Niedrige Prozesspriorität (das Spiel hat Vorrang)"))
        perf.body.addWidget(self.low_priority)
        perf.body.addWidget(label(tr("„Ausgewogen“ passt für die meisten. Kurz vor dem Raid-Ende wird schneller "
                                     "geprüft, damit 99/100 sicher erkannt wird."), "small", wrap=True))
        perf.body.addStretch(1)

        guard = Card(tr("Wächter"))
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
        guard.body.addWidget(label(tr("Abstürze erkennt der Wächter am Roblox-Prozess, Disconnects und Kicks am "
                                      "Roblox-Protokoll – ohne zusätzliche Bilderkennung. Was gesendet wird, stellst du "
                                      "unter „Meldungen“ ein."), "small", wrap=True))
        guard.body.addStretch(1)
        root.addLayout(columns(perf, guard))

        # ------------------------------------------------------------------ Programm
        root.addWidget(section(tr("Programm")))
        ui = Card(tr("Oberfläche"))
        ug = form_grid()
        self.language = ComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        ug.addWidget(label(tr("Sprache / Language")), 0, 0)
        ug.addWidget(self.language, 0, 1)
        ui.body.addLayout(ug)
        self.close_to_tray = QCheckBox(tr("Beim Schließen im Infobereich weiterlaufen"))
        ui.body.addWidget(self.close_to_tray)
        ui.body.addWidget(label(tr("Rechtsklick auf das Symbol neben der Uhr: Öffnen, Start/Stopp, Pause, Server "
                                   "beitreten, Anti-AFK, Auto-Rejoin, Beenden. Ein Sprachwechsel gilt nach einem "
                                   "Neustart."), "small", wrap=True))
        ui.body.addStretch(1)

        keys = Card(tr("Hotkeys"))
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
        keys.body.addWidget(label(tr("Global, auch im Spiel. Format: Ctrl+Alt+S, Shift+F9 … – einzelne F-Tasten "
                                     "vermeiden, die Roblox selbst nutzt."), "small", wrap=True))
        keys.body.addStretch(1)
        root.addLayout(columns(ui, keys))

        rpc = Card(tr("Discord-Profilstatus"))
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
        rpc.body.addWidget(label(tr("Anwendungs-ID: discord.com/developers/applications → New Application (der Name "
                                    "erscheint im Profil als „Spielt …“) → Application ID kopieren. Die Discord-Desktop-"
                                    "App muss laufen und das Teilen der Aktivität an sein (Discord → Einstellungen → "
                                    "Aktivitäts-Privatsphäre)."), "small", wrap=True))
        root.addWidget(rpc)

        upd = Card(tr("Updates"))
        upd.body.addWidget(label(tr("Installierte Version: {version}", version=__version__), "muted"))
        self.update_check = QCheckBox(tr("Automatisch nach Updates suchen (höchstens alle 6 Stunden)"))
        upd.body.addWidget(self.update_check)
        urow = QHBoxLayout()
        ubtn = QPushButton(tr("Jetzt nach Updates suchen"))
        ubtn.clicked.connect(lambda: self.main.check_updates(True))
        urow.addWidget(ubtn)
        urow.addStretch(1)
        upd.body.addLayout(urow)
        upd.body.addStretch(1)

        data = Card(tr("Daten"))
        path = label(str(app_paths.data_dir()), "small", wrap=True)
        path.setToolTip(str(app_paths.data_dir()))
        data.body.addWidget(path)
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
        data.body.addWidget(label(tr("settings.json enthält deine Webhook-URL unverschlüsselt – nicht weitergeben."),
                                  "small", wrap=True))
        data.body.addStretch(1)
        root.addLayout(columns(upd, data))
        root.addStretch(1)

    def _show_preset(self) -> None:
        preset = PRESETS.get(self.perf.currentData(), PRESETS["balanced"])
        self.perf_info.setText(tr("Ruhig alle {idle} s, kurz vor Raid-Ende alle {hot} s, Quests alle {quest} s.",
                                  idle=f"{preset['idle']:g}", hot=f"{preset['hot']:g}", quest=f"{preset['quest']:g}"))

    def load(self, s) -> None:
        self.language.setCurrentIndex(max(0, self.language.findData(s.language)))
        self.close_to_tray.setChecked(s.close_to_tray)
        self.afk_minutes.setValue(s.anti_afk_minutes)
        self.ps_link.setText(s.private_server_link)
        self.ps_state.setText(roblox_join.explain(s.private_server_link))
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
        self.rpc_enabled.setChecked(s.rpc_enabled)
        self.rpc_id.setText(s.rpc_client_id)
        self.rpc_link.setText(s.rpc_game_link)

    def set_hotkey_status(self, text: str, ok: bool) -> None:
        self.hk_status.setText(text)
        self.hk_status.setObjectName("good" if ok else "bad")
        self.hk_status.style().unpolish(self.hk_status)
        self.hk_status.style().polish(self.hk_status)

    def apply(self, s) -> None:
        s.language = self.language.currentData() or "de"
        s.close_to_tray = self.close_to_tray.isChecked()
        s.anti_afk_minutes = self.afk_minutes.value()
        s.private_server_link = self.ps_link.text().strip()
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
        s.rpc_enabled = self.rpc_enabled.isChecked()
        s.rpc_client_id = self.rpc_id.text().strip()
        s.rpc_game_link = self.rpc_link.text().strip()

    def refresh(self) -> None:
        presence = self.main.engine.presence
        self.rpc_state.setText(("✅ " if presence.status_ok else "ℹ️ ") + presence.status_text)
