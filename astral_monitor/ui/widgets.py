"""Wiederverwendbare Bausteine."""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
import json

from PySide6.QtCore import Property, QByteArray, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTextOption
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QProgressBar, QScrollArea, QSizePolicy, QSpinBox, QTableWidget,
                               QTableWidgetItem, QToolButton, QToolTip, QVBoxLayout, QWidget)

from .. import app_paths
from ..i18n import thousands
from . import theme


def bgr_to_pixmap(bgr: np.ndarray, max_width: Optional[int] = None) -> QPixmap:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    pix = QPixmap.fromImage(image)
    if max_width and pix.width() > max_width:
        pix = pix.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
    return pix


class _NoWheelMixin:
    """Das Mausrad ändert den Wert nur bei fokussiertem Feld; sonst scrollt die Seite weiter."""

    def _init_nowheel(self) -> None:
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


FIELD_WIDTH = 170                                  # Zahlenfelder nicht über die ganze Breite ziehen


class SpinBox(_NoWheelMixin, QSpinBox):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._init_nowheel()
        theme.track(self, lambda o, f: o.setMaximumWidth(round(FIELD_WIDTH * f)))


class DoubleSpinBox(_NoWheelMixin, QDoubleSpinBox):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._init_nowheel()
        theme.track(self, lambda o, f: o.setMaximumWidth(round(FIELD_WIDTH * f)))


class ComboBox(_NoWheelMixin, QComboBox):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._init_nowheel()


class SortItem(QTableWidgetItem):
    """Tabellenzelle mit eigenem Sortierwert (Zahlen werden als Zahlen sortiert, nicht als Text)."""

    def __init__(self, text: str, key=None, right: bool = False) -> None:
        super().__init__(text)
        self._key = key
        align = Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft
        self.setTextAlignment(int(align | Qt.AlignmentFlag.AlignVCenter))

    def __lt__(self, other) -> bool:
        a, b = self._key, getattr(other, "_key", None)
        if a is not None and b is not None:
            return a < b
        return self.text() < other.text()


def make_table(headers: list[str], rights: tuple = (), widths: tuple = (), selectable: bool = False) -> QTableWidget:
    """Ordentliche Tabelle: Überschrift und Zellen gleich ausgerichtet, jede Spalte einzeln in der Breite
    ziehbar, Spalten verschiebbar, per Klick auf die Überschrift sortierbar."""
    table = QTableWidget(0, len(headers))
    for i, text in enumerate(headers):
        item = QTableWidgetItem(text)
        align = Qt.AlignmentFlag.AlignRight if i in rights else Qt.AlignmentFlag.AlignLeft
        item.setTextAlignment(int(align | Qt.AlignmentFlag.AlignVCenter))
        table.setHorizontalHeaderItem(i, item)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    if selectable:
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    else:
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)
    table.setShowGrid(False)
    table.setWordWrap(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)      # jede Spalte einzeln ziehbar
    header.setStretchLastSection(True)
    header.setSectionsMovable(True)
    header.setSortIndicatorShown(True)
    header.setHighlightSections(False)
    header.setMinimumSectionSize(60)
    for i, w in enumerate(widths):
        table.setColumnWidth(i, w)
    table.setSortingEnabled(True)
    smooth(table)
    return table


def _ui_state_file():
    return app_paths.data_dir() / "ui_state.json"


def _read_ui_state() -> dict:
    try:
        data = json.loads(_ui_state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_header(table: QTableWidget, key: str) -> None:
    """Spaltenbreiten, Reihenfolge und Sortierung merken."""
    state = _read_ui_state()
    state[key] = bytes(table.horizontalHeader().saveState().toBase64().data()).decode("ascii")
    try:
        _ui_state_file().write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def restore_header(table: QTableWidget, key: str) -> None:
    text = _read_ui_state().get(key)
    if text:
        table.horizontalHeader().restoreState(QByteArray.fromBase64(text.encode("ascii")))


def smooth(view: QAbstractItemView) -> None:
    """Pixelweises, ruhiges Scrollen statt sprunghaftem Zeilen-Scrollen."""
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.verticalScrollBar().setSingleStep(16)


def scroll_page(page: QWidget) -> QScrollArea:
    """Verpackt eine Seite: bei kleinem Fenster wird gescrollt, statt dass Elemente überlappen."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)   # nur bei großer UI-Größe nötig
    area.verticalScrollBar().setSingleStep(24)
    area.setWidget(page)
    return area


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def section(text: str) -> QLabel:
    """Zwischenüberschrift über einer Gruppe von Karten."""
    lbl = QLabel(text.upper())
    lbl.setObjectName("section")
    return lbl


def short_field(widget: QWidget, width: int = 260) -> QWidget:
    """Eingabefeld für kurze Werte (Hotkeys, Zahlenlisten) auf eine sinnvolle Breite begrenzen."""
    theme.track(widget, lambda o, f: o.setMaximumWidth(round(width * f)))
    return widget


def columns(*cards: QWidget, spacing: int = 14) -> QHBoxLayout:
    """Karten nebeneinander, gleich breit und gleich hoch."""
    row = QHBoxLayout()
    theme.track_spacing(row, spacing)
    for card in cards:
        row.addWidget(card, 1)
    return row


def form_grid() -> "QGridLayout":
    """Raster Beschriftung | Feld; die Felder behalten ihre eigene Breite."""
    from PySide6.QtWidgets import QGridLayout
    grid = QGridLayout()
    grid.setColumnStretch(2, 1)
    theme.track_spacing(grid, 10)
    return grid


PARAGRAPH = chr(10) * 2                            # Absatz in Info-Texten (Leerzeile)


class InfoButton(QToolButton):
    """Kleines ⓘ: Erklärung erscheint beim Darüberfahren oder Anklicken – statt Fließtext auf der Seite."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.setObjectName("info")
        self.setText("i")
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_info(text)
        self.clicked.connect(lambda: QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.toolTip(), self))

    def set_info(self, text: str) -> None:
        # als Rich-Text, damit Qt lange Hinweise umbricht; Absätze mit Leerzeile
        paras = "".join(f"<p style='margin:0 0 6px 0'>{part}</p>" for part in text.split(PARAGRAPH))
        self.setToolTip(f"<div style='max-width:360px'>{paras}</div>")


