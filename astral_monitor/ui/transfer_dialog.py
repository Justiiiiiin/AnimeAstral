"""Dialoge: Einstellungen mit Passwort exportieren / importieren (secure.py)."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QFrame, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout

from .. import secure
from ..i18n import tr
from . import theme
from .widgets import form_grid, label


class PasswordDialog(QDialog):
    """export=True: Warnhinweis + Passwort zweimal. export=False: Passwort einmal (Import)."""

    def __init__(self, parent, export: bool) -> None:
        super().__init__(parent)
        self._export = export
        title = tr("Export settings") if export else tr("Import settings")
        self.setWindowTitle(title)
        theme.track_min_width(self, 540)
        root = QVBoxLayout(self)
        theme.track_margins(root, 20, 18, 20, 18)
        theme.track_spacing(root, 12)
        root.addWidget(label(title, "h2"))
        if export:
            box = QFrame()
            box.setObjectName("card")
            inner = QVBoxLayout(box)
            theme.track_margins(inner, 14, 12, 14, 12)
            inner.addWidget(label(tr("⚠️ The file contains your Discord webhook URL, your saved server links and "
                                     "IDs."), "warn", wrap=True))
            inner.addWidget(label(tr("Anyone who knows the webhook URL can send messages to your channel. That is "
                                     "why the file is encrypted with your password (AES-256) – without the password "
                                     "it is unreadable. Nobody can recover a forgotten password."),
                                  "small", wrap=True))
            root.addWidget(box)
        else:
            root.addWidget(label(tr("Enter the password you chose when exporting. Your current settings will then "
                                    "be replaced."), "small", wrap=True))
        grid = form_grid()
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.repeat = QLineEdit()
        self.repeat.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(label(tr("Password")), 0, 0)
        grid.addWidget(self.password, 0, 1)
        if export:
            grid.addWidget(label(tr("Repeat")), 1, 0)
            grid.addWidget(self.repeat, 1, 1)
        else:
            self.repeat.hide()
        root.addLayout(grid)
        show = QCheckBox(tr("Show password"))
        show.toggled.connect(self._show)
        root.addWidget(show)
        self.state = label("", "small", wrap=True)
        root.addWidget(self.state)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(tr("Continue …") if export else tr("Import"))
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        root.addLayout(row)
        self.password.textChanged.connect(self._check)
        self.repeat.textChanged.connect(self._check)
        self._check()
        self.password.setFocus()

    def _show(self, on: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        self.password.setEchoMode(mode)
        self.repeat.setEchoMode(mode)

    def _check(self) -> None:
        if self._export:
            problem = secure.check_password(self.password.text(), self.repeat.text())
        else:
            problem = None if self.password.text() else tr("Please enter the password.")
        self.state.setText(problem or "")
        self.ok.setEnabled(problem is None)

    def value(self) -> str:
        return self.password.text()
