"""Dialog „Versionen & Änderungen“: alle Versionshinweise lesen, beliebige Version installieren (auch älter)."""
from __future__ import annotations

import threading
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QTextBrowser, QVBoxLayout)

from .. import updater
from ..i18n import tr
from ..version import __version__
from . import theme
from .widgets import label, smooth


def _date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d.%m.%Y")
    except ValueError:
        return ""


class VersionsDialog(QDialog):
    def __init__(self, main) -> None:
        super().__init__(main)
        self.main = main
        self.releases: list[updater.ReleaseInfo] = []
        self.setWindowTitle(tr("Versions & changes"))
        theme.track(self, lambda o, f: o.resize(round(820 * f), round(560 * f)))
        root = QVBoxLayout(self)
        theme.track_margins(root, 24, 20, 24, 18)
        theme.track_spacing(root, 12)
        root.addWidget(label(tr("Versions & changes"), "h1"))
        root.addWidget(label(tr("Installed: {version}", version=__version__), "muted"))
        body = QHBoxLayout()
        theme.track_spacing(body, 14)
        self.list = QListWidget()
        smooth(self.list)
        theme.track_fixed_width(self.list, 230)
        self.list.currentRowChanged.connect(self._show)
        body.addWidget(self.list)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        body.addWidget(self.notes, 1)
        root.addLayout(body, 1)
        self.state = label(tr("Loading versions …"), "small", wrap=True)
        root.addWidget(self.state)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.reject)
        self.install = QPushButton(tr("Install this version"))
        self.install.setObjectName("primary")
        self.install.setEnabled(False)
        self.install.clicked.connect(self._install)
        row.addWidget(close)
        row.addWidget(self.install)
        root.addLayout(row)

        self._result: dict = {"done": False, "data": None, "error": None}
        repo = updater.current_repo()

        def work() -> None:
            try:
                self._result["data"] = updater.list_releases(repo, beta=self.main.engine.settings.update_beta) if repo else []
                if not repo:
                    self._result["error"] = tr("This version has no update source.")
            except updater.UpdateError as exc:
                self._result["error"] = str(exc)
            self._result["done"] = True

        threading.Thread(target=work, daemon=True).start()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._loaded)
        self._timer.start()

    def _loaded(self) -> None:
        if not self._result["done"]:
            return
        self._timer.stop()
        self.releases = self._result["data"] or []
        if self._result["error"]:
            self.state.setText(self._result["error"])
        else:
            self.state.setText("")
        current = None
        for i, rel in enumerate(self.releases):
            mark = ("  ● " + tr("installed")) if rel.version == __version__ else \
                ("  ★ " + tr("new")) if updater.is_newer(rel.version) else ""
            beta = ("  β " + tr("Beta")) if rel.prerelease else ""
            item = QListWidgetItem(f"{rel.version}   {_date(rel.published)}{beta}{mark}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.list.addItem(item)
            if rel.version == __version__:
                current = i
        if self.releases:
            self.list.setCurrentRow(current if current is not None else 0)

    def _show(self, row: int) -> None:
        if not 0 <= row < len(self.releases):
            return
        rel = self.releases[row]
        self.notes.setMarkdown(f"## {rel.version}\n\n" + (rel.notes or tr("No release notes provided.")))
        if rel.version == __version__:
            self.install.setText(tr("Reinstall"))
        elif updater.is_newer(rel.version):
            self.install.setText(tr("Update to {version}", version=rel.version))
        else:
            self.install.setText(tr("Back to {version}", version=rel.version))
        self.install.setEnabled(updater.is_installed_build())
        if not updater.is_installed_build():
            self.state.setText(tr("Installing only works in the installed version (not when started from source)."))

    def _install(self) -> None:
        row = self.list.currentRow()
        if not 0 <= row < len(self.releases):
            return
        rel = self.releases[row]
        older = updater.version_key(rel.version) < updater.version_key(__version__)
        if older:
            text = tr("Install version {version}? Your settings and statistics are kept.\n\nSo that the newest "
                      "update is not offered again right away, it is skipped – you can update again any time under "
                      "Settings → Updates.", version=rel.version)
            if QMessageBox.question(self, tr("Older version"), text) != QMessageBox.StandardButton.Yes:
                return
            if self.releases and updater.is_newer(self.releases[0].version, rel.version):
                self.main.skip_version(self.releases[0].version)
        from .update_dialog import UpdateDialog
        self.accept()
        UpdateDialog(self.main, rel, full_install=True).exec()
