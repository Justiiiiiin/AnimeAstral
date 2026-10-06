"""Seite „Raids": Raid-Namen verwalten (anlegen, umbenennen, löschen) und je Raid Notiz/Auslöser.
Welcher Raid gerade läuft, wählst du auf der Startseite aus."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import messages
from ..i18n import dec, tr
from . import theme
from .widgets import Card, SpinBox, columns, form_grid, label, smooth


class RaidsPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.engine = main.engine
        self.store = main.engine.profile_store

        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 14)
        root.addWidget(label(tr("Raids"), "h1"))
        root.addWidget(label(tr("Deine Raids als Liste. Welcher gerade läuft, wählst du auf der Startseite aus – "
                                "Statistik, Discord und Profilstatus nutzen dann diesen Namen."), "muted", wrap=True))

        left = Card(tr("Meine Raids"))
        self.list = QListWidget()
        smooth(self.list)
        theme.track_min_height(self.list, 300)
        self.list.currentRowChanged.connect(lambda _row: self._load_selected())
        self.list.itemDoubleClicked.connect(lambda _item: self._rename())
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        left.body.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton(tr("Neu …"))
        add.clicked.connect(self._new)
        ren = QPushButton(tr("Umbenennen …"))
        ren.clicked.connect(self._rename)
        delete = QPushButton(tr("Löschen"))
        delete.clicked.connect(self._delete)
        for btn in (add, ren, delete):
            row.addWidget(btn)
        left.body.addLayout(row)
        left.body.addWidget(label(tr("Doppelklick oder Rechtsklick auf einen Raid zum Umbenennen. Beim Umbenennen "
                                     "zieht die Statistik mit."), "small", wrap=True))

        right = Card(tr("Raid-Einstellungen"))
        self.sel_title = label("", "h2")
        right.body.addWidget(self.sel_title)
        self.sel_stats = label("", "small", wrap=True)
        right.body.addWidget(self.sel_stats)
        grid = form_grid()
        self.p_trigger = SpinBox()
        self.p_trigger.setRange(-1, 5)
        self.p_trigger.setSpecialValueText(tr("wie global"))
        self.p_trigger.setToolTip(tr("1 = Raid zählt ab 99/100. „wie global“ nutzt den Wert unter „Erkennung“."))
        self.p_note = QLineEdit()
        self.p_note.setPlaceholderText(tr("z. B. „Boss bei Welle 27“"))
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.addWidget(label(tr("Auslöser: Gesamt minus")), 0, 0)
        grid.addWidget(self.p_trigger, 0, 1, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(label(tr("Notiz")), 1, 0)
        grid.addWidget(self.p_note, 1, 1)
        right.body.addLayout(grid)
        srow = QHBoxLayout()
        srow.addStretch(1)
        self.save_p = QPushButton(tr("Übernehmen"))
        self.save_p.setObjectName("primary")
        self.save_p.clicked.connect(self._save_selected)
        srow.addWidget(self.save_p)
        right.body.addLayout(srow)
        right.body.addStretch(1)
        root.addLayout(columns(left, right), 1)
        self.refresh_list()

    # ------------------------------------------------------------------ Liste
    def _current(self) -> str:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def refresh_list(self, select: str = "") -> None:
        keep = select or self._current() or self.engine.settings.current_raid
        self.list.blockSignals(True)
        self.list.clear()
        for name in self.store.names():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == keep:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._load_selected()

    def _load_selected(self) -> None:
        name = self._current()
        for w in (self.p_trigger, self.p_note, self.save_p):
            w.setEnabled(bool(name))
        if not name:
            self.sel_title.setText(tr("Noch keine Raids"))
            self.sel_stats.setText(tr("Lege mit „Neu …“ deinen ersten Raid an."))
            self.p_trigger.setValue(-1)
            self.p_note.clear()
            return
        self.sel_title.setText(name)
        summary = self.engine.stats.summary(None, name)
        attempts = summary.ok + summary.failed
        best = self.engine.stats.best_wave(name)
        self.sel_stats.setText(tr("{attempts} Versuche · Bestwelle {best} · Ø Endwelle {avg}",
                                  attempts=messages.fmt_int(attempts), best=best or "–",
                                  avg=dec(f"{summary.avg_wave_all:.1f}") if summary.avg_wave_all else "–"))
        data = self.store.settings(name)
        trigger = data.get("trigger_offset")
        self.p_trigger.setValue(trigger if isinstance(trigger, int) else -1)
        self.p_note.setText(str(data.get("note", "")))

    def _save_selected(self) -> None:
        name = self._current()
        if not name:
            return
        data = {"note": self.p_note.text().strip()}
        if self.p_trigger.value() >= 0:
            data["trigger_offset"] = self.p_trigger.value()
        self.store.save_settings(name, data)
        if self.engine.settings.current_raid == name:
            self.engine.set_current_raid(name)          # Auslöser sofort übernehmen
        self.main.show_toast(tr("Raid-Einstellungen gespeichert ✓"))

    def _context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        self.list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction(tr("Als aktuellen Raid wählen"), lambda: self.main.select_raid(self._current()))
        menu.addAction(tr("Umbenennen …"), self._rename)
        menu.addSeparator()
        menu.addAction(tr("Löschen"), self._delete)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ Aktionen
    def _new(self) -> None:
        text, ok = QInputDialog.getText(self, tr("Neuer Raid"), tr("Name des Raids (z. B. MaxTac Call):"))
        if not ok or not text.strip():
            return
        try:
            name = self.store.create(text)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr("Raid"), str(exc))
            return
        self.refresh_list(select=name)
        self.main.raids_changed()

    def _rename(self) -> None:
        old = self._current()
        if not old:
            return
        text, ok = QInputDialog.getText(self, tr("Raid umbenennen"), tr("Neuer Name für „{name}“:", name=old),
                                        QLineEdit.EchoMode.Normal, old)
        if not ok or not text.strip() or text.strip() == old:
            return
        try:
            name = self.engine.rename_raid(old, text)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr("Raid umbenennen"), str(exc))
            return
        self.refresh_list(select=name)
        self.main.raids_changed()
        self.main.show_toast(tr("Umbenannt: {old} → {new} ✓", old=old, new=name))

    def _delete(self) -> None:
        name = self._current()
        if not name:
            return
        if QMessageBox.question(self, tr("Raid löschen"),
                                tr("Raid „{name}“ aus der Liste löschen? Die bisherige Statistik bleibt erhalten.",
                                   name=name)) != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(name)
        if self.engine.settings.current_raid == name:
            self.main.select_raid("")
        self.refresh_list()
        self.main.raids_changed()

    # ------------------------------------------------------------------ Seite
    def load(self, s) -> None:
        pass

    def apply(self, s) -> None:
        pass

    def refresh(self) -> None:
        pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load_selected()                          # Statistik des gewählten Raids aktuell halten
