"""Designs (QSS) mit Farbschemata, Skalierung und Symbolen.

Designs sind wählbar (Einstellungen → Darstellung) und tragen die Version, mit der sie eingeführt wurden. Alte Designs
bleiben erhalten; ein neues Design = neuer Eintrag in DESIGNS + Vorlage + Paletten. Farben stehen als @token in den
Vorlagen und kommen aus der Palette – Code, der selbst zeichnet, holt sie über color("token")."""
from __future__ import annotations

import re
import weakref
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication

from ..i18n import N_

# ------------------------------------------------------------------ Paletten
_CLASSIC_DARK = {
    "bg": "#0F1419", "sidebar": "#0B0F14", "topbar": "#0B0F14", "card": "#151B23", "border": "#222B36",
    "text": "#E6EAF0", "muted": "#8B97A8", "accent": "#3DD6B5", "accent2": "#3DD6B5", "accentHover": "#52E0C1",
    "accent2Hover": "#52E0C1", "onAccent": "#06201A", "warn": "#F5A524", "danger": "#FF9A9A", "okBg": "#12201E",
    "okBorder": "#1F4A42", "line": "#1E2630", "field": "#0B0F14", "control": "#18212B", "controlHover": "#1E2A37",
    "controlBorder": "#2B3644", "checkBorder": "#3A4656", "navHover": "#121A22", "navActive": "#18212B",
    "select": "#25405A", "dangerBg": "#2A1519", "dangerBorder": "#6B3038", "dangerHover": "#351B20",
    "disabled": "#5B6676", "disabledBg": "#10161D", "section": "#6F7D90", "scroll": "#2B3644", "scrollHover": "#3D4D62",
    "headerLine": "#1B232D", "stepdot": "#26303C", "stepDone": "#2B6B60", "bar": "#2B6B60", "barEmpty": "#1E2630",
    "trackOff": "#2B3644", "knobOff": "#8B97A8", "knobOn": "#06201A", "info": "#E6EAF0",
}
_ASTRAL_DARK = {
    "bg": "#0A0D13", "sidebar": "#0D1119", "topbar": "#0A0D13", "card": "#121722", "border": "#1C2331",
    "text": "#ECEFF5", "muted": "#8A94A7", "accent": "#45E0BF", "accent2": "#7B8CFF", "accentHover": "#62EACB",
    "accent2Hover": "#93A0FF", "onAccent": "#051B16", "warn": "#FFB547", "danger": "#FF8A8A", "okBg": "#0F1F1D",
    "okBorder": "#1D4A41", "line": "#181E2A", "field": "#0D121B", "control": "#181F2C", "controlHover": "#202939",
    "controlBorder": "#263043", "checkBorder": "#36425A", "navHover": "#141B27", "navActive": "#17263A",
    "select": "#24365A", "dangerBg": "#2A1419", "dangerBorder": "#6B3038", "dangerHover": "#36191F",
    "disabled": "#566175", "disabledBg": "#0F141D", "section": "#6C7891", "scroll": "#252E40", "scrollHover": "#36435C",
    "headerLine": "#1A2130", "stepdot": "#232C3B", "stepDone": "#2A6E61", "bar": "#2A6E61", "barEmpty": "#1A2130",
    "trackOff": "#283246", "knobOff": "#8A94A7", "knobOn": "#051B16", "info": "#ECEFF5",
}
_ASTRAL_LIGHT = {
    "bg": "#F3F5F9", "sidebar": "#FFFFFF", "topbar": "#F3F5F9", "card": "#FFFFFF", "border": "#E1E6EE",
    "text": "#151A23", "muted": "#5E6879", "accent": "#0EA585", "accent2": "#5566F2", "accentHover": "#11B793",
    "accent2Hover": "#6575FF", "onAccent": "#FFFFFF", "warn": "#B26A00", "danger": "#C9302C", "okBg": "#E7F7F2",
    "okBorder": "#A6DDCF", "line": "#E9EDF3", "field": "#F8FAFC", "control": "#EEF1F6", "controlHover": "#E3E8F0",
    "controlBorder": "#D4DAE4", "checkBorder": "#B9C2D0", "navHover": "#EEF2F7", "navActive": "#E3F4EF",
    "select": "#CDEBE3", "dangerBg": "#FDECEC", "dangerBorder": "#F0B6B6", "dangerHover": "#FADADA",
    "disabled": "#A2ABB9", "disabledBg": "#F0F2F6", "section": "#7A8496", "scroll": "#CDD4DF", "scrollHover": "#B4BDCB",
    "headerLine": "#E6EAF1", "stepdot": "#D8DEE8", "stepDone": "#8FD3C3", "bar": "#9AD9CA", "barEmpty": "#E6EAF0",
    "trackOff": "#CDD3DD", "knobOff": "#FFFFFF", "knobOn": "#FFFFFF", "info": "#151A23",
}

