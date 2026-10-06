"""Dunkles Theme (QSS)."""
from __future__ import annotations

import re
import weakref

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG = "#0F1419"
SIDEBAR = "#0B0F14"
CARD = "#151B23"
BORDER = "#222B36"
TEXT = "#E6EAF0"
MUTED = "#8B97A8"
ACCENT = "#3DD6B5"
WARN = "#F5A524"
DANGER = "#FF9A9A"
OK_BG = "#12201E"
OK_BORDER = "#1F4A42"

STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: "Segoe UI"; font-size: 10pt; }}
QMainWindow, QStackedWidget {{ background: {BG}; }}
QFrame#sidebar {{ background: {SIDEBAR}; border-right: 1px solid #1E2630; }}
QFrame#topbar {{ background: {SIDEBAR}; border-bottom: 1px solid #1E2630; }}
QFrame#topbar QWidget {{ background: transparent; }}
QFrame#topbar QPushButton#slim {{ background: #18212B; min-height: 28px; padding: 0 12px; border-radius: 7px; }}
QFrame#topbar QPushButton#slim:hover {{ background: #1E2A37; }}
QFrame#sidebar QWidget {{ background: transparent; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#card QWidget {{ background: transparent; }}
QFrame#statusbox {{ background: {OK_BG}; border: 1px solid {OK_BORDER}; border-radius: 8px; }}
QFrame#statusbox[state="off"] {{ background: {CARD}; border: 1px solid {BORDER}; }}
QLabel#h1 {{ font-size: 17pt; font-weight: 600; }}
QLabel#h2 {{ font-size: 11pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#small {{ color: {MUTED}; font-size: 9pt; }}
QLabel#kpi {{ font-family: Consolas; font-size: 20pt; font-weight: 600; }}
QLabel#wave {{ font-family: Consolas; font-size: 34pt; font-weight: 600; }}
QLabel#preview {{ background: {SIDEBAR}; border: 1px solid {BORDER}; border-radius: 8px; }}
QLabel#good {{ color: {ACCENT}; }}
QLabel#bad {{ color: {DANGER}; }}
QLabel#warn {{ color: {WARN}; }}
QLabel#chip {{ background: #18212B; border: 1px solid #2B3644; border-radius: 12px; padding: 5px 14px; color: {MUTED}; }}
QLabel#chip[state="ok"] {{ background: {OK_BG}; border: 1px solid {OK_BORDER}; color: {ACCENT}; }}
QLabel#chip[state="bad"] {{ background: #2A1519; border: 1px solid #6B3038; color: {DANGER}; }}
QLabel#stepdot {{ background: #26303C; border-radius: 5px; min-width: 10px; max-width: 10px; min-height: 10px; max-height: 10px; }}
QLabel#stepdot[state="active"] {{ background: {ACCENT}; min-width: 28px; max-width: 28px; border-radius: 5px; }}
QLabel#stepdot[state="done"] {{ background: #2B6B60; }}
QLabel#hero {{ font-size: 24pt; font-weight: 600; }}
QPushButton {{ background: #18212B; border: 1px solid #2B3644; border-radius: 8px;
  padding: 0 18px; min-height: 40px; font-weight: 500; }}
