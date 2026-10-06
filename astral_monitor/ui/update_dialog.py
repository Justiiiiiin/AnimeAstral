"""Dialog „Update verfügbar“: Hinweise anzeigen, laden, Prüfsumme prüfen, Installer starten."""
from __future__ import annotations

import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QMessageBox, QProgressBar, QPushButton, QTextBrowser,
                               QVBoxLayout)

from .. import updater
from ..version import __version__
from .widgets import label


class UpdateDialog(QDialog):
    def __init__(self, main, info: updater.ReleaseInfo) -> None:
        super().__init__(main)
        self.main, self.info = main, info
        self.setWindowTitle("Update verfügbar")
        self.setModal(True)
        self.resize(560, 460)
        self._state = {"done": 0, "total": 0, "error": None, "path": None, "finished": False}
        self._cancel = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        lay.addWidget(label(f"Version {info.version} ist verfügbar", "h1"))
        lay.addWidget(label(f"Du hast Version {__version__}.", "muted"))
        notes = QTextBrowser()                  # GitHub-Versionshinweise sind Markdown
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.notes or "Keine Versionshinweise angegeben.")
        lay.addWidget(notes, 1)
        self.warn = label("Die laufende Überwachung wird für das Update beendet; danach startet das Programm neu."
                          if main.engine.running else "Das Programm startet nach dem Update automatisch neu.", "muted", wrap=True)
        lay.addWidget(self.warn)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = label("", "small")
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.btn_skip = QPushButton("Diese Version überspringen")
        self.btn_skip.clicked.connect(self._skip)
        self.btn_later = QPushButton("Später")
        self.btn_later.clicked.connect(self.reject)
        self.btn_go = QPushButton("Jetzt aktualisieren")
        self.btn_go.setObjectName("primary")
        self.btn_go.clicked.connect(self._start)
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        row.addWidget(self.btn_later)
        row.addWidget(self.btn_go)
        lay.addLayout(row)

        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._poll)

    def _skip(self) -> None:
        self.main.skip_version(self.info.version)
        self.reject()

    def _start(self) -> None:
        for btn in (self.btn_skip, self.btn_later):
            btn.setEnabled(False)
        self.btn_go.setText("Abbrechen")
        self.btn_go.clicked.disconnect()
        self.btn_go.clicked.connect(self._abort)
        self.bar.setVisible(True)
        self.status.setText("Lade herunter …")
        self.timer.start()

        def work() -> None:
            try:
                self._state["path"] = updater.download(
                    self.info, lambda d, t: self._state.update(done=d, total=t), lambda: self._cancel)
            except Exception as exc:                    # UpdateError und alles Unerwartete
                self._state["error"] = str(exc) or exc.__class__.__name__
            self._state["finished"] = True

        threading.Thread(target=work, daemon=True).start()

    def _abort(self) -> None:
        self._cancel = True
        self.btn_go.setEnabled(False)
        self.status.setText("Wird abgebrochen …")

    def _poll(self) -> None:
        total, done = self._state["total"], self._state["done"]
        if total:
            self.bar.setValue(int(done * 100 / total))
            self.status.setText(f"{done / 1048576:.1f} von {total / 1048576:.1f} MB")
        if not self._state["finished"]:
            return
        self.timer.stop()
        if self._state["error"]:
            if not self._cancel:
                QMessageBox.warning(self, "Update", f"Das Update ist fehlgeschlagen:\n{self._state['error']}")
            self.reject()
            return
        self.status.setText("Installiere … das Programm startet gleich neu.")
        try:
            updater.launch_installer(self._state["path"], relaunch=True)
        except OSError as exc:
            QMessageBox.warning(self, "Update", f"Der Installer konnte nicht gestartet werden:\n{exc}")
            self.reject()
            return
        self.accept()
        self.main.quit_for_update()