# ------------------------------------------------------------------ Vorlagen
_CLASSIC = """
QWidget { background: @bg; color: @text; font-family: @font; font-size: 10pt; }
QMainWindow, QStackedWidget { background: @bg; }
QFrame#sidebar { background: @sidebar; border-right: 1px solid @line; }
QFrame#topbar { background: @topbar; border-bottom: 1px solid @line; }
QFrame#topbar QWidget { background: transparent; }
QFrame#topbar QToolButton#slim { background: @control; min-height: 28px; padding: 0 30px 0 12px; border-radius: 7px; }
QFrame#topbar QToolButton#slim:hover { background: @controlHover; }
QFrame#topbar QToolButton#slim::menu-button { border: none; border-left: 1px solid @controlBorder; width: 22px; }
QFrame#topbar QToolButton#slim::menu-arrow { image: url("@arrow"); width: 9px; height: 6px; }
QFrame#sidebar QWidget { background: transparent; }
QFrame#card { background: @card; border: 1px solid @border; border-radius: 10px; }
QFrame#card QWidget { background: transparent; }
QFrame#statusbox { background: @okBg; border: 1px solid @okBorder; border-radius: 8px; }
QFrame#statusbox[state="off"] { background: @card; border: 1px solid @border; }
QLabel#h1 { font-size: 17pt; font-weight: 600; }
QLabel#h2 { font-size: 11pt; font-weight: 600; }
QLabel#brand { font-size: 11pt; font-weight: 600; }
QLabel#muted { color: @muted; }
QLabel#small { color: @muted; font-size: 9pt; }
QLabel#kpi { font-family: Consolas; font-size: 20pt; font-weight: 600; }
QLabel#wave { font-family: Consolas; font-size: 34pt; font-weight: 600; }
QLabel#preview { background: @sidebar; border: 1px solid @border; border-radius: 8px; color: @disabled; padding: 8px; }
QLabel#good { color: @accent; }
QLabel#bad { color: @danger; }
QLabel#warn { color: @warn; }
QLabel#chip { background: @control; border: 1px solid @controlBorder; border-radius: 12px; padding: 5px 14px; color: @muted; }
QLabel#chip[state="ok"] { background: @okBg; border: 1px solid @okBorder; color: @accent; }
QLabel#chip[state="bad"] { background: @dangerBg; border: 1px solid @dangerBorder; color: @danger; }
QLabel#stepdot { background: @stepdot; border-radius: 5px; min-width: 10px; max-width: 10px; min-height: 10px; max-height: 10px; }
QLabel#stepdot[state="active"] { background: @accent; min-width: 28px; max-width: 28px; border-radius: 5px; }
QLabel#stepdot[state="done"] { background: @stepDone; }
QLabel#hero { font-size: 24pt; font-weight: 600; }
QLabel#section { color: @section; font-size: 8.5pt; font-weight: 700; padding-top: 6px; }
QLabel#empty { color: @disabled; }
QFrame#savebar { background: @sidebar; border-top: 1px solid @line; }
QFrame#savebar QWidget { background: transparent; }
QFrame#savebar QPushButton#primary { background: @accent; }
QFrame#savebar QPushButton#primary:hover { background: @accentHover; }
QPushButton { background: @control; border: 1px solid @controlBorder; border-radius: 8px;
  padding: 0 18px; min-height: 40px; font-weight: 500; }
QPushButton:hover { background: @controlHover; }
QPushButton:disabled { color: @disabled; }
QPushButton#primary { background: @accent; color: @onAccent; border: 1px solid @accent; font-weight: 600; }
QPushButton#primary:hover { background: @accentHover; }
QPushButton#primary:disabled { background: @control; color: @disabled; border: 1px solid @controlBorder; }
QPushButton#danger { background: @dangerBg; color: @danger; border: 1px solid @dangerBorder; font-weight: 600; }
QPushButton#danger:hover { background: @dangerHover; }
QPushButton#chipbtn { min-height: 30px; padding: 0 12px; border-radius: 15px; }
QPushButton#chipbtn:checked { background: @navActive; border: 1px solid @accent; color: @accent; }
QFrame#card QPushButton { background: @control; }
QFrame#card QPushButton:hover { background: @controlHover; }
QFrame#card QPushButton#primary { background: @accent; }
QFrame#card QPushButton#primary:hover { background: @accentHover; }
QFrame#card QPushButton#danger { background: @dangerBg; }
QFrame#card QPushButton#danger:hover { background: @dangerHover; }
QFrame#card QPushButton#nav, QFrame#card QPushButton#tab { background: transparent; }
QFrame#card QPushButton#nav:hover, QFrame#card QPushButton#tab:hover { background: @navHover; }
QFrame#card QPushButton#nav:checked, QFrame#card QPushButton#tab:checked { background: @navActive; }
QFrame#card QPushButton#chipbtn:checked { background: @navActive; }
QPushButton#nav, QPushButton#tab { background: transparent; border: none; text-align: left; padding: 0 14px;
  color: @muted; min-height: 42px; border-radius: 8px; }
QPushButton#nav:hover, QPushButton#tab:hover { background: @navHover; }
QPushButton#nav:checked, QPushButton#tab:checked { background: @navActive; color: @text; }
QToolButton#info, QFrame#card QToolButton#info { background: transparent; border: 1px solid @controlBorder;
  border-radius: 9px; min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; padding: 0;
  color: @muted; font-size: 8pt; font-weight: 700; }
QToolButton#info:hover, QFrame#card QToolButton#info:hover { color: @accent; border: 1px solid @accent; }
QToolButton#gear { background: transparent; border: none; border-radius: 8px; min-height: 40px; min-width: 40px; }
QToolButton#gear:hover { background: @navHover; }
QToolButton#gear:checked { background: @navActive; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextBrowser { background: @field;
  border: 1px solid @controlBorder; border-radius: 8px; padding: 6px 10px; min-height: 28px;
  selection-background-color: @select; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid @accent; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QCheckBox:disabled, QLabel:disabled { color: @disabled; }
QCheckBox::indicator:disabled { background: @disabledBg; border: 1px solid @border; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none;
  background: transparent; }
QComboBox::down-arrow { image: url("@arrow"); width: 10px; height: 6px; }
QComboBox QAbstractItemView { background: @card; border: 1px solid @controlBorder; selection-background-color: @select; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 1px solid @checkBorder; background: @field; }
QCheckBox::indicator:checked { background: @accent; border: 1px solid @accent; }
QProgressBar { background: @line; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; color: transparent; }
QProgressBar::chunk { background: @accent; border-radius: 4px; }
QTableWidget { background: transparent; border: none; gridline-color: transparent; }
QHeaderView::section { background: transparent; color: @muted; border: none; border-bottom: 1px solid @border;
  border-right: 1px solid @headerLine; padding: 8px 10px; font-weight: 500; }
QHeaderView::section:hover { color: @text; background: @control; }
QTableWidget::item { padding: 4px 10px; border-bottom: 1px solid @line; }
QTableWidget::item:selected { background: @select; color: @text; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 7px 4px; border-bottom: 1px solid @line; }
QListWidget::item:selected { background: @select; color: @text; border-radius: 6px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 14px; margin: 4px 3px 4px 3px; }
QScrollBar:horizontal { background: transparent; height: 14px; margin: 3px 4px 3px 4px; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 4px; min-height: 44px; }
QScrollBar::handle:horizontal { background: @scroll; border-radius: 4px; min-width: 44px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: @scrollHover; }
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed { background: @accent; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: none; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QAbstractScrollArea::corner { background: transparent; }
QToolButton { background: @control; border: 1px solid @controlBorder; border-radius: 8px; padding: 0 14px;
  min-height: 40px; min-width: 40px; font-weight: 500; }
QToolButton:hover { background: @controlHover; }
QToolButton::menu-indicator { image: none; width: 0; }
QMenu { background: @card; border: 1px solid @controlBorder; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 8px 18px; border-radius: 6px; }
QMenu::item:selected { background: @select; }
QMenu::separator { height: 1px; background: @border; margin: 6px 4px; }
QToolTip { background: @card; color: @text; border: 1px solid @controlBorder; }
QDialog { background: @bg; }
"""

