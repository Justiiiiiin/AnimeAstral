"""Reusable building blocks."""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
import json

from PySide6.QtCore import Property, QByteArray, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTextOption
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QProgressBar, QScrollArea, QSizePolicy, QSpinBox, QTableWidget,
                               QTableWidgetItem, QToolButton, QToolTip, QVBoxLayout, QWidget)

from .. import app_paths
from ..i18n import thousands, tr
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
    """The mouse wheel only changes the value of a focused field; otherwise the page keeps scrolling."""

    def _init_nowheel(self) -> None:
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


FIELD_WIDTH = 170                                  # don't stretch number fields across the whole width


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
    """Table cell with its own sort value (numbers sort as numbers, not as text)."""

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
    """Tidy table: header and cells aligned the same, every column resizable on its own, columns movable,
    sortable by clicking the header."""
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
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)      # every column can be resized on its own
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
    """Remember column widths, order and sorting."""
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
    """Smooth pixel scrolling instead of jumpy line scrolling."""
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.verticalScrollBar().setSingleStep(16)


def scroll_page(page: QWidget) -> QScrollArea:
    """Wraps a page: with a small window it scrolls instead of elements overlapping."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)   # only needed at a large UI size
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
    """Subheading above a group of cards."""
    lbl = QLabel(text.upper())
    lbl.setObjectName("section")
    return lbl


def short_field(widget: QWidget, width: int = 260) -> QWidget:
    """Limit an input field for short values (hotkeys, number lists) to a sensible width."""
    theme.track(widget, lambda o, f: o.setMaximumWidth(round(width * f)))
    return widget


def columns(*cards: QWidget, spacing: int = 14) -> QHBoxLayout:
    """Cards side by side, equally wide and equally tall."""
    row = QHBoxLayout()
    theme.track_spacing(row, spacing)
    for card in cards:
        row.addWidget(card, 1)
    return row


def form_grid() -> QGridLayout:
    """Grid label | field; the fields keep their own width."""
    grid = QGridLayout()
    grid.setColumnStretch(2, 1)
    theme.track_spacing(grid, 10)
    return grid


PARAGRAPH = chr(10) * 2                            # paragraph in info texts (blank line)


class InfoButton(QToolButton):
    """Small ⓘ: the explanation appears on hover or click – instead of running text on the page."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.setObjectName("info")
        self.setText("i")
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_info(text)
        self.clicked.connect(lambda: QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.toolTip(), self))

    def set_info(self, text: str) -> None:
        # as rich text so Qt wraps long hints; paragraphs with a blank line
        paras = "".join(f"<p style='margin:0 0 6px 0'>{part}</p>" for part in text.split(PARAGRAPH))
        self.setToolTip(f"<div style='max-width:360px'>{paras}</div>")


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


def page_header(title: str, info: str = "") -> QHBoxLayout:
    """Page title with ⓘ in one row; append controls to the right with addWidget (after addStretch).
    Saves the subtitle row – all pages should fit without scrolling."""
    row = QHBoxLayout()
    theme.track_spacing(row, 8)
    row.addWidget(label(title, "h1"))
    if info:
        row.addWidget(InfoButton(info))
    return row


class StatCard(Card):
    def __init__(self, title: str, value: str = "–") -> None:
        super().__init__()
        self.setProperty("kpi", True)                  # Nebula: accent edge at the top
        theme.track_spacing(self.body, 2)
        self.title_label = label(title, "small", wrap=True)     # wrap instead of widening the row of tiles
        self.body.addWidget(self.title_label)
        self.value = label(value, "kpi")
        self.body.addWidget(self.value)

    def set_value(self, text: str) -> None:
        if self.value.text() != text:
            self.value.setText(text)


