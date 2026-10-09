"""Short “What's new” after an update: the most important points, everything else under “All versions”."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from .. import changelog
from ..i18n import tr
from ..version import __version__
from . import theme
from .widgets import label


class WhatsNewDialog(QDialog):
    def __init__(self, main, items: list[str]) -> None:
        super().__init__(main)
        self.main = main
        self.setWindowTitle(tr("What's new"))
        theme.track_min_width(self, 440)
        root = QVBoxLayout(self)
        theme.track_margins(root, 22, 20, 22, 18)
        theme.track_spacing(root, 10)
        root.addWidget(label(tr("New in version {version}", version=__version__), "h2"))
        for item in items:
            root.addWidget(label("•  " + item, "", wrap=True))
        row = QHBoxLayout()
        more = QPushButton(tr("All changes …"))
        more.clicked.connect(self._all)
        ok = QPushButton(tr("Let's go"))
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(more)
        row.addStretch(1)
        row.addWidget(ok)
        root.addSpacing(theme.px(6))
        root.addLayout(row)

    def _all(self) -> None:
        from .versions_dialog import VersionsDialog
        self.accept()
        VersionsDialog(self.main).exec()


def should_show(seen: str, wizard_done: bool) -> bool:
    """Only after an update: new installs (wizard still open) don't see it, the same version only once."""
    return wizard_done and seen != __version__


def show_if_updated(main) -> None:
    s = main.engine.settings
    show = should_show(s.seen_version, s.wizard_done)
    if s.seen_version != __version__:
        s.seen_version = __version__
        try:
            s.save()
        except OSError:
            pass
    items = changelog.highlights(__version__) if show else []
    if items:
        WhatsNewDialog(main, items).exec()