# Astral (0.6.5): weichere Flächen, größere Rundungen, Verlauf auf Hauptknöpfen, Symbole in der Navigation,
# Einstellungen als Zahnrad unten links, schmale Bildlaufleisten. Hell und Dunkel aus derselben Vorlage.
_ASTRAL = """
QWidget { background: @bg; color: @text; font-family: @font; font-size: 10pt; }
QMainWindow, QStackedWidget { background: @bg; }
QFrame#sidebar { background: @sidebar; border-right: 1px solid @line; }
QFrame#topbar { background: @topbar; border-bottom: 1px solid @line; }
QFrame#topbar QWidget, QFrame#sidebar QWidget { background: transparent; }
QFrame#topbar QToolButton#slim { background: @control; border: 1px solid @controlBorder; min-height: 30px;
  padding: 0 32px 0 14px; border-radius: 15px; font-weight: 600; }
QFrame#topbar QToolButton#slim:hover { background: @controlHover; }
QFrame#topbar QToolButton#slim::menu-button { border: none; border-left: 1px solid @controlBorder; width: 24px;
  border-top-right-radius: 15px; border-bottom-right-radius: 15px; }
QFrame#topbar QToolButton#slim::menu-button:hover { background: @controlHover; }
QFrame#topbar QToolButton#slim::menu-arrow { image: url("@arrow"); width: 9px; height: 6px; }
QFrame#card { background: @card; border: 1px solid @border; border-radius: 14px; }
QFrame#card QWidget { background: transparent; }
QFrame#statusbox { background: @okBg; border: 1px solid @okBorder; border-radius: 12px; }
QFrame#statusbox[state="off"] { background: @card; border: 1px solid @border; }
QLabel#h1 { font-size: 19pt; font-weight: 700; }
QLabel#h2 { font-size: 11pt; font-weight: 600; }
QLabel#brand { font-size: 12pt; font-weight: 700; color: @text; }
QFrame#topbar QLabel#brandmark { background: transparent; }
QLabel#muted { color: @muted; }
QLabel#small { color: @muted; font-size: 9pt; }
QLabel#kpi { font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 21pt; font-weight: 700; }
QLabel#wave { font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 38pt; font-weight: 700; }
QLabel#preview { background: @field; border: 1px dashed @controlBorder; border-radius: 12px; color: @disabled;
  padding: 10px; }
QLabel#good { color: @accent; }
QLabel#bad { color: @danger; }
QLabel#warn { color: @warn; }
QLabel#chip { background: @control; border: 1px solid @controlBorder; border-radius: 13px; padding: 5px 14px; color: @muted; }
QLabel#chip[state="ok"] { background: @okBg; border: 1px solid @okBorder; color: @accent; }
QLabel#chip[state="bad"] { background: @dangerBg; border: 1px solid @dangerBorder; color: @danger; }
QLabel#stepdot { background: @stepdot; border-radius: 5px; min-width: 10px; max-width: 10px; min-height: 10px; max-height: 10px; }
QLabel#stepdot[state="active"] { background: @accent; min-width: 28px; max-width: 28px; border-radius: 5px; }
QLabel#stepdot[state="done"] { background: @stepDone; }
QLabel#hero { font-size: 25pt; font-weight: 700; }
QLabel#section { color: @section; font-size: 8.5pt; font-weight: 700; padding-top: 8px; }
QLabel#empty { color: @disabled; }
QFrame#savebar { background: @sidebar; border-top: 1px solid @line; }
QFrame#savebar QWidget { background: transparent; }
QPushButton { background: @control; border: 1px solid @controlBorder; border-radius: 10px;
  padding: 0 18px; min-height: 38px; font-weight: 600; }
QPushButton:hover { background: @controlHover; }
QPushButton:pressed { background: @control; padding-top: 1px; }
QPushButton:disabled { color: @disabled; }
QPushButton#primary, QFrame#card QPushButton#primary, QFrame#savebar QPushButton#primary {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @accent, stop:1 @accent2);
  color: @onAccent; border: none; font-weight: 700; }
QPushButton#primary:hover, QFrame#card QPushButton#primary:hover, QFrame#savebar QPushButton#primary:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @accentHover, stop:1 @accent2Hover); }
QPushButton#primary:disabled, QFrame#card QPushButton#primary:disabled { background: @control; color: @disabled; }
QPushButton#danger, QFrame#card QPushButton#danger { background: @dangerBg; color: @danger;
  border: 1px solid @dangerBorder; font-weight: 700; }
QPushButton#danger:hover, QFrame#card QPushButton#danger:hover { background: @dangerHover; }
QFrame#card QPushButton { background: @control; }
QFrame#card QPushButton:hover { background: @controlHover; }
QPushButton#chipbtn { min-height: 30px; padding: 0 12px; border-radius: 15px; font-weight: 600; }
QPushButton#chipbtn:checked, QFrame#card QPushButton#chipbtn:checked { background: @navActive;
  border: 1px solid @accent; color: @accent; }
QPushButton#nav { background: transparent; border: none; text-align: left; padding: 0 12px;
  color: @muted; min-height: 40px; border-radius: 10px; font-weight: 600; }
QPushButton#nav:hover { background: @navHover; color: @text; }
QPushButton#nav:checked { background: @navActive; color: @text; }
QPushButton#tab, QFrame#card QPushButton#tab { background: transparent; border: none; padding: 0 14px; color: @muted;
  min-height: 32px; border-radius: 16px; font-weight: 600; }
QPushButton#tab:hover, QFrame#card QPushButton#tab:hover { background: @navHover; color: @text; }
QPushButton#tab:checked, QFrame#card QPushButton#tab:checked { background: @navActive; color: @accent; }
QToolButton#info, QFrame#card QToolButton#info { background: transparent; border: 1px solid @controlBorder;
  border-radius: 9px; min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; padding: 0;
  color: @muted; font-size: 8pt; font-weight: 700; }
QToolButton#info:hover, QFrame#card QToolButton#info:hover { color: @accent; border: 1px solid @accent; }
QToolButton#gear { background: transparent; border: none; border-radius: 12px; min-height: 44px; min-width: 44px;
  padding: 0; }
QToolButton#gear:hover { background: @navHover; }
QToolButton#gear:checked { background: @navActive; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextBrowser { background: @field;
  border: 1px solid @controlBorder; border-radius: 10px; padding: 6px 12px; min-height: 26px;
  selection-background-color: @select; selection-color: @text; }
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover { border: 1px solid @checkBorder; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid @accent; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QCheckBox:disabled, QLabel:disabled { color: @disabled; }
QCheckBox::indicator:disabled { background: @disabledBg; border: 1px solid @border; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }
QComboBox { padding-right: 30px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 28px; border: none;
  background: transparent; }
QComboBox::down-arrow { image: url("@arrow"); width: 10px; height: 6px; }
QComboBox QAbstractItemView { background: @card; border: 1px solid @controlBorder; border-radius: 10px; padding: 4px;
  selection-background-color: @select; selection-color: @text; outline: none; }
QCheckBox { spacing: 10px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 6px; border: 1px solid @checkBorder; background: @field; }
QCheckBox::indicator:hover { border: 1px solid @accent; }
QCheckBox::indicator:checked { background: @accent; border: 1px solid @accent; image: url("@check"); }
QProgressBar { background: @line; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; color: transparent; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @accent, stop:1 @accent2); border-radius: 4px; }
QTableWidget { background: transparent; border: none; gridline-color: transparent; }
QHeaderView::section { background: transparent; color: @muted; border: none; border-bottom: 1px solid @border;
  padding: 8px 10px; font-weight: 600; }
QHeaderView::section:hover { color: @text; }
QTableWidget::item { padding: 4px 10px; border-bottom: 1px solid @line; }
QTableWidget::item:selected { background: @select; color: @text; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 8px 6px; border-bottom: 1px solid @line; }
QListWidget::item:hover { background: @navHover; border-radius: 8px; }
QListWidget::item:selected { background: @navActive; color: @text; border-radius: 8px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 6px 2px 6px 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px 6px 2px 6px; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 3px; min-height: 40px; }
QScrollBar::handle:horizontal { background: @scroll; border-radius: 3px; min-width: 40px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: @scrollHover; }
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed { background: @accent; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: none; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QAbstractScrollArea::corner { background: transparent; }
QToolButton { background: @control; border: 1px solid @controlBorder; border-radius: 10px; padding: 0 14px;
  min-height: 38px; min-width: 38px; font-weight: 600; }
QToolButton:hover { background: @controlHover; }
QToolButton::menu-indicator { image: none; width: 0; }
QMenu { background: @card; border: 1px solid @controlBorder; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 8px 20px; border-radius: 8px; }
QMenu::item:selected { background: @navActive; }
QMenu::separator { height: 1px; background: @border; margin: 6px 6px; }
QMenu::indicator { width: 14px; height: 14px; }
QToolTip { background: @card; color: @text; border: 1px solid @controlBorder; padding: 4px 6px; }
QDialog { background: @bg; }
"""