def media_icon(kind: str, token: str = "text", size: int = 64):
    """Start (▶), stop (■) or pause (❚❚) as a drawn icon – independent of the font."""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.color(token)))
    s = size / 24.0
    if kind == "play":
        p.drawPolygon(QPolygonF([QPointF(7 * s, 4.5 * s), QPointF(19.5 * s, 12 * s), QPointF(7 * s, 19.5 * s)]))
    elif kind == "stop":
        p.drawRoundedRect(QRectF(6 * s, 6 * s, 12 * s, 12 * s), 2 * s, 2 * s)
    else:                                               # pause
        p.drawRoundedRect(QRectF(6 * s, 5 * s, 4.2 * s, 14 * s), 1.2 * s, 1.2 * s)
        p.drawRoundedRect(QRectF(13.8 * s, 5 * s, 4.2 * s, 14 * s), 1.2 * s, 1.2 * s)
    p.end()
    return QIcon(pix)


def discord_icon(size: int = 64):
    """Discord icon (simplified mascot “Clyde”) in the accent color – drawn, no image file."""
    from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 24.0
    body = QPainterPath()                               # head: wide, round at the top, two “feet” at the bottom
    body.moveTo(5.0 * s, 6.0 * s)
    body.cubicTo(7.5 * s, 4.6 * s, 9.6 * s, 4.4 * s, 10.2 * s, 4.6 * s)
    body.lineTo(10.6 * s, 5.6 * s)
    body.cubicTo(11.6 * s, 5.4 * s, 12.4 * s, 5.4 * s, 13.4 * s, 5.6 * s)
    body.lineTo(13.8 * s, 4.6 * s)
    body.cubicTo(14.4 * s, 4.4 * s, 16.5 * s, 4.6 * s, 19.0 * s, 6.0 * s)
    body.cubicTo(21.0 * s, 9.2 * s, 21.8 * s, 12.6 * s, 21.6 * s, 16.4 * s)
    body.cubicTo(19.8 * s, 17.8 * s, 18.0 * s, 18.6 * s, 16.4 * s, 19.0 * s)
    body.lineTo(15.4 * s, 17.4 * s)
    body.cubicTo(14.2 * s, 17.8 * s, 9.8 * s, 17.8 * s, 8.6 * s, 17.4 * s)
    body.lineTo(7.6 * s, 19.0 * s)
    body.cubicTo(6.0 * s, 18.6 * s, 4.2 * s, 17.8 * s, 2.4 * s, 16.4 * s)
    body.cubicTo(2.2 * s, 12.6 * s, 3.0 * s, 9.2 * s, 5.0 * s, 6.0 * s)
    body.closeSubpath()
    eyes = QPainterPath()
    eyes.addEllipse(7.4 * s, 10.4 * s, 3.0 * s, 3.4 * s)
    eyes.addEllipse(13.6 * s, 10.4 * s, 3.0 * s, 3.4 * s)
    p.fillPath(body.subtracted(eyes), QColor(theme.color("accent")))
    p.end()
    return QIcon(pix)


class ElidedLabel(QLabel):
    """Single-line label that shortens too long text with “…” (full text in the tooltip) – never widens the page."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full = ""
        self.setMinimumWidth(1)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt name)
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def minimumSizeHint(self):  # noqa: N802
        hint = super().minimumSizeHint()
        hint.setWidth(1)
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(10, self.width()))
        if super().text() != shown:
            super().setText(shown)


class QuestRow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        theme.track_margins(lay, 0, 2, 0, 2)
        theme.track_spacing(lay, 4)
        top = QHBoxLayout()
        self.title = ElidedLabel("")                    # one line, long titles with “…” (full title in the tooltip)
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
    """Toggle switch (on/off) – scales with theme.px()."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0                                 # 0 = off, 1 = on (animated)
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
        if not self.isVisible() or not theme.animations():     # invisible or switched off: right away
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
    """Simple bar chart without an extra library."""

    def __init__(self) -> None:
        super().__init__()
        self._data: list[tuple[str, int]] = []
        self._fmt = str                                 # label above the bars
        theme.track_min_height(self, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: list[tuple[str, int]], fmt=None) -> None:
        """fmt: value -> label (e.g. minutes as “2.5 h”); default: the number."""
        self._data = data
        self._fmt = fmt or str
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._data or not any(v for _n, v in self._data):
            p = QPainter(self)
            paint_empty(p, QRectF(self.rect()), "chart", tr("No data in the selected period yet"))
            p.end()
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._data)
        fm = p.fontMetrics()
        line = fm.height()
        top_pad, bottom_pad, gap = line + 6, line + 8, max(4, theme.px(8))
        bw = (w - gap * (n - 1)) / n
        # axis labels only as dense as they don't overlap (every k-th)
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
            if value:                                   # no “0” above empty bars
                p.setPen(QColor(theme.color("text")))
                p.drawText(QRectF(x - gap, h - bottom_pad - bh - line - 2, bw + 2 * gap, line), self._fmt(value), center)
        p.end()


