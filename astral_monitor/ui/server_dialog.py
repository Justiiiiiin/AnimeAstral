"""Dialog: Server-Favorit anlegen oder ändern (Name + Private-Server-Link)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout

from .. import roblox_join
from ..i18n import tr
from . import theme
from .widgets import form_grid, label


class ServerDialog(QDialog):
    def __init__(self, parent, title: str, name: str = "", link: str = "", taken: tuple = ()) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._taken = {t.lower() for t in taken}
        theme.track_min_width(self, 560)
        root = QVBoxLayout(self)
        theme.track_margins(root, 20, 18, 20, 18)
        theme.track_spacing(root, 12)
        root.addWidget(label(title, "h2"))
        grid = form_grid()
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        self.name = QLineEdit(name)
        self.name.setMaxLength(40)
        self.name.setPlaceholderText(tr("z. B. Mein Server oder Server von Max"))
        self.link = QLineEdit(link)
        self.link.setPlaceholderText("https://www.roblox.com/share?code=…&type=Server")
        grid.addWidget(label(tr("Name")), 0, 0)
        grid.addWidget(self.name, 0, 1)
        grid.addWidget(label(tr("Link")), 1, 0)
        grid.addWidget(self.link, 1, 1)
        root.addLayout(grid)
        self.state = label("", "small", wrap=True)
        root.addWidget(self.state)
        root.addWidget(label(tr("Teilen-Link aus Roblox („Teilen“ → Link kopieren) oder klassischer Link mit "
                                "„privateServerLinkCode“. Der Link bleibt nur auf diesem PC."), "small", wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("Abbrechen"))
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(tr("Speichern"))
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        root.addLayout(row)
        self.name.textChanged.connect(self._check)
        self.link.textChanged.connect(self._check)
        self._check()
        (self.link if name else self.name).setFocus()

    def _problem(self) -> Optional[str]:
        name = self.result_name()
        if not name:
            return tr("Bitte einen Namen eingeben.")
        if name.lower() in self._taken:
            return tr("Diesen Namen gibt es schon.")
        if not roblox_join.deep_link(self.link.text()):
            return roblox_join.explain(self.link.text())
        return None

    def _check(self) -> None:
        problem = self._problem()
        self.state.setText(problem or "✓ " + roblox_join.explain(self.link.text()))
        self.state.setObjectName("small" if problem else "good")
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self.ok.setEnabled(problem is None)

    def result_name(self) -> str:
        return " ".join(self.name.text().split())[:40]

    def result_link(self) -> str:
        return self.link.text().strip().strip("﻿​\"'<>").strip()