# Nebula (0.7.0): aus dem Logo abgeleitet – tiefes Nachtblau, Verlauf Türkis → Violett, weiße Akzente. Eigenes Layout:
# schmale Symbolleiste (Logo oben, Zahnrad unten, Namen als Tooltip), Status als Pille in der Kopfzeile,
# Karten mit Verlaufsrand. Baut auf der Astral-Vorlage auf; die Regeln unten überschreiben sie.
_NEBULA_DARK = dict(_ASTRAL_DARK, **{
    "bg": "#080A11", "sidebar": "#0B0E17", "topbar": "#080A11", "card": "#10141F", "cardTop": "#141A29",
    "border": "#1D2436", "borderA": "#2C3A5C", "borderB": "#1A2031", "line": "#151A27", "field": "#0C1019",
    "control": "#161C2B", "controlHover": "#1F2739", "controlBorder": "#262F45", "navHover": "#141A28",
    "navActive": "#18223A", "softA": "#163A3A", "softB": "#252A55", "edge": "#3B4A7A", "select": "#24305A",
    "section": "#7D88B5", "okBg": "#0D1D1E", "okBorder": "#1E5148", "scroll": "#232B40", "text": "#EEF1FA",
})
_NEBULA_LIGHT = dict(_ASTRAL_LIGHT, **{
    "bg": "#F4F5FB", "sidebar": "#FFFFFF", "topbar": "#F4F5FB", "card": "#FFFFFF", "cardTop": "#FBFBFF",
    "border": "#E3E6F2", "borderA": "#D7DCF0", "borderB": "#EEEAFB", "line": "#ECEEF6", "navHover": "#F0F2FA",
    "navActive": "#E8EBFB", "softA": "#DDF5EF", "softB": "#E4E6FD", "edge": "#B9C1EE", "section": "#7A82A6",
})
_NEBULA = _ASTRAL + """
QFrame#sidebar { background: @sidebar; border-right: 1px solid @line; }
QFrame#card { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 @cardTop, stop:1 @card);
  border: 1px solid qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @borderA, stop:1 @borderB); border-radius: 16px; }
QPushButton#nav { min-height: 46px; max-height: 46px; min-width: 46px; max-width: 46px; padding: 0;
  border-radius: 14px; text-align: center; }
QPushButton#nav:hover { background: @navHover; }
QPushButton#nav:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @softA, stop:1 @softB);
  border: 1px solid @edge; }
QToolButton#gear { min-height: 46px; max-height: 46px; min-width: 46px; max-width: 46px; border-radius: 14px; }
QToolButton#gear:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @softA, stop:1 @softB);
  border: 1px solid @edge; }
QFrame#pill { background: @control; border: 1px solid @controlBorder; border-radius: 15px; }
QFrame#pill[state="on"] { background: @okBg; border: 1px solid @accent; }
QFrame#pill[state="paused"] { border: 1px solid @warn; }
QFrame#pill QLabel { background: transparent; }
QLabel#h1 { font-size: 20pt; font-weight: 800; }
QLabel#section { color: @section; }
QFrame#card[kpi="true"] { border-top: 2px solid qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @accent, stop:1 @accent2); }
QFrame#statusbox { border-radius: 14px; }
"""

