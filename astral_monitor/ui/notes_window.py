"""Notebook (beta): free notes on upgrades, codes and plans – saves automatically, only on this PC."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from .. import app_paths
from ..i18n import tr
from . import theme
from .widgets import label

SAVE_DELAY_MS = 800


def notes_file():
    return app_paths.data_dir() / "notes.md"


class NotesWindow(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(tr("Notebook"))
        theme.track_min_width(self, 420)
        theme.track_min_height(self, 360)
        self.resize(theme.px(520), theme.px(560))
        root = QVBoxLayout(self)
        theme.track_margins(root, 18, 16, 18, 16)
        theme.track_spacing(root, 10)
        head = QHBoxLayout()
        head.addWidget(label(tr("Notebook"), "h2"))
        beta = label(tr("Beta"), "small")
        head.addWidget(beta)
        head.addStretch(1)
        self.state = label("", "small")
        head.addWidget(self.state)
        root.addLayout(head)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(tr("Upgrades, codes, plans … saved automatically."))
        try:
            self.edit.setPlainText(notes_file().read_text(encoding="utf-8"))
        except OSError:
            pass
        root.addWidget(self.edit, 1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SAVE_DELAY_MS)
        self._timer.timeout.connect(self.save)
        self.edit.textChanged.connect(self._changed)

    def _changed(self) -> None:
        self.state.setText("…")
        self._timer.start()

    def save(self) -> None:
        self._timer.stop()
        try:
            notes_file().write_text(self.edit.toPlainText(), encoding="utf-8")
            self.state.setText(tr("Saved ✓"))
        except OSError as exc:
            self.state.setText(tr("Could not save: {error}", error=exc))

    def closeEvent(self, event) -> None:
        if self._timer.isActive():
            self.save()
        super().closeEvent(event)
