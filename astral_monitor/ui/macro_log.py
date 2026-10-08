"""Makro-Protokoll: kompakte Log-Ansicht (Uhrzeit + Meldung, enge Zeilen, Farbe nach Art). Steht unter
Einstellungen → Makro; auf der Startseite nur, wenn dort „Protokoll auf der Startseite“ an ist."""
from __future__ import annotations

import html

from PySide6.QtCore import QSize
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton

from ..i18n import tr
from . import theme
from .widgets import Card


def _token(text: str) -> str:
    """Farbe einer Zeile: Start/Fertig, Warnung, Abbruch/Fehler, sonst normal."""
    if text.startswith(("✖", "■")):
        return "danger"
    if text.startswith("⚠"):
        return "warn"
    if text.startswith(("▶", "✔")):
        return "accent"
    if text.startswith(tr("Schritt")) or text.startswith(tr("Runde")):
        return "accent2"
    return "text"


class MacroLogView(QPlainTextEdit):
    """Liest aus dem MacroController; mehrere Ansichten (Einstellungen, Startseite) zeigen dasselbe."""

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

    def sizeHint(self) -> QSize:                          # füllt den Platz, fordert aber keinen (ohne Scrollen)
        return QSize(super().sizeHint().width(), theme.px(80))

    def _append(self, stamp: str, text: str) -> None:
        muted, color = theme.color("muted"), theme.color(_token(text))
        self.appendHtml(f'<span style="color:{muted}">{stamp}</span>&nbsp; '
                        f'<span style="color:{color}">{html.escape(text)}</span>')
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def reload(self) -> None:
        """Nach Designwechsel neu einfärben."""
        self.clear()
        for stamp, text in self.controller.lines:
            self._append(stamp, text)


class MacroLogCard(Card):
    def __init__(self, controller, info: str = "") -> None:
        super().__init__(tr("Makro-Protokoll"), info or tr(
            "Was das Makro gerade tut – jeder Schritt mit Uhrzeit. Farbig: Start, Schritte und „fertig“; orange: "
            "Warnung (wird wiederholt oder übersprungen); rot: abgebrochen. Ausführlich mit Bildern bei Problemen: "
            "debug/makro_*.jpg im Datenordner."))
        self.controller = controller
        self.view = MacroLogView(controller)
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        copy = QPushButton(tr("Kopieren"))
        copy.setToolTip(tr("Ganzes Protokoll in die Zwischenablage (z. B. für eine Fehlermeldung)"))
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(
            "\n".join(f"{s}  {t}" for s, t in controller.lines)))
        clear = QPushButton(tr("Leeren"))
        clear.clicked.connect(self._clear)
        row.addStretch(1)
        row.addWidget(copy)
        row.addWidget(clear)
        self.body.addLayout(row)

    def _clear(self) -> None:
        self.controller.clear_log()