# Saison-Designs (0.7.2): Nebula-Aufbau mit eigenen Farben
_HALLOWEEN_DARK = dict(_NEBULA_DARK, **{
    "bg": "#120A1A", "sidebar": "#170C21", "topbar": "#120A1A", "card": "#1F1029", "cardTop": "#2A1538",
    "border": "#3A1F4D", "borderA": "#7A3FA8", "borderB": "#3A1F4D", "line": "#26152F", "field": "#140A1C",
    "control": "#2A1638", "controlHover": "#36204A", "controlBorder": "#4A2A63", "navHover": "#2A1638",
    "navActive": "#3D1D52", "softA": "#5A2A0E", "softB": "#3F1A63", "edge": "#B5651D", "select": "#5A2C7A",
    "accent": "#FF7A1A", "accent2": "#B04DFF", "accentHover": "#FF9442", "accent2Hover": "#C470FF",
    "onAccent": "#1A0A00", "knobOn": "#1A0A00", "okBg": "#2A1408", "okBorder": "#7A3A12", "bar": "#C0561C",
    "stepDone": "#C0561C", "section": "#C89BF0", "muted": "#B8A5C9", "scroll": "#3E2550", "warn": "#FFD25A",
    "cardGlass": "#D81F1029", "cardTopGlass": "#D82A1538",          # leicht durchscheinend (Deko dahinter)
})
_WINTER_DARK = dict(_NEBULA_DARK, **{
    "bg": "#06111F", "sidebar": "#081628", "topbar": "#06111F", "card": "#0C1D33", "cardTop": "#122A48",
    "border": "#1C3557", "borderA": "#3C78B8", "borderB": "#1C3557", "line": "#0F2238", "field": "#081A2E",
    "control": "#11253F", "controlHover": "#18304F", "controlBorder": "#25456B", "navHover": "#10233B",
    "navActive": "#16345A", "softA": "#14466B", "softB": "#23336B", "edge": "#5AA8E6", "select": "#1F4C7A",
    "accent": "#7FE0FF", "accent2": "#A99BFF", "accentHover": "#A3EAFF", "accent2Hover": "#BFB4FF",
    "onAccent": "#04121D", "knobOn": "#04121D", "okBg": "#0A2236", "okBorder": "#2A6A96", "bar": "#2F86C0",
    "stepDone": "#2F86C0", "section": "#9CC4EC", "muted": "#93A9C4", "scroll": "#1F3A5C",
    "cardGlass": "#D80C1D33", "cardTopGlass": "#D8122A48",
})
_WINTER_LIGHT = dict(_NEBULA_LIGHT, **{
    "bg": "#EAF4FD", "topbar": "#EAF4FD", "sidebar": "#F5FAFF", "border": "#D3E4F3", "accent": "#0B86D6",
    "accent2": "#5E6CFF", "accentHover": "#1C97E6", "accent2Hover": "#7280FF", "softA": "#CDEBFC",
    "softB": "#DCE0FE", "edge": "#8CC3EC", "bar": "#7DBDEB", "select": "#C2E1F7", "okBg": "#E2F2FC",
    "okBorder": "#9CCDEE", "navActive": "#D6EBFB", "stepDone": "#7DBDEB", "section": "#5D86AD",
    "cardGlass": "#E6FFFFFF", "cardTopGlass": "#E6F7FBFF",
})