QPushButton:hover {{ background: #1E2A37; }}
QPushButton:disabled {{ color: #5B6676; }}
QPushButton#primary {{ background: {ACCENT}; color: #06201A; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: #52E0C1; }}
QPushButton#danger {{ background: #2A1519; color: {DANGER}; border: 1px solid #6B3038; font-weight: 600; }}
QPushButton#danger:hover {{ background: #351B20; }}
QFrame#card QPushButton {{ background: #18212B; }}
QFrame#card QPushButton:hover {{ background: #1E2A37; }}
QFrame#card QPushButton#primary {{ background: {ACCENT}; }}
QFrame#card QPushButton#primary:hover {{ background: #52E0C1; }}
QFrame#card QPushButton#danger {{ background: #2A1519; }}
QFrame#card QPushButton#danger:hover {{ background: #351B20; }}
QFrame#card QPushButton#nav {{ background: transparent; }}
QFrame#card QPushButton#nav:hover {{ background: #121A22; }}
QFrame#card QPushButton#nav:checked {{ background: #18212B; }}
QPushButton#nav {{ background: transparent; border: none; text-align: left; padding: 0 14px;
  color: {MUTED}; min-height: 42px; border-radius: 8px; }}
QPushButton#nav:hover {{ background: #121A22; }}
QPushButton#nav:checked {{ background: #18212B; color: {TEXT}; }}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextBrowser {{ background: {SIDEBAR}; border: 1px solid #2B3644;
  border-radius: 8px; padding: 6px 10px; min-height: 28px; selection-background-color: #25405A; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid #2B3644; selection-background-color: #25405A; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px; border: 1px solid #3A4656; background: {SIDEBAR}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
QProgressBar {{ background: #1E2630; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QTableWidget {{ background: transparent; border: none; gridline-color: transparent; }}
QTableWidget::item {{ padding: 6px 4px; border-bottom: 1px solid #1E2630; }}
QHeaderView::section {{ background: transparent; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
  border-right: 1px solid #1B232D; padding: 8px 10px; font-weight: 500; }}
QHeaderView::section:hover {{ color: {TEXT}; background: #18212B; }}
QTableWidget::item {{ padding: 4px 10px; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ padding: 7px 4px; border-bottom: 1px solid #1E2630; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 14px; margin: 4px 3px 4px 3px; }}
QScrollBar:horizontal {{ background: transparent; height: 14px; margin: 3px 4px 3px 4px; }}
QScrollBar::handle:vertical {{ background: #2B3644; border-radius: 4px; min-height: 44px; }}
QScrollBar::handle:horizontal {{ background: #2B3644; border-radius: 4px; min-width: 44px; }}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: #3D4D62; }}
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; background: none; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QAbstractScrollArea::corner {{ background: transparent; }}
QToolButton {{ background: #18212B; border: 1px solid #2B3644; border-radius: 8px; padding: 0 14px;
  min-height: 40px; min-width: 40px; font-weight: 500; }}
QToolButton:hover {{ background: #1E2A37; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QMenu {{ background: {CARD}; border: 1px solid #2B3644; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 8px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: #25405A; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 6px 4px; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid #2B3644; }}
QDialog {{ background: {BG}; }}
"""


# ------------------------------------------------------------------ Skalierung mit der Fenstergröße
# Alles ist für 1180 × 800 entworfen (Faktor 1). Das Hauptfenster setzt den Faktor beim Größenändern (0,7–1,3); Schrift,
# Abstände und Knopfhöhen im Stylesheet sowie per track() angemeldete feste Größen im Code werden umgerechnet.
DESIGN_SIZE = (1180, 800)
SCALE_MIN, SCALE_MAX = 0.7, 1.3
_scale = 1.0
_tracked: list = []                             # (schwache Referenz, Funktion(objekt, faktor))
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)(px|pt)")


def scale() -> float:
    return _scale


def px(value: float) -> int:
    """Pixelwert im aktuellen Maßstab (mindestens 1)."""
    return max(1, round(value * _scale))


def track(obj, apply_fn) -> None:
    """Feste Größe im Code skalierbar machen: apply_fn(obj, faktor) läuft sofort und bei jeder Änderung."""
    _tracked.append((weakref.ref(obj), apply_fn))
    apply_fn(obj, _scale)


def _s(value: int, factor: float) -> int:
    return max(0, round(value * factor))


def track_margins(layout, left: int, top: int, right: int, bottom: int) -> None:
    track(layout, lambda o, f: o.setContentsMargins(_s(left, f), _s(top, f), _s(right, f), _s(bottom, f)))


def track_spacing(layout, value: int) -> None:
    track(layout, lambda o, f: o.setSpacing(_s(value, f)))


def track_min_height(widget, value: int) -> None:
    track(widget, lambda o, f: o.setMinimumHeight(_s(value, f)))


def track_min_width(widget, value: int) -> None:
    track(widget, lambda o, f: o.setMinimumWidth(_s(value, f)))


def track_fixed_width(widget, value: int) -> None:
    track(widget, lambda o, f: o.setFixedWidth(_s(value, f)))


def track_fixed_height(widget, value: int) -> None:
    track(widget, lambda o, f: o.setFixedHeight(_s(value, f)))


def style(factor: float) -> str:
    def repl(m: re.Match) -> str:
        value = float(m.group(1))
        if m.group(2) == "pt":
            return f"{value * factor:.1f}pt"
        return f"{max(1, round(value * factor)) if value else 0}px"
    return _SIZE_RE.sub(repl, STYLE)


def factor_for(width: int, height: int) -> float:
    """Faktor für eine Fenstergröße: proportional, gerundet auf 0,05 (weniger Neuberechnungen)."""
    raw = min(width / DESIGN_SIZE[0], height / DESIGN_SIZE[1])
    return round(min(SCALE_MAX, max(SCALE_MIN, raw)) * 20) / 20


def set_scale(app: QApplication, factor: float) -> bool:
    global _scale
    if abs(factor - _scale) < 0.001:
        return False
    _scale = factor
    font = QFont("Segoe UI")
    font.setPointSizeF(10 * factor)
    app.setFont(font)
    app.setStyleSheet(style(factor))
    alive = []
    for ref, fn in _tracked:
        obj = ref()
        if obj is None:
            continue
        try:
            fn(obj, factor)
            alive.append((ref, fn))
        except RuntimeError:                        # Qt-Objekt bereits gelöscht
            pass
    _tracked[:] = alive
    return True


def apply(app: QApplication) -> None:
    font = QFont("Segoe UI")
    font.setPointSizeF(10 * _scale)
    app.setFont(font)
    palette = app.palette()                     # Links (z. B. Versionshinweise): Standardblau ist auf Dunkel kaum lesbar
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor(ACCENT))
    app.setPalette(palette)
    app.setStyleSheet(style(_scale))