EMPTY_GLYPHS = {"events": 0xE81C, "quests": 0xF0E3, "chart": 0xE9D2, "servers": 0xE734}


def paint_empty(p: QPainter, rect: QRectF, glyph: str, text: str) -> None:
    """Empty state: icon in a softly glowing circle with small stars, a short text below."""
    from PySide6.QtGui import QFont, QRadialGradient
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    size = theme.px(64)
    cx = rect.center().x()
    cy = rect.top() + rect.height() / 2 - theme.px(14)
    accent, accent2 = QColor(theme.color("accent")), QColor(theme.color("accent2"))
    glow = QRadialGradient(cx, cy, size / 2)
    inner, outer = QColor(accent), QColor(accent)
    inner.setAlphaF(0.22)
    outer.setAlphaF(0.0)
    glow.setColorAt(0, inner)
    glow.setColorAt(1, outer)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QRectF(cx - size / 2, cy - size / 2, size, size))
    for dx, dy, r in ((0.42, -0.34, 2.2), (-0.46, 0.18, 1.6), (0.30, 0.40, 1.3)):     # small stars
        star = QColor(accent2)
        star.setAlphaF(0.75)
        p.setBrush(star)
        p.drawEllipse(QRectF(cx + dx * size - r, cy + dy * size - r, 2 * r, 2 * r))
    font = QFont()
    font.setFamilies(list(theme.ICON_FONTS))
    font.setPixelSize(theme.px(28))
    p.setFont(font)
    p.setPen(accent)
    p.drawText(QRectF(cx - size / 2, cy - size / 2, size, size), Qt.AlignmentFlag.AlignCenter,
               chr(EMPTY_GLYPHS.get(glyph, 0xE734)))
    p.setFont(QFont())
    p.setPen(QColor(theme.color("muted")))
    text_rect = QRectF(rect.left() + theme.px(16), cy + size / 2 + theme.px(4), rect.width() - theme.px(32),
                       theme.px(40))
    p.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, text)
    p.restore()


class EmptyState(QWidget):
    """Placeholder for empty areas (events, quests) – instead of plain text."""

    def __init__(self, glyph: str, text: str) -> None:
        super().__init__()
        self._glyph, self._text = glyph, text
        theme.track_min_height(self, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        paint_empty(p, QRectF(self.rect()), self._glyph, self._text)
        p.end()


def round_pixmap(path, size: int):
    """Image as a round crop (avatar). None = image missing."""
    from PySide6.QtGui import QPainterPath
    src = QPixmap(str(path))
    if src.isNull():
        return None
    ratio = 2.0
    out = QPixmap(int(size * ratio), int(size * ratio))
    out.setDevicePixelRatio(ratio)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, size, size))
    p.setClipPath(clip)
    p.fillRect(QRectF(0, 0, size, size), QColor(theme.color("control")))
    p.drawPixmap(QRectF(0, 0, size, size), src, QRectF(src.rect()))
    p.end()
    return out