# OLED (0.7.6): echtes Schwarz, Nebula-Aufbau
_OLED_DARK = dict(_NEBULA_DARK, **{
    "bg": "#000000", "sidebar": "#000000", "topbar": "#000000", "card": "#08090C", "cardTop": "#0C0E13",
    "border": "#16181F", "borderA": "#232838", "borderB": "#111319", "line": "#0E1015", "field": "#030405",
    "control": "#0F1116", "controlHover": "#171A22", "controlBorder": "#1D212B", "navHover": "#0C0E13",
    "navActive": "#121620", "okBg": "#03100D", "dangerBg": "#160709", "disabledBg": "#050608",
    "headerLine": "#101219", "barEmpty": "#0E1015", "scroll": "#1A1D26", "trackOff": "#1A1D26",
})

# Bubble (0.7.6): Nebula mit runden „Blasen“-Formen – Knöpfe und Felder als Pillen, große Kartenradien
_BUBBLE = _NEBULA + """
QFrame#card { border-radius: 26px; }
QFrame#statusbox { border-radius: 22px; }
QPushButton, QToolButton { border-radius: 19px; }
QPushButton#nav, QToolButton#gear { border-radius: 23px; }
QPushButton#chipbtn { border-radius: 15px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { border-radius: 19px; padding: 6px 16px; }
QComboBox { padding-right: 30px; }
QPlainTextEdit, QTextBrowser { border-radius: 18px; }
QComboBox QAbstractItemView { border-radius: 16px; }
QMenu { border-radius: 18px; }
QMenu::item { border-radius: 12px; }
QCheckBox::indicator { border-radius: 9px; }
QListWidget::item:hover, QListWidget::item:selected { border-radius: 14px; }
QLabel#preview { border-radius: 20px; }
QFrame#pill { border-radius: 16px; }
"""

# Saison-Designs: Karten leicht durchscheinend, damit die Deko (seasonal.py) dahinter sichtbar ist
_SEASON = _NEBULA + """
QFrame#card { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 @cardTopGlass, stop:1 @cardGlass); }
"""

DESIGNS: dict[str, dict] = {
    # Schlüssel: Anzeigename, eingeführt in Version, Vorlage, Paletten je Farbschema (fehlt eines: Dunkel)
    "nebula": {"name": N_("Nebula"), "since": "0.7.0", "template": _NEBULA, "icons": True, "gear": True,
               "animate": True, "rail": True, "font": ["Segoe UI Variable Text", "Segoe UI"],
               "palettes": {"dark": _NEBULA_DARK, "light": _NEBULA_LIGHT}},
    "astral": {"name": N_("Astral"), "since": "0.6.5", "template": _ASTRAL, "icons": True, "gear": True,
               "animate": True, "font": ["Segoe UI Variable Text", "Segoe UI"],
               "palettes": {"dark": _ASTRAL_DARK, "light": _ASTRAL_LIGHT}},
    "bubble": {"name": N_("Bubble"), "since": "0.7.6", "template": _BUBBLE, "icons": True, "gear": True,
               "animate": True, "rail": True, "font": ["Segoe UI Variable Text", "Segoe UI"],
               "palettes": {"dark": _NEBULA_DARK, "light": _NEBULA_LIGHT}},
    "oled": {"name": N_("OLED"), "since": "0.7.6", "template": _NEBULA, "icons": True, "gear": True,
             "animate": True, "rail": True, "font": ["Segoe UI Variable Text", "Segoe UI"],
             "palettes": {"dark": _OLED_DARK}},
    "halloween": {"name": N_("Kürbisnacht"), "since": "0.7.2", "template": _SEASON, "icons": True, "gear": True,
                  "animate": True, "rail": True, "font": ["Segoe UI Variable Text", "Segoe UI"],
                  "palettes": {"dark": _HALLOWEEN_DARK}, "season": ((10, 15), (11, 2)), "decor": "halloween"},
    "winter": {"name": N_("Frost"), "since": "0.7.2", "template": _SEASON, "icons": True, "gear": True,
               "animate": True, "rail": True, "font": ["Segoe UI Variable Text", "Segoe UI"],
               "palettes": {"dark": _WINTER_DARK, "light": _WINTER_LIGHT}, "season": ((12, 1), (1, 6)),
               "decor": "winter"},
    "classic": {"name": N_("Klassisch"), "since": "0.5.0", "template": _CLASSIC, "icons": False, "gear": False,
                "animate": False, "font": ["Segoe UI"], "palettes": {"dark": _CLASSIC_DARK}},
}
DEFAULT_DESIGN = "nebula"


def season_design(today=None) -> str:
    """Saison-Design für ein Datum („“ = keine Saison): Kürbisnacht 15.10.–2.11., Frost 1.12.–6.1."""
    from datetime import date
    today = today or date.today()
    md = (today.month, today.day)
    for key, info in DESIGNS.items():
        if "season" not in info:
            continue
        start, end = info["season"]
        if (start <= md <= end) if start <= end else (md >= start or md <= end):
            return key
    return ""


def effective_design(chosen: str, seasonal: bool, today=None) -> str:
    """Gewähltes Design – oder während einer Saison das Saison-Design, wenn „automatisch“ an ist."""
    return (season_design(today) or chosen) if seasonal else chosen
