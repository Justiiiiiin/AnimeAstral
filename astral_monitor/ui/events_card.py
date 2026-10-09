"""Karte „Debug“ (Einstellungen → Debug): zeigt live jede Protokollzeile – dasselbe wie monitor.log im
Diagnose-Paket (Überwachung, Makro, Erkunden, Anti-AFK, Rejoin, Fehler). Nur bei Bedarf einschalten: aus = es wird
nichts gesammelt (debuglog.BUFFER hängt dann nicht am Logger), die Karte zeichnet nichts."""
from __future__ import annotations

import html

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton

from .. import app_paths
from ..debuglog import BUFFER, KEEP
from ..i18n import tr
from . import theme
from .widgets import Card, short_field

LEVEL_TOKENS = {"ERROR": "danger", "CRITICAL": "danger", "WARNING": "warn", "DEBUG": "muted", "INFO": "text"}


def set_debug(enabled: bool) -> None:
    """Sammeln an/aus (beim Start und vom Schalter)."""
    BUFFER.enable(enabled, app_paths.log_file())


class EventsCard(Card):
    def __init__(self, main) -> None:
        super().__init__(tr("Debug"),
                         tr("Shows everything the program logs, live – exactly like monitor.log in the diagnostics "
                            "package: monitoring, macro and explore steps, anti-AFK, rejoin, warnings and errors. "
                            "Switching it on loads the last lines from the log.\n\nOnly switch it on when needed: "
                            "off = nothing is collected or drawn."))
        self.main = main
        self._seq = 0
        head = self.body.itemAt(0).layout()
        self.enabled = QCheckBox(tr("Debug on"))
        self.enabled.setChecked(bool(main.engine.settings.debug_view))
        self.enabled.toggled.connect(self._toggle)
        head.addWidget(self.enabled)

        row = QHBoxLayout()
        theme.track_spacing(row, 8)
        self.filter = short_field(QLineEdit(), 280)
        theme.track_min_width(self.filter, 260)
        self.filter.setPlaceholderText(tr("Filter (e.g. makro, tracker, WARNING) …"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _t: self._rebuild())
        row.addWidget(self.filter)
        row.addStretch(1)
        copy = QPushButton(tr("Copy"))
        copy.setToolTip(tr("Copy all shown lines to the clipboard"))
        copy.clicked.connect(self._copy)
        clear = QPushButton(tr("Clear"))
        clear.clicked.connect(self._clear)
        diag = QPushButton(tr("Diagnostics package"))
        diag.setToolTip(tr("Log, value history and settings without webhook and links – for troubleshooting"))
        diag.clicked.connect(lambda: self.main.create_diagnostics())
        for btn in (copy, clear, diag):
            row.addWidget(btn)
        self.body.addLayout(row)
        self._buttons = [self.filter, copy, clear]

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(KEEP)
        self.view.setObjectName("debuglog")
        theme.track_min_height(self.view, 180)
        self.body.addWidget(self.view, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._poll)
        self._show_state()

    # ------------------------------------------------------------------ An/Aus
    def _toggle(self, on: bool) -> None:
        s = self.main.engine.settings
        s.debug_view = on
        try:
            s.save()                                     # sofort, ohne Speichern-Leiste
        except OSError as exc:
            QMessageBox.critical(self, tr("Save"), tr("Could not save: {error}", error=exc))
        set_debug(on)
        self._seq = 0
        self._show_state()

    def _show_state(self) -> None:
        on = self.enabled.isChecked()
        for w in self._buttons:
            w.setEnabled(on)
        self.view.clear()
        self.view.setPlaceholderText("" if on else tr("Debug is off – switch it on at the top right when you want "
                                                      "to test something or track down a bug."))
        if on:
            self._rebuild()
            self.timer.start()
        else:
            self.timer.stop()

    # ------------------------------------------------------------------ Anzeige
    def _line_html(self, level: str, text: str) -> str:
        color = theme.color(LEVEL_TOKENS.get(level, "text"))
        return f"<span style='color:{color}'>{html.escape(text)}</span>"

    def _match(self, text: str) -> bool:
        words = self.filter.text().casefold().split()
        return all(w in text.casefold() for w in words)

    def _rebuild(self) -> None:
        self.view.clear()
        lines = BUFFER.since(0)
        self._seq = lines[-1][0] if lines else 0
        shown = [self._line_html(level, text) for _s, level, text in lines if self._match(text)]
        if shown:
            self.view.appendHtml("<br>".join(shown))
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def _poll(self) -> None:
        if not self.isVisible():
            return                                       # Reiter nicht offen: nichts zeichnen
        lines = BUFFER.since(self._seq)
        if not lines:
            return
        self._seq = lines[-1][0]
        bar = self.view.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        for _s, level, text in lines:
            if self._match(text):
                self.view.appendHtml(self._line_html(level, text))
        if at_end:
            bar.setValue(bar.maximum())                  # nur mitlaufen, wenn man nicht gerade hochgescrollt hat

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.view.toPlainText())

    def _clear(self) -> None:
        BUFFER.clear()
        self._seq = 0
        self.view.clear()

    def recolor(self) -> None:
        if self.enabled.isChecked():
            self._rebuild()

    def add(self, _data: dict) -> None:
        """Früher: einzelne Ereignisse. Sie stehen jetzt ohnehin im Protokoll."""
