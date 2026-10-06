"""Seite „Einstellungen": Leistung, Zeiten, Startwert."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import app_paths
from ..i18n import LANGUAGES, tr
from . import theme
from ..version import __version__
from ..settings import PRESETS
from .widgets import SpinBox, DoubleSpinBox, ComboBox, Card, label


class SettingsPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        outer = QVBoxLayout(self)
        theme.track_margins(outer, 28, 24, 28, 24)
        theme.track_spacing(outer, 12)
        outer.addWidget(label(tr("Einstellungen"), "h1"))
        outer.addWidget(label(tr("Leistung, Wächter, Hotkeys und Daten."), "muted"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        root = QVBoxLayout(inner)
        theme.track_margins(root, 0, 0, 8, 0)
        theme.track_spacing(root, 14)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        ui = Card(tr("Oberfläche"))
        lrow = QHBoxLayout()
        lrow.addWidget(label(tr("Sprache / Language")))
        self.language = ComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        lrow.addWidget(self.language)
        lrow.addStretch(1)
        ui.body.addLayout(lrow)
        self.close_to_tray = QCheckBox(tr("Beim Schließen im Infobereich (neben der Uhr) weiterlaufen"))
        ui.body.addWidget(self.close_to_tray)
        ui.body.addWidget(label(tr("Rechtsklick auf das Symbol neben der Uhr: Öffnen, Starten/Stoppen, Pause, Beenden. "
                                   "Ein Sprachwechsel gilt nach einem Neustart des Programms."), "small", wrap=True))
        root.addWidget(ui)

        perf = Card(tr("Leistung"))
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)
        self.perf = ComboBox()
        for key, preset in PRESETS.items():
            self.perf.addItem(tr("{name}  ·  ruhig {idle} s, kurz vor Raid-Ende {hot} s, Quests alle {quest} s",
                                 name=tr(preset["label"]), idle=f"{preset['idle']:g}", hot=f"{preset['hot']:g}",
                                 quest=f"{preset['quest']:g}"), key)
        grid.addWidget(label(tr("Prüfrate")), 0, 0)
        grid.addWidget(self.perf, 0, 1)
        perf.body.addLayout(grid)
        self.low_priority = QCheckBox(tr("Niedrige Prozesspriorität (das Spiel hat immer Vorrang)"))
        perf.body.addWidget(self.low_priority)
        perf.body.addWidget(label(tr("„Ausgewogen“ passt für die meisten. Der Takt wird nur kurz vor dem Raid-Ende "
                                  "erhöht, damit 99/100 sicher erwischt wird."), "small", wrap=True))
        root.addWidget(perf)

        misc = Card(tr("Zeiten und Zähler"))
        grid2 = QGridLayout()
        grid2.setColumnStretch(1, 1)
        grid2.setVerticalSpacing(8)
        self.uptime = SpinBox()
        self.uptime.setRange(1, 1440)
        self.uptime.setSuffix(tr(" Min"))
        self.offset = SpinBox()
        self.offset.setRange(0, 10_000_000)
        grid2.addWidget(label(tr("Uptime-Meldung alle")), 0, 0)
        grid2.addWidget(self.uptime, 0, 1)
        grid2.addWidget(label(tr("Startwert „Raids gesamt“")), 1, 0)
        grid2.addWidget(self.offset, 1, 1)
        misc.body.addLayout(grid2)
        misc.body.addWidget(label(tr("Der Startwert wird zu den gespeicherten Raids addiert "
                                  "(z. B. dein bisheriger Zählerstand aus dem alten Programm)."), "small", wrap=True))
        root.addWidget(misc)

        guard = Card(tr("Wächter"))
        self.guard_enabled = QCheckBox(tr("Wächter aktiv (Alarme bei Absturz, Disconnect, Stillstand, Speicher)"))
        guard.body.addWidget(self.guard_enabled)
        gg = QGridLayout()
        gg.setColumnStretch(1, 1)
        gg.setVerticalSpacing(8)
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
        gg.addWidget(label(tr("Stillstand: Zähler unverändert für")), 0, 0)
        gg.addWidget(self.stall, 0, 1)
        gg.addWidget(label(tr("Alarm, wenn kein Raid endet für")), 1, 0)
        gg.addWidget(self.no_raid, 1, 1)
        gg.addWidget(label(tr("Speicher-Warnung ab (Roblox)")), 2, 0)
        gg.addWidget(self.ram, 2, 1)
        guard.body.addLayout(gg)
        self.disconnect = QCheckBox(tr("Disconnect-Meldung im Spiel erkennen (Texterkennung in der Fenstermitte)"))
        guard.body.addWidget(self.disconnect)
        guard.body.addWidget(label(tr("Der Abstürze-Alarm nutzt den Roblox-Prozess. Welche Alarme gesendet werden und ob "
                                   "es einen Ping gibt, stellst du unter „Meldungen“ ein."), "small", wrap=True))
        root.addWidget(guard)

        afk = Card(tr("Anti-AFK"))
        arow = QHBoxLayout()
        arow.addWidget(label(tr("Springen alle")))
        self.afk_minutes = SpinBox()
        self.afk_minutes.setRange(1, 19)
        self.afk_minutes.setSuffix(tr(" Min"))
        arow.addWidget(self.afk_minutes)
        arow.addStretch(1)
        afk.body.addLayout(arow)
        afk.body.addWidget(label(tr("Ein- und ausschalten oben rechts in der Kopfzeile (oder im Tray-Menü). Das Programm "
                                    "holt Roblox kurz nach vorne, drückt einmal die Leertaste und wechselt zu deinem "
                                    "Fenster zurück – Roblox nimmt Tasten nur im Vordergrund an. Tippst oder klickst du "
                                    "gerade, wartet es, bis du 2 Sekunden nichts eingibst. Roblox darf nicht minimiert "
                                    "sein. Hinweis: Makros sind laut Roblox-Regeln nicht erlaubt; Nutzung auf eigene "
                                    "Verantwortung."), "small", wrap=True))
        root.addWidget(afk)

        keys = Card(tr("Hotkeys (global, auch während des Spiels)"))
        kg = QGridLayout()
        kg.setColumnStretch(1, 1)
        kg.setVerticalSpacing(8)
        self.hk_toggle = QLineEdit()
        self.hk_pause = QLineEdit()
        kg.addWidget(label(tr("Start / Stopp")), 0, 0)
        kg.addWidget(self.hk_toggle, 0, 1)
        kg.addWidget(label(tr("Pause / Fortsetzen")), 1, 0)
        kg.addWidget(self.hk_pause, 1, 1)
        self.hk_status_edit = QLineEdit()
        kg.addWidget(label(tr("Status neu senden (nach unten)")), 2, 0)
        kg.addWidget(self.hk_status_edit, 2, 1)
        keys.body.addLayout(kg)
        self.hk_status = label("", "small", wrap=True)
        keys.body.addWidget(self.hk_status)
        keys.body.addWidget(label(tr("Format: Ctrl+Alt+S, Shift+F9 … (Modifier: Ctrl, Alt, Shift, Win). Vermeide einzelne "
                                  "F-Tasten, die Roblox selbst nutzt."), "small", wrap=True))
        root.addWidget(keys)

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
        root.addWidget(upd)

        rpc = Card(tr("Discord-Profilstatus"))
        self.rpc_enabled = QCheckBox(tr("Aktuellen Raid und Fortschritt in meinem Discord-Profil anzeigen"))
        rpc.body.addWidget(self.rpc_enabled)
        self.rpc_state = label("", "muted", wrap=True)
        rpc.body.addWidget(self.rpc_state)
        grow = QHBoxLayout()
        grow.addWidget(label(tr("Spiel-Link (für das Bild)")))
        self.rpc_link = QLineEdit()
        self.rpc_link.setPlaceholderText(tr("https://www.roblox.com/games/…"))
        grow.addWidget(self.rpc_link, 1)
        rpc.body.addLayout(grow)
        irow = QHBoxLayout()
        irow.addWidget(label(tr("Anwendungs-ID")))
        self.rpc_id = QLineEdit()
        self.rpc_id.setPlaceholderText(tr("eigene Application ID aus dem Discord-Entwicklerportal"))
        irow.addWidget(self.rpc_id, 1)
        rpc.body.addLayout(irow)
        rpc.body.addWidget(label(tr("Anwendungs-ID: discord.com/developers/applications → New Application (der Name erscheint "
                                 "im Profil als „Spielt …“) → Application ID kopieren. Kein Bot und keine Server-Einladung "
                                 "nötig. Die Discord-Desktop-App muss auf dem PC laufen, und unter Discord → Einstellungen → "
                                 "Aktivitäts-Privatsphäre muss das Teilen der Aktivität an sein. Als Bild erscheint das "
                                 "Thumbnail des Spiels; der Status wird höchstens alle 15 Sekunden aktualisiert."),
                                 "small", wrap=True))
        root.addWidget(rpc)

        data = Card(tr("Daten"))
        data.body.addWidget(label(str(app_paths.data_dir()), "small", wrap=True))
        row = QHBoxLayout()
        open_btn = QPushButton(tr("Datenordner öffnen"))
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_paths.data_dir()))))
        row.addWidget(open_btn)
        wiz_btn = QPushButton(tr("Einrichtungsassistent"))
        wiz_btn.clicked.connect(lambda: self.main.open_wizard())
        row.addWidget(wiz_btn)
        diag_btn = QPushButton(tr("Diagnose-Paket erstellen"))
        diag_btn.clicked.connect(lambda: self.main.create_diagnostics())
        row.addWidget(diag_btn)
        row.addStretch(1)
        data.body.addLayout(row)
        data.body.addWidget(label(tr("Einstellungen (inkl. Webhook-URL) liegen unverschlüsselt in settings.json. "
                                  "Gib diese Datei nicht weiter. Das Diagnose-Paket enthält die Webhook-URL nicht."),
                                  "small", wrap=True))
        root.addWidget(data)

        save = QPushButton(tr("Speichern"))
        save.setObjectName("primary")
        save.clicked.connect(lambda: self.main.save_settings())
        root.addStretch(1)
        row2 = QHBoxLayout()
        row2.addWidget(label(tr("Version {version}", version=__version__), "small"))
        row2.addStretch(1)
        row2.addWidget(save)
        outer.addLayout(row2)

    def load(self, s) -> None:
        self.language.setCurrentIndex(max(0, self.language.findData(s.language)))
        self.close_to_tray.setChecked(s.close_to_tray)
        self.afk_minutes.setValue(s.anti_afk_minutes)
        self.perf.setCurrentIndex(max(0, self.perf.findData(s.performance)))
        self.low_priority.setChecked(s.low_priority)
        self.uptime.setValue(s.uptime_minutes)
        self.offset.setValue(s.total_offset)
        self.guard_enabled.setChecked(s.guard_enabled)
        self.stall.setValue(s.stall_minutes)
        self.no_raid.setValue(s.no_raid_minutes)
        self.ram.setValue(s.ram_alert_gb)
        self.disconnect.setChecked(s.disconnect_check)
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
        s.performance = self.perf.currentData()
        s.low_priority = self.low_priority.isChecked()
        s.uptime_minutes = self.uptime.value()
        s.total_offset = self.offset.value()
        s.guard_enabled = self.guard_enabled.isChecked()
        s.stall_minutes = self.stall.value()
        s.no_raid_minutes = self.no_raid.value()
        s.ram_alert_gb = self.ram.value()
        s.disconnect_check = self.disconnect.isChecked()
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