MODES = ("dark", "light", "system")

_design = DEFAULT_DESIGN
_mode = "dark"
_palette = _NEBULA_DARK
_listeners: list = []                          # Rückrufe bei Design-/Farbwechsel (schwache Referenzen)



def design() -> str:
    return _design


_motion = True                                     # False = „Animationen reduzieren“


def set_motion(on: bool) -> None:
    global _motion
    _motion = bool(on)


def animations() -> bool:
    """Animationen zeigen? (Design sieht sie vor und der Nutzer hat sie nicht abgeschaltet)"""
    return _motion and bool(design_info()["animate"])


def design_info(key: str | None = None) -> dict:
    return DESIGNS.get(key or _design, DESIGNS[DEFAULT_DESIGN])


def has_mode(design_key: str, mode: str) -> bool:
    return mode in design_info(design_key)["palettes"]


def color(token: str) -> str:
    return _palette.get(token, "#FF00FF")


def is_dark() -> bool:
    return QColor(_palette["bg"]).lightness() < 128


def on_change(callback: Callable[[], None]) -> None:
    """callback() nach jedem Design-/Farbwechsel (z. B. Symbole neu einfärben)."""
    ref = weakref.WeakMethod(callback) if hasattr(callback, "__self__") else (lambda cb=callback: cb)
    _listeners.append(ref)


def _system_mode() -> str:
    try:
        hints = QApplication.styleHints()
        return "light" if hints.colorScheme() == Qt.ColorScheme.Light else "dark"
    except Exception:
        return "dark"


def _resolve(design_key: str, mode: str) -> tuple[str, dict]:
    info = design_info(design_key)
    effective = _system_mode() if mode == "system" else mode
    palettes = info["palettes"]
    palette = palettes.get(effective, palettes["dark"])
    return effective, with_accent(palette, _accent) if _accent else palette


# Eigene Akzentfarbe (leer = Farbe des Designs). Vorschläge für die Auswahl in den Einstellungen.
ACCENTS = ["#45E0BF", "#7B8CFF", "#FF6FB5", "#FFB547", "#4FB3FF", "#7BE07B", "#FF7A6B"]
_accent = ""


def set_accent(value: str) -> None:
    global _accent
    _accent = value if QColor.isValidColorName(value or "") and (value or "").startswith("#") else ""


def with_accent(palette: dict, accent: str) -> dict:
    """Palette mit eigener Akzentfarbe: zweite Verlaufsfarbe um 40° im Farbkreis versetzt, Schrift auf dem Akzent
    automatisch hell/dunkel, getönte Hintergründe passend zur Helligkeit des Designs."""
    base = QColor(accent)
    h, s, v, _a = base.getHsv()
    second = QColor.fromHsv((h + 40) % 360 if h >= 0 else 0, s, v)
    dark_bg = QColor(palette["bg"]).lightness() < 128

    def mix(a: QColor, b: str, t: float) -> str:
        c = QColor(b)
        return QColor(round(a.red() * t + c.red() * (1 - t)), round(a.green() * t + c.green() * (1 - t)),
                      round(a.blue() * t + c.blue() * (1 - t))).name().upper()

    out = dict(palette)
    out.update({
        "accent": base.name().upper(), "accent2": second.name().upper(),
        "accentHover": base.lighter(112).name().upper(), "accent2Hover": second.lighter(112).name().upper(),
        "onAccent": "#0B0E14" if base.lightness() > 150 else "#FFFFFF",
    })
    for key, t in (("softA", 0.22 if dark_bg else 0.16), ("softB", 0.16 if dark_bg else 0.12),
                   ("okBg", 0.10), ("okBorder", 0.40)):
        if key in palette:
            out[key] = mix(base if key != "softB" else second, palette["bg"], t)
    return out


# ------------------------------------------------------------------ Skalierung
# Entworfen für 1180 × 800 (Faktor 1). Faktor = Zoom (50–200 %, Einstellungen) × optional Anpassung an die
# Fenstergröße (0,7–1,3). Schrift, Abstände und Knopfhöhen im Stylesheet sowie per track() angemeldete feste Größen im
# Code werden umgerechnet.
DESIGN_SIZE = (1180, 800)
SCALE_MIN, SCALE_MAX = 0.7, 1.3                # nur der Anteil „an Fenstergröße anpassen“
ZOOM_MIN, ZOOM_MAX = 50, 200
_scale = 1.0
_tracked: list = []                            # (schwache Referenz, Funktion(objekt, faktor))
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)(px|pt)")
_TOKEN_RE = re.compile(r"@([A-Za-z][A-Za-z0-9]*)")


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


def factor_for(width: int, height: int, zoom: int = 100, fit: bool = True) -> float:
    """Gesamtfaktor: Zoom in Prozent × (Fensteranpassung 0,7–1,3, falls an); gerundet auf 0,05."""
    fitted = min(SCALE_MAX, max(SCALE_MIN, min(width / DESIGN_SIZE[0], height / DESIGN_SIZE[1]))) if fit else 1.0
    zoom = min(ZOOM_MAX, max(ZOOM_MIN, int(zoom)))
    return max(0.35, round(fitted * zoom / 100 * 20) / 20)


# ------------------------------------------------------------------ Bilder für das Stylesheet
_images: dict[str, str] = {}


