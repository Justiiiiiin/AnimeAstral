"""Hauptfenster: Seitenleiste + Seiten, Takt zur Aktualisierung der Anzeige."""
from __future__ import annotations

import copy
import logging
import queue
import sys
import threading
import time
from typing import Callable, Optional

from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import app_paths, messages
from ..version import __version__
from ..engine import Engine, EngineError
from ..hotkeys import HotkeyListener
from .. import updater
from ..discord_client import DiscordSender
from ..settings import Settings, is_valid_webhook
from . import theme
from .page_alerts import AlertsPage
from .page_detect import DetectPage
from .page_monitor import MonitorPage
from .page_raids import RaidsPage
from .page_settings import SettingsPage
from .page_stats import StatsPage
from .widgets import label, scroll_page


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine
        self._ui_calls: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._status_key = None
        self.setWindowTitle(f"Anime Astral Monitor {__version__}")
        self.resize(1180, 800)
        self.setMinimumSize(980, 680)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(208)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 22, 12, 16)
        side.setSpacing(4)
        side.addWidget(label("Astral Monitor", "h2"))
        side.addSpacing(14)

        self.stack = QStackedWidget()
        self.pages = [MonitorPage(self), StatsPage(self), AlertsPage(self), RaidsPage(self),
                      DetectPage(self), SettingsPage(self)]
        names = ["Überwachung", "Statistik", "Meldungen", "Raids", "Erkennung", "Einstellungen"]
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for i, (name, page) in enumerate(zip(names, self.pages)):
            btn = QPushButton(name)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            self.nav.addButton(btn, i)
            side.addWidget(btn)
            self.stack.addWidget(scroll_page(page))
        self.nav.button(0).setChecked(True)
        self.nav.idClicked.connect(self.stack.setCurrentIndex)
        side.addStretch(1)

        self.toast = label("", "small", wrap=True)
        side.addWidget(self.toast)
        self.status_box = QFrame()
        self.status_box.setObjectName("statusbox")
        box = QVBoxLayout(self.status_box)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(2)
        self.status_title = label("Gestoppt", "muted")
        self.status_sub = label("", "small")
        box.addWidget(self.status_title)
        box.addWidget(self.status_sub)
        side.addWidget(self.status_box)

        root.addWidget(sidebar)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        for page in self.pages:
            page.load(engine.settings)

        self._hotkeys: Optional[HotkeyListener] = None
        self._hotkey_sig = None
        self._setup_hotkeys()
        self._force_close = False
        if not engine.settings.wizard_done:
            QTimer.singleShot(500, self.open_wizard)        # beim ersten Start: Einrichtungsassistent
        QTimer.singleShot(6000, lambda: self.check_updates(False))     # leise im Hintergrund (höchstens alle 6 Stunden)

        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # --------------------------------------------------------------- Einstellungen
    def collect_settings(self) -> Optional[Settings]:
        s = copy.deepcopy(self.engine.settings)
        try:
            for page in self.pages:
                page.apply(s)
        except ValueError as exc:
            QMessageBox.warning(self, "Ungültige Eingabe", str(exc))
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
            QMessageBox.warning(self, "Einstellungen", error)
            return False
        self.engine.apply_settings(s)
        try:
            s.save()
        except OSError as exc:
            QMessageBox.critical(self, "Speichern", f"Konnte nicht speichern: {exc}")
            return False
        self._setup_hotkeys()
        if show_message:
            self.show_toast("Gespeichert ✓")
        return True

    def _setup_hotkeys(self) -> None:
        s = self.engine.settings
        signature = (s.hotkey_toggle, s.hotkey_pause, s.hotkey_status)
        if signature == self._hotkey_sig:
            return
        self._hotkey_sig = signature
        if self._hotkeys is not None:
            self._hotkeys.stop()
        listener = HotkeyListener({
            "Start/Stopp": (s.hotkey_toggle, lambda: self.post(self.toggle_monitoring)),
            "Pause": (s.hotkey_pause, lambda: self.post(self.toggle_pause)),
            "Status neu senden": (s.hotkey_status, lambda: self.post(self.resend_status)),
        })
        listener.start()
        listener.ready.wait(2.0)
        self._hotkeys = listener
        page = self.pages[5]
        if listener.failed:
            page.set_hotkey_status("Nicht registriert: " + "; ".join(listener.failed), False)
        else:
            page.set_hotkey_status(f"Aktiv: {s.hotkey_toggle} (Start/Stopp), {s.hotkey_pause} (Pause), "
                                   f"{s.hotkey_status} (Status neu senden)", True)

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
            QMessageBox.critical(self, "Diagnose", f"Das Paket konnte nicht erstellt werden:\n{exc}")
            return
        finally:
            self.unsetCursor()
        QMessageBox.information(self, "Diagnose-Paket erstellt",
                                f"Gespeichert:\n{path}\n\nDie Datei enthält Protokoll, Wertverlauf, Einstellungen "
                                "(ohne Webhook) und einen Screenshot des Roblox-Fensters.")
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
            QMessageBox.critical(self, "Start nicht möglich", str(exc))
        finally:
            self.unsetCursor()

    def toggle_pause(self) -> None:
        self.engine.toggle_pause()

    # --------------------------------------------------------------- Discord / Status / Assistent
    def resend_status(self) -> None:
        s = self.engine.settings
        if not s.status_enabled or not is_valid_webhook(s.webhook_url):
            QMessageBox.information(self, "Live-Status", "Die Live-Statusnachricht ist nicht aktiv. Webhook eintragen und "
                                                         "unter „Meldungen“ aktivieren.")
            return
        self.engine.resend_status()
        self.show_toast("Status wird neu gesendet …")

    def test_webhook(self, url: str, done: Callable[[bool, str], None]) -> None:
        """Sendet eine Test-Nachricht im Hintergrund; `done(ok, info)` läuft danach im GUI-Thread."""
        tmp = copy.deepcopy(self.engine.settings)
        tmp.webhook_url = url
        payload, _files = messages.build_message(tmp, "start_stop", "🔔 Test-Nachricht", messages.COLOR_INFO,
                                                 [("Status", "Verbindung zum Webhook funktioniert.", False)])

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
                QMessageBox.information(self, "Updates", "In dieser Version ist keine Update-Quelle hinterlegt. Die "
                                                         "automatische Prüfung gibt es in der installierten Version "
                                                         "(Download von GitHub).")
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
                QMessageBox.warning(self, "Updates", f"Die Suche nach Updates ist fehlgeschlagen:\n{error}")
            return
        self.engine.settings.update_last_check = time.time()
        try:
            self.engine.settings.save()
        except OSError:
            pass
        if info is None or not updater.is_newer(info.version):
            if manual:
                QMessageBox.information(self, "Updates", f"Du hast die neueste Version ({__version__}).")
            return
        if not manual and info.version == self.engine.settings.update_skip:
            return
        if not updater.is_installed_build():
            if manual:
                QMessageBox.information(self, "Updates", f"Version {info.version} ist verfügbar:\n{info.page_url}\n\n"
                                                         "Nur die installierte Version aktualisiert sich selbst.")
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
    def _tick(self) -> None:
        refresh_stats = False
        for _ in range(200):
            try:
                kind, data = self.engine.events.get_nowait()
            except queue.Empty:
                break
            if kind == "event":
                self.pages[0].add_event(data)
                if "Raid" in data["text"]:
                    refresh_stats = True
        for _ in range(20):
            try:
                self._ui_calls.get_nowait()()
            except queue.Empty:
                break
        if refresh_stats:
            self.pages[1].mark_dirty()

        st = self.engine.state
        key = "paused" if (st.running and st.paused) else ("on" if st.running else "off")
        if st.running:
            elapsed = time.monotonic() - (st.started_at or time.monotonic())
            self.status_sub.setText(f"Laufzeit {messages.fmt_duration(elapsed)}")
        elif key != self._status_key:
            self.status_sub.setText("")
        if key != self._status_key:               # Stil nur bei Wechsel neu berechnen (spart CPU)
            self._status_key = key
            self.status_title.setText({"paused": "● Pausiert", "on": "● Läuft", "off": "● Gestoppt"}[key])
            self.status_title.setObjectName({"paused": "warn", "on": "good", "off": "muted"}[key])
            self.status_box.setProperty("state", "off" if key == "off" else "on")
            for widget in (self.status_title, self.status_box):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

        self.pages[self.stack.currentIndex()].refresh()

    def closeEvent(self, event) -> None:
        if self.engine.running and not self._force_close:
            answer = QMessageBox.question(self, "Beenden", "Die Überwachung läuft noch. Wirklich beenden?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        for page in self.pages:
            if hasattr(page, "save_ui"):
                page.save_ui()
        if self._hotkeys is not None:
            self._hotkeys.stop()
        self.engine.shutdown()
        event.accept()


def _install_crash_logging() -> None:
    """Unbehandelte Fehler ins Protokoll schreiben (im Fenstermodus der EXE gäbe es sonst keine Spur)."""
    log = logging.getLogger("crash")

    def handle(exc_type, exc, tb) -> None:
        log.critical("Unbehandelte Ausnahme", exc_info=(exc_type, exc, tb))
        try:
            QMessageBox.critical(None, "Unerwarteter Fehler",
                                 f"{exc_type.__name__}: {exc}\n\nDetails stehen in monitor.log "
                                 f"({app_paths.log_file()}).")
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
    icon = app_paths.resource_path("assets/app.ico")
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    theme.apply(app)

    lock = QLockFile(str(app_paths.data_dir() / "app.lock"))       # nur eine Instanz gleichzeitig
    if not lock.tryLock(300):
        QMessageBox.information(None, "Bereits geöffnet", "Der Anime Astral Monitor läuft bereits.")
        return 0
    try:
        engine = Engine(Settings.load())
    except Exception as exc:
        QMessageBox.critical(None, "Start fehlgeschlagen", f"{type(exc).__name__}: {exc}")
        return 1
    _install_crash_logging()
    window = MainWindow(engine)
    window.show()
    code = app.exec()
    lock.unlock()
    return code