def with_info(widget: QWidget, text: str) -> QHBoxLayout:
    """Zeile: Element + ⓘ (z. B. für Kontrollkästchen)."""
    row = QHBoxLayout()
    theme.track_spacing(row, 6)
    row.addWidget(widget)
    row.addWidget(InfoButton(text))
    row.addStretch(1)
    return row


class Card(QFrame):
    def __init__(self, title: str = "", info: str = "") -> None:
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        theme.track_margins(self.body, 16, 14, 16, 14)
        theme.track_spacing(self.body, 10)
        self.info: Optional[InfoButton] = None
        if title:
            head = QHBoxLayout()
            theme.track_spacing(head, 8)
            head.addWidget(label(title, "h2"))
            if info:
                self.info = InfoButton(info)
                head.addWidget(self.info)
            head.addStretch(1)
            self.body.addLayout(head)


class StatCard(Card):
    def __init__(self, title: str, value: str = "–") -> None:
        super().__init__()
        theme.track_spacing(self.body, 2)
        self.title_label = label(title, "small", wrap=True)     # umbrechen statt die Kachelreihe zu verbreitern
        self.body.addWidget(self.title_label)
        self.value = label(value, "kpi")
        self.body.addWidget(self.value)

    def set_title(self, text: str) -> None:
        if self.title_label.text() != text:
            self.title_label.setText(text)

    def set_value(self, text: str) -> None:
        if self.value.text() != text:
            self.value.setText(text)


class QuestRow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        theme.track_margins(lay, 0, 2, 0, 2)
        theme.track_spacing(lay, 4)
        top = QHBoxLayout()
        self.title = QLabel("")
        self.value = QLabel("")
        self.value.setObjectName("muted")
        top.addWidget(self.title, 1)
        top.addWidget(self.value)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        lay.addLayout(top)
        lay.addWidget(self.bar)

    def set_quest(self, q: dict) -> None:
        cur = "?" if q["cur"] is None else thousands(f"{q['cur']:,}")
        tot = "?" if not q["total"] else thousands(f"{q['total']:,}")
        self.title.setText(q["title"])
        self.value.setText(f"{cur} / {tot}")
        self.bar.setValue(q["percent"] or 0)


class ToggleSwitch(QAbstractButton):
    """Schiebeschalter (an/aus) – skaliert mit theme.px()."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0                                 # 0 = aus, 1 = an (animiert)
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, on: bool) -> None:
        if not self.isVisible():                       # unsichtbar (z. B. beim Laden): ohne Animation
            self._set_knob(1.0 if on else 0.0)
            return
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:
        return QSize(theme.px(42), theme.px(24))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        track_h = min(h, theme.px(22))
        top = (h - track_h) / 2
        t = self._pos
        off, on = QColor(theme.color("trackOff")), QColor(theme.color("accent"))
        mix = QColor.fromRgbF(off.redF() + (on.redF() - off.redF()) * t, off.greenF() + (on.greenF() - off.greenF()) * t,
                              off.blueF() + (on.blueF() - off.blueF()) * t)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix)
        p.drawRoundedRect(QRectF(0, top, w, track_h), track_h / 2, track_h / 2)
        knob = track_h - theme.px(6)
        x = theme.px(3) + (w - knob - 2 * theme.px(3)) * t
        p.setBrush(QColor(theme.color("knobOn" if t > 0.5 else "knobOff")))
        p.drawEllipse(QRectF(x, top + theme.px(3), knob, knob))
        p.end()


class BarChart(QWidget):
    """Einfaches Balkendiagramm ohne Zusatzbibliothek."""

    def __init__(self) -> None:
        super().__init__()
        self._data: list[tuple[str, int]] = []
        theme.track_min_height(self, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: list[tuple[str, int]]) -> None:
        self._data = data
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._data)
        fm = p.fontMetrics()
        line = fm.height()
        top_pad, bottom_pad, gap = line + 6, line + 8, max(4, theme.px(8))
        bw = (w - gap * (n - 1)) / n
        # Achsenbeschriftung nur so dicht, dass sie sich nicht überlappt (jede k-te)
        widest = max(fm.horizontalAdvance(name) for name, _ in self._data) + theme.px(6)
        step = max(1, int(-(-widest // (bw + gap))))
        max_v = max(1, max(v for _, v in self._data))
        best = max(range(n), key=lambda i: self._data[i][1])
        center = QTextOption(Qt.AlignmentFlag.AlignCenter)
        for i, (name, value) in enumerate(self._data):
            x = i * (bw + gap)
            bh = (h - top_pad - bottom_pad) * value / max_v
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.color("accent" if i == best and value else "bar" if value else "barEmpty")))
            p.drawRoundedRect(QRectF(x, h - bottom_pad - max(bh, 2), bw, max(bh, 2)), 3, 3)
            p.setPen(QColor(theme.color("muted")))
            if i % step == 0:
                p.drawText(QRectF(x - gap, h - bottom_pad + 4, bw + 2 * gap, line), name, center)
            if value:                                   # keine „0“ über leeren Balken
                p.setPen(QColor(theme.color("text")))
                p.drawText(QRectF(x - gap, h - bottom_pad - bh - line - 2, bw + 2 * gap, line), str(value), center)
        p.end()
