"""Dialog „Update verfügbar“: Hinweise anzeigen, laden, Prüfsumme prüfen, Installer starten."""
from __future__ import annotations

import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QMessageBox, QProgressBar, QPushButton, QTextBrowser,
                               QVBoxLayout)

from .. import updater
from ..i18n import tr
from . import theme
from ..version import __version__
from .widgets import label


class UpdateDialog(QDialog):
    def __init__(self, main, info: updater.ReleaseInfo, full_install: bool = False) -> None:
        """full_install: kompletten Installer nutzen (Downgrade/Neuinstallation – Update-Pakete gehen nur vorwärts)."""
        super().__init__(main)
        self.main, self.info = main, info
        newer = updater.is_newer(info.version)
        self.setWindowTitle(tr("Update verfügbar") if newer else tr("Version installieren"))
        self.setModal(True)
        self.resize(560, 460)
        self._state = {"done": 0, "total": 0, "error": None, "path": None, "finished": False}
        self._cancel = False

        lay = QVBoxLayout(self)
        theme.track_margins(lay, 28, 24, 28, 20)
        theme.track_spacing(lay, 12)
        lay.addWidget(label(tr("Version {version} ist verfügbar", version=info.version) if newer
                            else tr("Version {version} installieren", version=info.version), "h1"))
        lay.addWidget(label(tr("Du hast Version {version}.", version=__version__), "muted"))
        notes = QTextBrowser()                  # GitHub-Versionshinweise sind Markdown
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.notes or tr("Keine Versionshinweise angegeben."))
        lay.addWidget(notes, 1)
        self.warn = label(tr("Die laufende Überwachung wird für das Update beendet; danach startet das Programm neu.")
                          if main.engine.running else tr("Das Programm startet nach dem Update automatisch neu."), "muted", wrap=True)
        lay.addWidget(self.warn)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = label("", "small")
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.btn_skip = QPushButton(tr("Diese Version überspringen"))
        self.btn_skip.clicked.connect(self._skip)
        self.btn_skip.setVisible(newer and not full_install)
        btn_all = QPushButton(tr("Alle Versionen …"))
        btn_all.setToolTip(tr("Versionshinweise aller Versionen lesen oder eine ältere Version installieren"))
        btn_all.clicked.connect(self._all_versions)
        self.btn_later = QPushButton(tr("Später"))
        self.btn_later.clicked.connect(self.reject)
        self.btn_go = QPushButton(tr("Jetzt aktualisieren") if newer else tr("Installieren"))
        self.btn_go.setObjectName("primary")
        self.btn_go.clicked.connect(self._start)
        row.addWidget(self.btn_skip)
        row.addWidget(btn_all)
        row.addStretch(1)
        row.addWidget(self.btn_later)
        row.addWidget(self.btn_go)
        lay.addLayout(row)

        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._poll)

        # Passt das kleine Update-Paket (nur geänderte Dateien)? Prüfung im Hintergrund, dauert meist < 1 s.
        self._plan = None
        self._plan_state = {"done": False, "plan": None}
        self.btn_go.setEnabled(False)
        self.status.setText(tr("Prüfe Download-Größe …"))

        def plan_work() -> None:
            try:
                self._plan_state["plan"] = None if full_install else updater.prepare_patch(info)
            except Exception:
                self._plan_state["plan"] = None
            self._plan_state["done"] = True

        threading.Thread(target=plan_work, daemon=True).start()
        self._plan_timer = QTimer(self)
        self._plan_timer.setInterval(100)
        self._plan_timer.timeout.connect(self._plan_ready)
        self._plan_timer.start()

    def _plan_ready(self) -> None:
        if not self._plan_state["done"]:
            return
        self._plan_timer.stop()
        self._plan = self._plan_state["plan"]
        if self._plan is not None:
            self.status.setText(tr("Download: {mb} MB (nur {count} geänderte Dateien)",
                                   mb=f"{self.info.patch_size / 1048576:.1f}", count=len(self._plan.changed)))
        else:
            self.status.setText(tr("Download: {mb} MB (kompletter Installer)", mb=f"{self.info.size / 1048576:.0f}"))
        self.btn_go.setEnabled(True)

    def _all_versions(self) -> None:
        from .versions_dialog import VersionsDialog
        self.reject()
        VersionsDialog(self.main).exec()

    def _skip(self) -> None:
        self.main.skip_version(self.info.version)
        self.reject()

    def _start(self) -> None:
        for btn in (self.btn_skip, self.btn_later):
            btn.setEnabled(False)
        self.btn_go.setText(tr("Abbrechen"))
        self.btn_go.clicked.disconnect()
        self.btn_go.clicked.connect(self._abort)
        self.bar.setVisible(True)
        self.status.setText(tr("Lade herunter …"))
        self.timer.start()

        def work() -> None:
            try:
                self._state["path"] = updater.download(
                    self.info, lambda d, t: self._state.update(done=d, total=t), lambda: self._cancel,
                    patch=self._plan is not None)
            except Exception as exc:                    # UpdateError und alles Unerwartete
                self._state["error"] = str(exc) or exc.__class__.__name__
            self._state["finished"] = True

        threading.Thread(target=work, daemon=True).start()

    def _abort(self) -> None:
        self._cancel = True
        self.btn_go.setEnabled(False)
        self.status.setText(tr("Wird abgebrochen …"))

    def _poll(self) -> None:
        total, done = self._state["total"], self._state["done"]
        if total:
            self.bar.setValue(int(done * 100 / total))
            self.status.setText(tr("{done} von {total} MB", done=f"{done / 1048576:.1f}", total=f"{total / 1048576:.1f}"))
        if not self._state["finished"]:
            return
        self.timer.stop()
        if self._state["error"]:
            if not self._cancel:
                QMessageBox.warning(self, tr("Update"), tr("Das Update ist fehlgeschlagen:\n{error}",
                                                                        error=self._state["error"]))
            self.reject()
            return
        self.status.setText(tr("Installiere … das Programm startet gleich neu."))
        try:
            if self._plan is not None:
                updater.launch_patch(self._state["path"], self._plan, relaunch=True)
            else:
                updater.launch_installer(self._state["path"], relaunch=True)
        except (OSError, updater.UpdateError) as exc:
            QMessageBox.warning(self, tr("Update"), tr("Der Installer konnte nicht gestartet werden:\n{error}", error=exc))
            self.reject()
            return
        self.accept()
        self.main.quit_for_update()
