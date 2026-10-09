"""Dialog “Update available”: show notes, download, verify checksum, start the installer."""
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
        """full_install: use the full installer (downgrade/new install – update packages only go forward)."""
        super().__init__(main)
        self.main, self.info = main, info
        newer = updater.is_newer(info.version)
        self.setWindowTitle(tr("Update available") if newer else tr("Install version"))
        self.setModal(True)
        self.resize(560, 460)
        self._state = {"done": 0, "total": 0, "error": None, "path": None, "finished": False}
        self._cancel = False

        lay = QVBoxLayout(self)
        theme.track_margins(lay, 28, 24, 28, 20)
        theme.track_spacing(lay, 12)
        lay.addWidget(label(tr("Version {version} is available", version=info.version) if newer
                            else tr("Install version {version}", version=info.version), "h1"))
        lay.addWidget(label(tr("You have version {version}.", version=__version__), "muted"))
        notes = QTextBrowser()                  # GitHub release notes are Markdown
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.notes or tr("No release notes provided."))
        lay.addWidget(notes, 1)
        self.warn = label(tr("Monitoring will be stopped for the update; the program restarts afterwards.")
                          if main.engine.running else tr("The program restarts automatically after the update."), "muted", wrap=True)
        lay.addWidget(self.warn)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = label("", "small")
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.btn_skip = QPushButton(tr("Skip this version"))
        self.btn_skip.clicked.connect(self._skip)
        self.btn_skip.setVisible(newer and not full_install)
        btn_all = QPushButton(tr("All versions …"))
        btn_all.setToolTip(tr("Read the release notes of every version or install an older one"))
        btn_all.clicked.connect(self._all_versions)
        self.btn_later = QPushButton(tr("Later"))
        self.btn_later.clicked.connect(self.reject)
        self.btn_go = QPushButton(tr("Update now") if newer else tr("Install"))
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

        # Does the small update package fit (changed files only)? Checked in the background, usually takes < 1 s.
        self._plan = None
        self._plan_state = {"done": False, "plan": None}
        self.btn_go.setEnabled(False)
        self.status.setText(tr("Checking download size …"))

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
            self.status.setText(tr("Download: {mb} MB (only {count} changed files)",
                                   mb=f"{self.info.patch_size / 1048576:.1f}", count=len(self._plan.changed)))
        else:
            self.status.setText(tr("Download: {mb} MB (full installer)", mb=f"{self.info.size / 1048576:.0f}"))
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
        self.btn_go.setText(tr("Cancel"))
        self.btn_go.clicked.disconnect()
        self.btn_go.clicked.connect(self._abort)
        self.bar.setVisible(True)
        self.status.setText(tr("Downloading …"))
        self.timer.start()

        def work() -> None:
            try:
                self._state["path"] = updater.download(
                    self.info, lambda d, t: self._state.update(done=d, total=t), lambda: self._cancel,
                    patch=self._plan is not None)
            except Exception as exc:                    # UpdateError and anything unexpected
                self._state["error"] = str(exc) or exc.__class__.__name__
            self._state["finished"] = True

        threading.Thread(target=work, daemon=True).start()

    def _abort(self) -> None:
        self._cancel = True
        self.btn_go.setEnabled(False)
        self.status.setText(tr("Cancelling …"))

    def _poll(self) -> None:
        total, done = self._state["total"], self._state["done"]
        if total:
            self.bar.setValue(int(done * 100 / total))
            self.status.setText(tr("{done} of {total} MB", done=f"{done / 1048576:.1f}", total=f"{total / 1048576:.1f}"))
        if not self._state["finished"]:
            return
        self.timer.stop()
        if self._state["error"]:
            if not self._cancel:
                QMessageBox.warning(self, tr("Update"), tr("The update failed:\n{error}",
                                                                        error=self._state["error"]))
            self.reject()
            return
        self.status.setText(tr("Installing … the program will restart shortly."))
        try:
            if self._plan is not None:
                updater.launch_patch(self._state["path"], self._plan, relaunch=True)
            else:
                updater.launch_installer(self._state["path"], relaunch=True)
        except (OSError, updater.UpdateError) as exc:
            QMessageBox.warning(self, tr("Update"), tr("The installer could not be started:\n{error}", error=exc))
            self.reject()
            return
        self.accept()
        self.main.quit_for_update()