def _image(kind: str, rgb: str) -> str:
    """Kleine Hilfsbilder (Pfeil, Haken) in der Palettenfarbe – Qt-Stylesheets brauchen dafür Dateien."""
    key = f"{kind}_{rgb.lstrip('#')}"
    if key in _images:
        return _images[key]
    import tempfile
    from pathlib import Path

    path = Path(tempfile.gettempdir()) / f"anime_astral_{key}.png"
    try:
        pix = QPixmap(32, 32 if kind == "check" else 18)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if kind == "arrow":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(rgb))
            p.drawPolygon(QPolygonF([QPointF(2, 3), QPointF(30, 3), QPointF(16, 16)]))
        else:
            from PySide6.QtGui import QPen
            p.setPen(QPen(QColor(rgb), 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPolyline(QPolygonF([QPointF(7, 17), QPointF(13, 23), QPointF(25, 10)]))
        p.end()
        pix.save(str(path), "PNG")
        _images[key] = path.as_posix()
    except Exception:
        _images[key] = ""
    return _images[key]


def style(factor: float) -> str:
    info = design_info()
    pal = dict(_palette)
    pal["arrow"] = _image("arrow", pal["muted"])
    pal["check"] = _image("check", pal["onAccent"])
    pal["font"] = ", ".join(f'"{f}"' for f in info["font"])
    text = _TOKEN_RE.sub(lambda m: pal.get(m.group(1), m.group(0)), info["template"])

    def repl(m: re.Match) -> str:
        value = float(m.group(1))
        if m.group(2) == "pt":
            return f"{value * factor:.1f}pt"
        return f"{max(1, round(value * factor)) if value else 0}px"
    text = _SIZE_RE.sub(repl, text)
    if _backdrop:                                   # Hintergrundbild: Flächen zwischen den Karten durchsichtig
        text += '\n*[glass="true"] { background: transparent; }\n'
    return text


_backdrop = False


def set_backdrop(on: bool) -> None:
    """Hintergrundbild an/aus – Stylesheet neu setzen, wenn sich etwas ändert."""
    global _backdrop
    if bool(on) == _backdrop:
        return
    _backdrop = bool(on)
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(style(_scale))


def _font(factor: float) -> QFont:
    font = QFont()
    font.setFamilies(design_info()["font"])
    font.setPointSizeF(10 * factor)
    return font


def _apply_palette(app: QApplication) -> None:
    palette = app.palette()
    for role, token in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
                        (QPalette.ColorRole.Base, "field"), (QPalette.ColorRole.Text, "text"),
                        (QPalette.ColorRole.Button, "control"), (QPalette.ColorRole.ButtonText, "text"),
                        (QPalette.ColorRole.Highlight, "select"), (QPalette.ColorRole.HighlightedText, "text"),
                        (QPalette.ColorRole.Link, "accent"), (QPalette.ColorRole.LinkVisited, "accent"),
                        (QPalette.ColorRole.ToolTipBase, "card"), (QPalette.ColorRole.ToolTipText, "text"),
                        (QPalette.ColorRole.PlaceholderText, "disabled")):
        palette.setColor(role, QColor(color(token)))
    app.setPalette(palette)


def set_scale(app: QApplication, factor: float) -> bool:
    global _scale
    if abs(factor - _scale) < 0.001:
        return False
    _scale = factor
    app.setFont(_font(factor))
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


def set_appearance(app: QApplication, design_key: str, mode: str) -> bool:
    """Design und Farbschema wechseln (sofort, ohne Neustart). Rückgabe: geändert?"""
    global _design, _mode, _palette
    design_key = design_key if design_key in DESIGNS else DEFAULT_DESIGN
    mode = mode if mode in MODES else "dark"
    _effective, palette = _resolve(design_key, mode)
    if design_key == _design and mode == _mode and palette is _palette:
        return False
    _design, _mode, _palette = design_key, mode, palette
    app.setFont(_font(_scale))
    _apply_palette(app)
    app.setStyleSheet(style(_scale))
    alive = []
    for ref in _listeners:
        cb = ref()
        if cb is None:
            continue
        try:
            cb()
            alive.append(ref)
        except RuntimeError:
            pass
    _listeners[:] = alive
    return True


def apply(app: QApplication, design_key: str = DEFAULT_DESIGN, mode: str = "dark") -> None:
    global _design, _mode, _palette
    _design = design_key if design_key in DESIGNS else DEFAULT_DESIGN
    _mode = mode if mode in MODES else "dark"
    _effective, _palette = _resolve(_design, _mode)
    app.setFont(_font(_scale))
    _apply_palette(app)
    app.setStyleSheet(style(_scale))


# ------------------------------------------------------------------ Symbole (Windows-Symbolschrift)
ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
GLYPHS = {"monitor": "", "stats": "", "alerts": "", "raids": "", "detect": "",
          "settings": "", "notes": chr(0xE70B)}


def glyph_icon(name: str, size: int = 18) -> QIcon:
    """Symbol aus der Windows-Symbolschrift, normal in „muted“, aktiv/ausgewählt in „text“ bzw. „accent“."""
    glyph = GLYPHS.get(name, "")
    icon = QIcon()
    if not glyph:
        return icon
    for state, token in ((QIcon.State.Off, "muted"), (QIcon.State.On, "accent")):
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
            icon.addPixmap(_glyph_pixmap(glyph, color("text") if mode == QIcon.Mode.Active and state == QIcon.State.Off
                                         else color(token), size), mode, state)
    return icon


def _glyph_pixmap(glyph: str, rgb: str, size: int) -> QPixmap:
    ratio = 2.0                                     # scharf auch bei 150–200 % Windows-Skalierung
    pix = QPixmap(int(size * ratio), int(size * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont()
    font.setFamilies(list(ICON_FONTS))
    font.setPixelSize(int(size * 0.9))
    p.setFont(font)
    p.setPen(QColor(rgb))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    return pix
