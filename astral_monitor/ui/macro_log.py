"""Macro log: compact log view (time + message, tight lines, color by kind). Lives under Settings → Macro; on
the start page only if “Macro log on the start page” is switched on there."""
from __future__ import annotations

import html

from PySide6.QtCore import QSize
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton

from ..i18n import tr
from . import theme
from .widgets import Card


def _token(text: str) -> str:
    """Color of a line: start/done, warning, stop/error, otherwise normal."""
    if text.startswith(("✖", "■")):
        return "danger"
    if text.startswith("⚠"):
        return "warn"
    if text.startswith(("▶", "✔")):
        return "accent"
    if text.startswith(tr("Step")) or text.startswith(tr("Round")):
        return "accent2"
    return "text"


class MacroLogView(QPlainTextEdit):
    """Reads from the MacroController; several views (settings, start page) show the same."""

    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self.setReadOnly(True)
        self.setObjectName("macroLog")
        self.setMaximumBlockCount(controller.lines.maxlen or 400)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont("Cascadia Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        theme.track(self, lambda o, f: (font.setPointSizeF(max(7.0, 8.5 * f)), o.setFont(font)))
        self.document().setDocumentMargin(4)
        for stamp, text in controller.lines:
            self._append(stamp, text)
        controller.log_listeners.append(self._append)
        controller.clear_listeners.append(self.clear)
        self.destroyed.connect(lambda *_: self._detach())

    def _detach(self) -> None:
        for listeners, f in ((self.controller.log_listeners, self._append),
                             (self.controller.clear_listeners, self.clear)):
            try:
                listeners.remove(f)
            except ValueError:
                pass

    def sizeHint(self) -> QSize:                          # fills the space but doesn't demand any (no scrolling)
        return QSize(super().sizeHint().width(), theme.px(80))

    def _append(self, stamp: str, text: str) -> None:
        muted, color = theme.color("muted"), theme.color(_token(text))
        self.appendHtml(f'<span style="color:{muted}">{stamp}</span>&nbsp; '
                        f'<span style="color:{color}">{html.escape(text)}</span>')
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def reload(self) -> None:
        """Recolor after a design change."""
        self.clear()
        for stamp, text in self.controller.lines:
            self._append(stamp, text)


class MacroLogCard(Card):
    def __init__(self, controller, info: str = "") -> None:
        super().__init__(tr("Macro log"), info or tr(
            "What the macro is doing right now – every step with its time. Colored: start, steps and “done”; "
            "orange: warning (retried or skipped); red: stopped. Details with images on problems: debug/makro_*.jpg "
            "in the data folder."))
        self.controller = controller
        self.view = MacroLogView(controller)
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        copy = QPushButton(tr("Copy"))
        copy.setToolTip(tr("Copy the whole log to the clipboard (e.g. for a bug report)"))
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(
            "\n".join(f"{s}  {t}" for s, t in controller.lines)))
        clear = QPushButton(tr("Clear"))
        clear.clicked.connect(self._clear)
        row.addStretch(1)
        row.addWidget(copy)
        row.addWidget(clear)
        self.body.addLayout(row)

    def _clear(self) -> None:
        self.controller.clear_log()
