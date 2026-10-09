"""Card “My raids” (Settings → Roblox): create, rename and delete raid names.
Which one is running is chosen on the start page. Since 0.9.0 without per-raid settings (trigger/note)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, \
    QPushButton

from .. import messages
from ..i18n import tr
from . import theme
from .widgets import Card, smooth


class RaidsCard(Card):
    def __init__(self, main) -> None:
        super().__init__(tr("My raids"),
                         tr("The raids you can pick on the home page. Double-click or right-click to rename – the "
                            "statistics follow. Deleting keeps the statistics."))
        self.main = main
        self.engine = main.engine
        self.store = main.engine.profile_store
        self.list = QListWidget()
        smooth(self.list)
        theme.track_fixed_height(self.list, 168)
        self.list.itemDoubleClicked.connect(lambda _item: self._rename())
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.body.addWidget(self.list)
        row = QHBoxLayout()
        for text, slot in ((tr("New …"), self._new), (tr("Rename …"), self._rename), (tr("Delete"), self._delete)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        self.body.addLayout(row)
        self.refresh_list()

    def _current(self) -> str:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def refresh_list(self, select: str = "") -> None:
        keep = select or self._current() or self.engine.settings.current_raid
        self.list.clear()
        for name in self.store.names():
            attempts = self.engine.stats.attempts(name)
            item = QListWidgetItem(f"{name}   ·   " + tr("{count} attempts", count=messages.fmt_k(attempts))
                                   if attempts else name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == keep:
                self.list.setCurrentItem(item)
        if not self.list.count():
            empty = QListWidgetItem(tr("No raids yet – create one with “New …”."))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)

    def _context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return
        self.list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction(tr("Select as current raid"), lambda: self.main.select_raid(self._current()))
        menu.addAction(tr("Rename …"), self._rename)
        menu.addSeparator()
        menu.addAction(tr("Delete"), self._delete)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _new(self) -> None:
        text, ok = QInputDialog.getText(self, tr("New raid"), tr("Name of the raid (e.g. MaxTac Call):"))
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
        text, ok = QInputDialog.getText(self, tr("Rename raid"), tr("New name for “{name}”:", name=old),
                                        QLineEdit.EchoMode.Normal, old)
        if not ok or not text.strip() or text.strip() == old:
            return
        try:
            name = self.engine.rename_raid(old, text)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr("Rename raid"), str(exc))
            return
        self.refresh_list(select=name)
        self.main.raids_changed()
        self.main.show_toast(tr("Renamed: {old} → {new} ✓", old=old, new=name))

    def _delete(self) -> None:
        name = self._current()
        if not name:
            return
        if QMessageBox.question(self, tr("Delete raid"),
                                tr("Delete raid “{name}” from the list? Its statistics are kept.",
                                   name=name)) != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(name)
        if self.engine.settings.current_raid == name:
            self.main.select_raid("")
        self.refresh_list()
        self.main.raids_changed()
