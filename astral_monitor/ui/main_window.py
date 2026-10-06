"""Hauptfenster: Seitenleiste + Seiten, Takt zur Aktualisierung der Anzeige."""
from __future__ import annotations

import copy
import logging
import queue
import sys
import threading
import time
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QLibraryInfo, QLockFile, QProcess, Qt, QTimer, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QStackedWidget, QSystemTrayIcon, QToolButton, QVBoxLayout,
                               QWidget)

from .. import app_paths, i18n, messages, roblox_join, winapi
from ..i18n import tr
from ..version import __version__
from ..engine import Engine, EngineError
from ..hotkeys import HotkeyListener
from .. import updater
from ..discord_client import DiscordSender
from ..settings import Settings, clean_favorites, is_valid_webhook
from . import theme
from .page_alerts import AlertsPage
from .page_detect import DetectPage
from .page_monitor import MonitorPage
from .page_raids import RaidsPage
from .page_settings import SettingsPage
from .page_stats import StatsPage
from .widgets import ToggleSwitch, label, scroll_page


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine
        self._ui_calls: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._status_key = None
        self.setWindowTitle(f"Anime Astral Monitor {__version__}")
        self.resize(1180, 800)
        self.setMinimumSize(760, 520)              # kleiner geht, weil die Oberfläche mitskaliert (theme.set_scale)
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.setInterval(150)         # erst nach dem Ziehen neu skalieren (flüssig)
        self._scale_timer.timeout.connect(self._apply_scale)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Kopfzeile: Programmname, Anti-AFK-Schalter mit Countdown
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        theme.track_margins(top, 16, 8, 16, 8)
        theme.track_spacing(top, 10)
        top.addWidget(label(tr("Anime Astral Monitor"), "h2"))
        top.addStretch(1)
        afk_label = label(tr("Anti-AFK"), "muted")
        afk_label.setToolTip(tr("Wechselt alle paar Minuten kurz zu Roblox, drückt einmal die Leertaste und wechselt "
                                "zurück – gegen die Trennung nach 20 Minuten. Abstand: Einstellungen → Anti-AFK."))
        self.afk_info = label("", "small")
        self.afk_switch = ToggleSwitch()
        self.afk_switch.setToolTip(afk_label.toolTip())
        self.afk_switch.setChecked(engine.settings.anti_afk_enabled)
        self.afk_switch.toggled.connect(self.set_anti_afk)
        self.join_btn = QToolButton()
        self.join_btn.setObjectName("slim")
        self.join_btn.setText(tr("Server beitreten"))
        self.join_btn.setToolTip(tr("Klick: dem markierten Server beitreten. Pfeil: anderen gespeicherten Server "
                                    "wählen (verwalten unter Einstellungen → Privater Server)."))
        self.join_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        join_menu = QMenu(self.join_btn)
        join_menu.aboutToShow.connect(lambda: self._fill_server_menu(join_menu))
        self.join_btn.setMenu(join_menu)
        self.join_btn.clicked.connect(lambda: self.join_private_server())
        top.addWidget(self.join_btn)
        top.addSpacing(theme.px(12))
        top.addWidget(self.afk_info)
        top.addWidget(afk_label)
        top.addWidget(self.afk_switch)
        top.addSpacing(theme.px(12))
        rejoin_label = label(tr("Auto-Rejoin"), "muted")
        rejoin_label.setToolTip(tr("Tritt nach Verbindungsabbruch, Kick oder Absturz automatisch wieder deinem privaten "
                                   "Server bei (Link unter Einstellungen → Privater Server). Wer Roblox selbst schließt "
                                   "oder das Spiel verlässt, wird nicht zurückgeholt."))
        self.rejoin_info = label("", "small")
        self.rejoin_switch = ToggleSwitch()
        self.rejoin_switch.setToolTip(rejoin_label.toolTip())
        self.rejoin_switch.setChecked(engine.settings.auto_rejoin_enabled)
        self.rejoin_switch.toggled.connect(self.set_auto_rejoin)
        top.addWidget(self.rejoin_info)
        top.addWidget(rejoin_label)
        top.addWidget(self.rejoin_switch)
        outer.addWidget(topbar)

        body = QWidget()
        root = QHBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        outer.addWidget(body, 1)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        theme.track_fixed_width(sidebar, 208)
        side = QVBoxLayout(sidebar)
        theme.track_margins(side, 12, 16, 12, 16)
        theme.track_spacing(side, 4)

        self.stack = QStackedWidget()
        self.pages = [MonitorPage(self), StatsPage(self), AlertsPage(self), RaidsPage(self),
                      DetectPage(self), SettingsPage(self)]
        names = [tr("Überwachung"), tr("Statistik"), tr("Meldungen"), tr("Raids"), tr("Erkennung"), tr("Einstellungen")]
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for i, (name, page) in enumerate(zip(names, self.pages)):
            btn = QPushButton(name)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            self.nav.addButton(btn, i)
            side.addWidget(btn)
            self.stack.addWidget(self._with_savebar(page) if getattr(page, "SAVES", False) else scroll_page(page))
        self.nav.button(0).setChecked(True)
        self.nav.idClicked.connect(self.stack.setCurrentIndex)
        side.addStretch(1)

        self.toast = label("", "small", wrap=True)
        side.addWidget(self.toast)
        self.status_box = QFrame()
        self.status_box.setObjectName("statusbox")
        box = QVBoxLayout(self.status_box)
        theme.track_margins(box, 12, 10, 12, 10)
        theme.track_spacing(box, 2)
        self.status_title = label(tr("Gestoppt"), "muted")
        self.status_sub = label("", "small")
        box.addWidget(self.status_title)
        box.addWidget(self.status_sub)
        side.addWidget(self.status_box)

        root.addWidget(sidebar)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        for page in self.pages:
            page.load(engine.settings)
        self._update_join_btn()

        self._hotkeys: Optional[HotkeyListener] = None
        self._hotkey_sig = None
        self._setup_hotkeys()
        self._force_close = False
        if not engine.settings.wizard_done:
            QTimer.singleShot(500, self.open_wizard)        # beim ersten Start: Einrichtungsassistent
        QTimer.singleShot(4000, updater.cleanup_downloads)               # Reste früherer Updates entfernen
        QTimer.singleShot(6000, lambda: self.check_updates(False))     # leise im Hintergrund (höchstens alle 6 Stunden)

        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        # Speicher aufräumen: nach dem Start, danach alle 10 Minuten und beim Minimieren (siehe winapi.trim_memory)
        self.trim_timer = QTimer(self)
        self.trim_timer.setInterval(10 * 60 * 1000)
        self.trim_timer.timeout.connect(winapi.trim_memory)
        self.trim_timer.start()
        QTimer.singleShot(30_000, winapi.trim_memory)
        self._quitting = False
        self._tray_hint_shown = False
        self.tray = self._setup_tray()
        show_request_file().unlink(missing_ok=True)          # Rest eines früheren Laufs

    def _with_savebar(self, page: QWidget) -> QWidget:
        """Seite mit Einstellungen: scrollt, die Speichern-Leiste bleibt unten immer sichtbar."""
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
        row.addWidget(label(tr("Änderungen gelten erst nach dem Speichern."), "small"))
        row.addStretch(1)
        save = QPushButton(tr("Speichern"))
        save.setObjectName("primary")
        theme.track_min_width(save, 140)
        save.clicked.connect(lambda: self.save_settings())
        row.addWidget(save)
        lay.addWidget(bar)
        box.widget = lambda: page                  # wie QScrollArea.widget() (Prüfhilfen)
        return box

    # --------------------------------------------------------------- Infobereich (Tray)
    def _setup_tray(self) -> Optional[QSystemTrayIcon]:
        """Symbol neben der Uhr: Fenster schließen = im Hintergrund weiterlaufen (kein Autostart)."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(self.windowIcon() if not self.windowIcon().isNull()
                               else QApplication.windowIcon(), self)
        menu = QMenu(self)
        menu.addAction(tr("Öffnen"), self.show_from_tray)
        self.tray_toggle = menu.addAction(tr("Überwachung starten"), self.toggle_monitoring)
        self.tray_pause = menu.addAction(tr("Pause"), self.toggle_pause)
        servers = menu.addMenu(tr("Server beitreten"))
        servers.aboutToShow.connect(lambda: self._fill_server_menu(servers))
        self.tray_afk = menu.addAction(tr("Anti-AFK"))
        self.tray_afk.setCheckable(True)
        self.tray_afk.toggled.connect(lambda on: self.afk_switch.setChecked(on))
        self.tray_rejoin = menu.addAction(tr("Auto-Rejoin"))
        self.tray_rejoin.setCheckable(True)
        self.tray_rejoin.toggled.connect(lambda on: self.rejoin_switch.setChecked(on))
        menu.addSeparator()
        menu.addAction(tr("Beenden"), self.quit_app)
        menu.aboutToShow.connect(self._update_tray_menu)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self.show_from_tray()
                               if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                                             QSystemTrayIcon.ActivationReason.Trigger) else None)
        tray.setToolTip(f"Anime Astral Monitor {__version__}")
        tray.show()
        return tray

    def _update_tray_menu(self) -> None:
        running = self.engine.running
        self.tray_toggle.setText(tr("Überwachung stoppen") if running else tr("Überwachung starten"))
        self.tray_pause.setEnabled(running)
        self.tray_pause.setText(tr("Fortsetzen") if self.engine.state.paused else tr("Pause"))
        self.tray_afk.blockSignals(True)
        self.tray_afk.setChecked(self.afk_switch.isChecked())
        self.tray_afk.blockSignals(False)
        self.tray_rejoin.blockSignals(True)
        self.tray_rejoin.setChecked(self.rejoin_switch.isChecked())
        self.tray_rejoin.blockSignals(False)

    # --------------------------------------------------------------- Privater Server
    def join_private_server(self) -> None:
        """Roblox direkt im markierten Server-Favoriten starten."""
        s = self.engine.settings
        if not s.private_server_link:
            self.show_from_tray()
            self.nav.button(5).click()                  # Einstellungen öffnen
            QMessageBox.information(self, tr("Privater Server"),
                                    tr("Bitte zuerst unter Einstellungen → Privater Server einen Server anlegen."))
            return
        ok, info = roblox_join.join(s.private_server_link)
        name = self.active_server_name()
        if ok and name:
            info = tr("Roblox wird gestartet und tritt „{name}“ bei …", name=name)
        self.engine._event(info, "info" if ok else "warn")
        if ok:
            self.show_toast(info)
        else:
            QMessageBox.warning(self, tr("Privater Server"), info)

    def active_server_name(self) -> str:
        s = self.engine.settings
        return next((f["name"] for f in s.server_favorites if f["link"] == s.private_server_link), "")

    def join_favorite(self, index: int) -> None:
        """Server aus dem Menü: wird zum markierten Server (auch für Auto-Rejoin) und sofort betreten."""
        favs = self.engine.settings.server_favorites
        if 0 <= index < len(favs):
            self.set_server_favorites(favs, favs[index]["link"])
            self.join_private_server()

    def set_server_favorites(self, favorites: list, active_link: str) -> None:
        """Favoriten ändern (sofort gespeichert – wie bei den Raids, ohne Speichern-Leiste)."""
        s = self.engine.settings
        s.server_favorites = clean_favorites(favorites)
        links = [f["link"] for f in s.server_favorites]
        s.private_server_link = active_link if active_link in links else (links[0] if links else "")
        try:
            s.save()
        except OSError as exc:
            QMessageBox.critical(self, tr("Speichern"), tr("Konnte nicht speichern: {error}", error=exc))
        self.pages[5].load_servers(s)
        self._update_join_btn()

    def _update_join_btn(self) -> None:
        name = self.active_server_name()
        self.join_btn.setText(tr("Beitreten: {name}", name=name) if name else tr("Server beitreten"))

    def _fill_server_menu(self, menu: QMenu) -> None:
        menu.clear()
        s = self.engine.settings
        for i, fav in enumerate(s.server_favorites):
            act = menu.addAction(fav["name"], lambda i=i: self.join_favorite(i))
            act.setCheckable(True)
            act.setChecked(fav["link"] == s.private_server_link)
        if not s.server_favorites:
            menu.addAction(tr("Noch keine Server gespeichert")).setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Server verwalten …"), self._manage_servers)

    def _manage_servers(self) -> None:
        self.show_from_tray()
        self.nav.button(5).click()

    # --------------------------------------------------------------- Raid-Auswahl
    def select_raid(self, name: str) -> None:
        """Aktuellen Raid setzen (Startseite, Raids-Seite) – sofort wirksam und gespeichert."""
        self.engine.set_current_raid(name)
        try:
            self.engine.settings.save()
        except OSError:
            pass
        self.pages[0].reload_raids()
        self.show_toast(tr("Aktueller Raid: {name}", name=name) if name else tr("Kein Raid gewählt"))

    def raids_changed(self) -> None:
        """Nach Anlegen/Umbenennen/Löschen: Auswahl und Statistik auffrischen."""
        self.pages[0].reload_raids()
        self.pages[1].mark_dirty()

    # --------------------------------------------------------------- Anti-AFK
    def set_anti_afk(self, on: bool) -> None:
        """Schalter oben / im Tray-Menü: sofort wirksam und gespeichert."""
        if self.engine.settings.anti_afk_enabled == on:
            return
        self.engine.settings.anti_afk_enabled = on
        try:
            self.engine.settings.save()
        except OSError:
            pass
        if self.afk_switch.isChecked() != on:
            self.afk_switch.setChecked(on)
        self.show_toast(tr("Anti-AFK an – alle {minutes} Min. kurz zu Roblox, Leertaste, zurück.",
                           minutes=self.engine.settings.anti_afk_minutes) if on else tr("Anti-AFK aus"))
        self._update_afk_info()

    def _update_afk_info(self) -> None:
        left = self.engine.anti_afk.seconds_left()
        text = "" if left is None else tr("nächster Sprung in {time}", time=messages.fmt_duration(left))
        if self.afk_info.text() != text:
            self.afk_info.setText(text)
        text = self.engine.rejoin.info()
        if self.rejoin_info.text() != text:
            self.rejoin_info.setText(text)

    # --------------------------------------------------------------- Auto-Rejoin
    def set_auto_rejoin(self, on: bool) -> None:
        """Schalter oben / im Tray-Menü: sofort wirksam und gespeichert."""
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
            self.show_toast(tr("Auto-Rejoin aus"))
        elif roblox_join.deep_link(s.private_server_link):
            self.show_toast(tr("Auto-Rejoin an – nach Verbindungsabbruch, Kick oder Absturz geht es zurück in deinen "
                               "privaten Server."))
        else:
            self.show_toast(tr("Auto-Rejoin an – ohne Private-Server-Link geht es in einen öffentlichen Server "
                               "(Link unter Einstellungen → Privater Server)."))

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        """Wirklich beenden (aus dem Tray-Menü)."""
        self._quitting = True
        self.show_from_tray() if self.engine.running else None     # Rückfrage braucht ein sichtbares Fenster
        self.close()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_timer.start()

    def _apply_scale(self) -> None:
        """Schrift, Abstände und feste Größen passend zur Fenstergröße (0,7–1,3 des Entwurfs 1180 × 800)."""
        if self.isMinimized():
            return
        if theme.set_scale(QApplication.instance(), theme.factor_for(self.width(), self.height())):
            self._status_key = None                 # Statusfeld neu zeichnen

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(1000, winapi.trim_memory)

    # --------------------------------------------------------------- Einstellungen
    def collect_settings(self) -> Optional[Settings]:
        s = copy.deepcopy(self.engine.settings)
        try:
            for page in self.pages:
                page.apply(s)
        except ValueError as exc:
            QMessageBox.warning(self, tr("Ungültige Eingabe"), str(exc))
            return None
        return s

    def apply_form(self) -> Optional[Settings]:
        """Formularwerte sofort übernehmen (ohne zu speichern), z. B. für Tests."""
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
            QMessageBox.warning(self, tr("Einstellungen"), error)
            return False
        self.engine.apply_settings(s)
        try:
            s.save()
        except OSError as exc:
            QMessageBox.critical(self, tr("Speichern"), tr("Konnte nicht speichern: {error}", error=exc))
            return False
        self._setup_hotkeys()
        if show_message:
            self.show_toast(tr("Gespeichert ✓"))
        if s.language != i18n.language() and show_message:
            answer = QMessageBox.question(self, tr("Sprache / Language"),
                                          tr("Die Sprache wird nach einem Neustart des Programms umgestellt. "
                                             "Jetzt neu starten?"))
            if answer == QMessageBox.StandardButton.Yes:
                self.restart_app()
        return True

    def restart_app(self) -> None:
        """Programm neu starten (z. B. nach Sprachwechsel); die neue Instanz wartet, bis diese beendet ist."""
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        QProcess.startDetached(sys.executable, [a for a in args if a != "--restart"] + ["--restart"])
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
            tr("Start/Stopp"): (s.hotkey_toggle, lambda: self.post(self.toggle_monitoring)),
            tr("Pause"): (s.hotkey_pause, lambda: self.post(self.toggle_pause)),
            tr("Status neu senden"): (s.hotkey_status, lambda: self.post(self.resend_status)),
        })
        listener.start()
        listener.ready.wait(2.0)
        self._hotkeys = listener
        page = self.pages[5]
        if listener.failed:
            page.set_hotkey_status(tr("Nicht registriert: {keys}", keys="; ".join(listener.failed)), False)
        else:
            page.set_hotkey_status(tr("Aktiv: {toggle} (Start/Stopp), {pause} (Pause), {status} (Status neu senden)",
                                      toggle=s.hotkey_toggle, pause=s.hotkey_pause, status=s.hotkey_status), True)

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
            QMessageBox.critical(self, tr("Diagnose"), tr("Das Paket konnte nicht erstellt werden:\n{error}", error=exc))
            return
        finally:
            self.unsetCursor()
        QMessageBox.information(self, tr("Diagnose-Paket erstellt"),
                                tr("Gespeichert:\n{path}\n\nDie Datei enthält Protokoll, Wertverlauf, Einstellungen "
                                   "(ohne Webhook) und einen Screenshot des Roblox-Fensters.", path=path))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def show_toast(self, text: str) -> None:
        self.toast.setText(text)
        QTimer.singleShot(3000, lambda: self.toast.setText(""))

    def post(self, call: Callable[[], None]) -> None:
        """Aus Hintergrund-Threads: Aufruf im GUI-Thread ausführen lassen."""
        self._ui_calls.put(call)

    # --------------------------------------------------------------- Steuerung
    def toggle_monitoring(self) -> None:
        if self.engine.running:
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
            QMessageBox.critical(self, tr("Start nicht möglich"), str(exc))
        finally:
            self.unsetCursor()

    def toggle_pause(self) -> None:
        self.engine.toggle_pause()

    # --------------------------------------------------------------- Discord / Status / Assistent
    def resend_status(self) -> None:
        s = self.engine.settings
        if not s.status_enabled or not is_valid_webhook(s.webhook_url):
            QMessageBox.information(self, tr("Live-Status"), tr("Die Live-Statusnachricht ist nicht aktiv. Webhook eintragen und "
                                                         "unter „Meldungen“ aktivieren."))
            return
        self.engine.resend_status()
        self.show_toast(tr("Status wird neu gesendet …"))

    def test_webhook(self, url: str, done: Callable[[bool, str], None]) -> None:
        """Sendet eine Test-Nachricht im Hintergrund; `done(ok, info)` läuft danach im GUI-Thread."""
        tmp = copy.deepcopy(self.engine.settings)
        tmp.webhook_url = url
        payload, _files = messages.build_message(tmp, "start_stop", tr("🔔 Test-Nachricht"), messages.COLOR_INFO,
                                                 [(tr("Status"), tr("Verbindung zum Webhook funktioniert."), False)])

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
                QMessageBox.information(self, tr("Updates"), tr("In dieser Version ist keine Update-Quelle hinterlegt. Die "
                                                         "automatische Prüfung gibt es in der installierten Version "
                                                         "(Download von GitHub)."))
            return
        if not manual and (not s.update_check or not updater.due(s.update_last_check)):
            return

        def work() -> None:
            try:
                info, error = updater.check_latest(repo), None
            except updater.UpdateError as exc:
                info, error = None, str(exc)
            self.post(lambda: self._update_result(info, error, manual))

        threading.Thread(target=work, daemon=True).start()

    def _update_result(self, info, error: Optional[str], manual: bool) -> None:
        if error:
            if manual:
                QMessageBox.warning(self, tr("Updates"), tr("Die Suche nach Updates ist fehlgeschlagen:\n{error}",
                                                            error=error))
            return
        self.engine.settings.update_last_check = time.time()
        try:
            self.engine.settings.save()
        except OSError:
            pass
        if info is None or not updater.is_newer(info.version):
            if manual:
                QMessageBox.information(self, tr("Updates"), tr("Du hast die neueste Version ({version}).",
                                                                version=__version__))
            return
        if not manual and info.version == self.engine.settings.update_skip:
            return
        if not updater.is_installed_build():
            if manual:
                QMessageBox.information(self, tr("Updates"), tr("Version {version} ist verfügbar:\n{url}\n\n"
                                                                "Nur die installierte Version aktualisiert sich selbst.",
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
        """Beendet das Programm sauber, damit der Installer die Dateien ersetzen kann."""
        self._force_close = True
        self.close()

    def open_wizard(self) -> None:
        from .wizard import SetupWizard
        SetupWizard(self).exec()

    def finish_wizard(self, start: bool) -> None:
        self.engine.settings.wizard_done = True
        self.save_settings(show_message=False)
        if start:
            self.toggle_monitoring()

    # --------------------------------------------------------------- Takt
    def _tray_tick(self) -> None:
        """Etwa jede Sekunde: Tooltip am Symbol aktualisieren, Anzeige-Wunsch einer zweiten Instanz erfüllen."""
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
                state = tr("Gestoppt")
            elif st.paused:
                state = tr("Pausiert")
            elif st.wave_value is not None:
                state = tr("Welle {wave}/{total}", wave=st.wave_value, total=st.wave_total)
            else:
                state = tr("Läuft")
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
                self.pages[0].add_event(data)
                refresh_stats = True               # Statistik beim nächsten Anzeigen neu laden (nur Markierung)
        for _ in range(20):
            try:
                self._ui_calls.get_nowait()()
            except queue.Empty:
                break
        if refresh_stats:
            self.pages[1].mark_dirty()
        self._tray_tick()
        if self.isMinimized() or not self.isVisible():
            self._status_key = None                 # nach dem Wiederherstellen alles neu zeichnen
            return                                  # minimiert: nichts zeichnen (spart CPU)

        st = self.engine.state
        key = "paused" if (st.running and st.paused) else ("on" if st.running else "off")
        if st.running:
            elapsed = time.monotonic() - (st.started_at or time.monotonic())
            self.status_sub.setText(tr("Laufzeit {time}", time=messages.fmt_duration(elapsed)))
        elif key != self._status_key:
            self.status_sub.setText("")
        if key != self._status_key:               # Stil nur bei Wechsel neu berechnen (spart CPU)
            self._status_key = key
            self.status_title.setText("● " + {"paused": tr("Pausiert"), "on": tr("Läuft"), "off": tr("Gestoppt")}[key])
            self.status_title.setObjectName({"paused": "warn", "on": "good", "off": "muted"}[key])
            self.status_box.setProperty("state", "off" if key == "off" else "on")
            for widget in (self.status_title, self.status_box):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

        self.pages[self.stack.currentIndex()].refresh()

    def closeEvent(self, event) -> None:
        if (self.tray is not None and self.engine.settings.close_to_tray
                and not self._quitting and not self._force_close):
            event.ignore()                          # weiterlaufen im Infobereich
            self.hide()
            QTimer.singleShot(1000, winapi.trim_memory)
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(tr("Anime Astral Monitor"),
                                      tr("Läuft im Hintergrund weiter. Rechtsklick auf das Symbol neben der Uhr → "
                                         "„Beenden“ schließt das Programm."),
                                      QSystemTrayIcon.MessageIcon.Information, 6000)
            return
        if self.engine.running and not self._force_close:
            answer = QMessageBox.question(self, tr("Beenden"), tr("Die Überwachung läuft noch. Wirklich beenden?"))
            if answer != QMessageBox.StandardButton.Yes:
                self._quitting = False
                event.ignore()
                return
        for page in self.pages:
            if hasattr(page, "save_ui"):
                page.save_ui()
        if self._hotkeys is not None:
            self._hotkeys.stop()
        self.engine.shutdown()
        if self.tray is not None:
            self.tray.hide()
        event.accept()
        QApplication.quit()                         # Programm endet (läuft sonst mit verstecktem Fenster weiter)


def show_request_file():
    """Datei, mit der eine zweite gestartete Instanz das laufende Programm bittet, sein Fenster zu zeigen."""
    return app_paths.data_dir() / "show.request"


def _install_qt_translation(app: QApplication, lang: str) -> None:
    """Qt-eigene Texte (Ja/Nein, Abbrechen …) in der gewählten Sprache; Englisch ist Qt-Standard."""
    if lang != "de":
        return
    translator = QTranslator(app)
    if translator.load("qtbase_de", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
        app._qt_translator = translator             # Referenz halten


def _install_crash_logging() -> None:
    """Unbehandelte Fehler ins Protokoll schreiben (im Fenstermodus der EXE gäbe es sonst keine Spur)."""
    log = logging.getLogger("crash")

    def handle(exc_type, exc, tb) -> None:
        log.critical("Unbehandelte Ausnahme", exc_info=(exc_type, exc, tb))
        try:
            QMessageBox.critical(None, tr("Unerwarteter Fehler"),
                                 f"{exc_type.__name__}: {exc}\n\n"
                                 + tr("Details stehen in monitor.log ({path}).", path=app_paths.log_file()))
        except Exception:
            pass

    sys.excepthook = handle
    threading.excepthook = lambda args: log.critical(
        "Ausnahme im Thread %s", getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def run() -> int:
    if sys.platform == "win32":
        try:    # eigenes Taskleisten-Symbol statt „python.exe“
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AnimeAstralMonitor")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Anime Astral Monitor")
    app.setQuitOnLastWindowClosed(False)            # Fenster zu = weiter im Infobereich
    icon = app_paths.resource_path("assets/app.ico")
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    try:
        settings = Settings.load()
    except Exception:
        settings = Settings()
    i18n.set_language(settings.language)            # vor dem Aufbau der Oberfläche
    _install_qt_translation(app, settings.language)
    theme.apply(app)

    lock = QLockFile(str(app_paths.data_dir() / "app.lock"))       # nur eine Instanz gleichzeitig
    if not lock.tryLock(10_000 if "--restart" in sys.argv else 300):   # bei Neustart: auf die alte Instanz warten
        # läuft schon (evtl. unsichtbar im Infobereich): dort das Fenster anzeigen lassen
        try:
            show_request_file().write_text("1", encoding="utf-8")
        except OSError:
            QMessageBox.information(None, tr("Bereits geöffnet"), tr("Der Anime Astral Monitor läuft bereits."))
        return 0
    try:
        engine = Engine(settings)
    except Exception as exc:
        QMessageBox.critical(None, tr("Start fehlgeschlagen"), f"{type(exc).__name__}: {exc}")
        return 1
    _install_crash_logging()
    window = MainWindow(engine)
    window.show()
    code = app.exec()
    lock.unlock()
    return code
