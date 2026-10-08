"""„Funde prüfen“ nach dem Erkunden – mit Markier-Werkzeug (Wunsch des Eigentümers 08.10.2026): Fensterbild groß,
mit der Maus Rahmen ziehen und jedem eine Art (Knopf, nie drücken, Schalter, Wert, Fortschritt, Liste, Reiter, Info)
und einen Text geben; dazu Art und Beschreibung des ganzen Fensters. Das Programm nutzt die Markierungen selbst
(review.py: „nie drücken“ = Sperrzone, „Liste“ = dort scrollen, Knöpfe/Schalter in der Karte)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QTextEdit, QVBoxLayout, QWidget)

from .. import app_paths, review
from ..i18n import tr
from ..knowledge import CATEGORIES
from . import theme
from .widgets import label

KIND_COLORS = {"button": "#36d399", "never": "#ff4d6d", "toggle": "#5ab0ff", "value": "#ffd166",
               "progress": "#c084fc", "list": "#f97316", "tab": "#22d3ee", "info": "#e5e7eb"}


class AnnotCanvas(QWidget):
    """Fensterbild mit Rahmen; Ziehen = neuer Rahmen, Klick in einen Rahmen = auswählen."""
    created = Signal(list)
    selected = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.pix = QPixmap()
        self.annots: list[dict] = []
        self.current = -1
        self._start: Optional[QPointF] = None
        self._end: Optional[QPointF] = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        theme.track_min_height(self, 260)

    def set_image(self, path: str, annots: list[dict]) -> None:
        self.pix = QPixmap(path) if path and Path(path).is_file() else QPixmap()
        self.annots, self.current = annots, -1
        self.update()

    def _area(self) -> QRectF:
        if self.pix.isNull():
            return QRectF(self.rect())
        s = min(self.width() / self.pix.width(), self.height() / self.pix.height())
        w, h = self.pix.width() * s, self.pix.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _rel(self, p: QPointF) -> tuple[float, float]:
        a = self._area()
        return (min(1.0, max(0.0, (p.x() - a.x()) / a.width())), min(1.0, max(0.0, (p.y() - a.y()) / a.height())))

    def _abs(self, box: list[float]) -> QRectF:
        a = self._area()
        return QRectF(a.x() + box[0] * a.width(), a.y() + box[1] * a.height(),
                      (box[2] - box[0]) * a.width(), (box[3] - box[1]) * a.height())

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.pix.isNull():
            p.setPen(QColor(theme.color("muted")))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Kein Bild"))
            return
        p.drawPixmap(self._area(), self.pix, QRectF(self.pix.rect()))
        font = QFont(self.font())
        font.setBold(True)
        p.setFont(font)
        for i, a in enumerate(self.annots):
            color = QColor(KIND_COLORS.get(a.get("kind", "info"), "#ffffff"))
            r = self._abs(a["box"])
            p.setPen(QPen(color, 3 if i == self.current else 2))
            p.drawRect(r)
            text = a.get("text") or tr(dict(review.ANNOTATION_KINDS).get(a.get("kind", "info"), ""))
            p.fillRect(QRectF(r.x(), r.y() - 16, min(260, 8 + 7 * len(text)), 16), QColor(0, 0, 0, 170))
            p.setPen(color)
            p.drawText(QPointF(r.x() + 4, r.y() - 4), text)
        if self._start is not None and self._end is not None:
            p.setPen(QPen(QColor("#ffffff"), 2, Qt.PenStyle.DashLine))
            p.drawRect(QRectF(self._start, self._end).normalized())

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        for i in reversed(range(len(self.annots))):        # Klick in einen Rahmen: auswählen
            if self._abs(self.annots[i]["box"]).contains(pos):
                self.current = i
                self.selected.emit(i)
                self.update()
                return
        self._start = self._end = pos

    def mouseMoveEvent(self, event) -> None:
        if self._start is not None:
            self._end = event.position()
            self.update()

    def mouseReleaseEvent(self, _event) -> None:
        if self._start is None or self._end is None:
            return
        (x0, y0), (x1, y1) = self._rel(self._start), self._rel(self._end)
        self._start = self._end = None
        box = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        if box[2] - box[0] > 0.01 and box[3] - box[1] > 0.01:
            self.created.emit(box)
        self.update()


class ReviewDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Erkunden: Funde prüfen und markieren"))
        self.data_dir = app_paths.data_dir()
        theme.track(self, lambda o, f: o.resize(round(1180 * f), round(720 * f)))
        root = QHBoxLayout(self)
        split = QSplitter()
        root.addWidget(split)

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show)
        split.addWidget(self.list)

        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addWidget(label(tr("Ziehe mit der Maus einen Rahmen und trage rechts Art und Text ein. Ein Klick in "
                              "einen Rahmen wählt ihn aus."), "small", wrap=True))
        self.canvas = AnnotCanvas()
        self.canvas.created.connect(self._new_annot)
        self.canvas.selected.connect(lambda i: self.annot_list.setCurrentRow(i))
        mv.addWidget(self.canvas, 1)
        split.addWidget(mid)

        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("Name des Fensters"))
        sv.addWidget(label(tr("Fenster")))
        sv.addWidget(self.name)
        self.category = QComboBox()
        for key, (text, _t, _w) in CATEGORIES.items():
            self.category.addItem(tr(text), key)
        self.category.addItem(tr("Unbekannt"), "unknown")
        sv.addWidget(self.category)
        self.desc = QTextEdit()
        self.desc.setPlaceholderText(tr("Was macht dieses Fenster? Wofür ist es da, was ist wichtig?"))
        theme.track(self.desc, lambda o, f: o.setMaximumHeight(round(110 * f)))
        sv.addWidget(self.desc)
        sv.addWidget(label(tr("Markierungen")))
        self.annot_list = QListWidget()
        self.annot_list.currentRowChanged.connect(self._select_annot)
        sv.addWidget(self.annot_list, 1)
        self.kind = QComboBox()
        for key, text in review.ANNOTATION_KINDS:
            self.kind.addItem(tr(text), key)
        self.kind.currentIndexChanged.connect(self._edit_annot)
        self.text = QLineEdit()
        self.text.setPlaceholderText(tr("Text, z. B. „Power bis zum nächsten Rank“"))
        self.text.textEdited.connect(self._edit_annot)
        remove = QPushButton(tr("Markierung löschen"))
        remove.clicked.connect(self._remove_annot)
        sv.addWidget(self.kind)
        sv.addWidget(self.text)
        sv.addWidget(remove)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        theme.track(self.info, lambda o, f: o.setMaximumHeight(round(130 * f)))
        sv.addWidget(label(tr("Vom Programm gefunden")))
        sv.addWidget(self.info)
        buttons = QHBoxLayout()
        ok = QPushButton(tr("Stimmt ✓"))
        ok.setObjectName("primary")
        ok.setToolTip(tr("Speichern – das Erkunden öffnet dieses Fenster nicht mehr."))
        ok.clicked.connect(lambda: self._decide(review.OK))
        again = QPushButton(tr("Nochmal prüfen"))
        again.setToolTip(tr("Das nächste Erkunden sieht sich dieses Fenster noch einmal genau an."))
        again.clicked.connect(lambda: self._decide(review.RECHECK))
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self._close)
        for b in (ok, again, close):
            buttons.addWidget(b)
        sv.addLayout(buttons)
        split.addWidget(side)
        split.setSizes([200, 640, 340])

        self._row = -1
        self._fill()

    # ------------------------------------------------------------------ Liste der Funde
    def _fill(self, keep: str = "") -> None:
        data = review.load(self.data_dir)
        order = {review.PENDING: 0, review.RECHECK: 1, review.OK: 2}
        self.items = sorted(data.items(), key=lambda kv: (order.get(kv[1].get("status"), 3), kv[0].lower()))
        self.list.blockSignals(True)
        self.list.clear()
        mark = {review.OK: "✓ ", review.RECHECK: "↻ ", review.PENDING: "• "}
        for name, entry in self.items:
            self.list.addItem(QListWidgetItem(mark.get(entry.get("status"), "  ") + (entry.get("display") or name)))
        self.list.blockSignals(False)
        names = [n for n, _e in self.items]
        self._row = -1
        if self.items:
            self.list.setCurrentRow(names.index(keep) if keep in names else 0)

    def _show(self, row: int) -> None:
        self._save_current()
        self._row = row
        if not 0 <= row < len(self.items):
            return
        name, entry = self.items[row]
        self.name.setText(entry.get("display") or name)
        self.category.setCurrentIndex(max(0, self.category.findData(entry.get("category", "unknown"))))
        self.desc.setPlainText(entry.get("description", ""))
        self.annots = [dict(a) for a in entry.get("annotations") or []]
        self.canvas.set_image(entry.get("image", ""), self.annots)
        self._refresh_annots()
        text = review.summary(entry)
        if entry.get("lines"):
            text += "\n\n" + tr("Gelesen:") + "\n" + "\n".join(entry["lines"])
        self.info.setPlainText(text)

    def _save_current(self) -> None:
        if not 0 <= self._row < len(self.items):
            return
        name, entry = self.items[self._row]
        review.set_notes(self.data_dir, name, self.annots, self.desc.toPlainText().strip(),
                         self.name.text().strip() if self.name.text().strip() != name else "")
        data = review.load(self.data_dir)
        data[name]["category"] = self.category.currentData()
        review.save(self.data_dir, data)

    # ------------------------------------------------------------------ Markierungen
    def _refresh_annots(self, select: int = -1) -> None:
        kinds = dict(review.ANNOTATION_KINDS)
        self.annot_list.blockSignals(True)
        self.annot_list.clear()
        for a in self.annots:
            self.annot_list.addItem(f"{tr(kinds.get(a.get('kind', 'info'), ''))}: {a.get('text', '')}")
        self.annot_list.blockSignals(False)
        if select >= 0:
            self.annot_list.setCurrentRow(select)
        self.canvas.update()

    def _new_annot(self, box: list) -> None:
        self.annots.append({"box": box, "kind": "button", "text": ""})
        self.canvas.annots = self.annots
        self._refresh_annots(len(self.annots) - 1)
        self.text.setFocus()

    def _select_annot(self, i: int) -> None:
        self.canvas.current = i
        self.canvas.update()
        if 0 <= i < len(self.annots):
            self.kind.blockSignals(True)
            self.kind.setCurrentIndex(max(0, self.kind.findData(self.annots[i].get("kind", "info"))))
            self.kind.blockSignals(False)
            self.text.setText(self.annots[i].get("text", ""))

    def _edit_annot(self, *_args) -> None:
        i = self.annot_list.currentRow()
        if 0 <= i < len(self.annots):
            self.annots[i]["kind"] = self.kind.currentData()
            self.annots[i]["text"] = self.text.text()
            self._refresh_annots(i)

    def _remove_annot(self) -> None:
        i = self.annot_list.currentRow()
        if 0 <= i < len(self.annots):
            del self.annots[i]
            self.canvas.annots = self.annots
            self._refresh_annots(min(i, len(self.annots) - 1))

    # ------------------------------------------------------------------ Entscheidungen
    def _decide(self, status: str) -> None:
        if not 0 <= self._row < len(self.items):
            return
        self._save_current()
        name = self.items[self._row][0]
        review.set_status(self.data_dir, name, status, self.category.currentData())
        nxt = next((n for n, e in self.items if e.get("status") == review.PENDING and n != name), name)
        self._fill(keep=nxt)

    def _close(self) -> None:
        self._save_current()
        self.accept()

    def reject(self) -> None:                             # Esc / Fenster schließen: trotzdem speichern
        self._save_current()
        super().reject()
