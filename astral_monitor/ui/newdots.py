"""“New” dots: after an update a small dot on areas with something new – disappears after the first opening.
New installs see no dots (everything is new)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QLabel, QWidget

from ..version import __version__
from . import theme

# Per version: where there is something new (“nav:<page>” = icon bar, “tab:<section>” = settings tab)
NEW_FEATURES: dict[str, tuple[str, ...]] = {
    "0.8.0": ("nav:1", "nav:2", "nav:5", "tab:Roblox", "tab:Appearance", "tab:Program"),
    "0.9.0": ("nav:3", "tab:Roblox"),
    "0.9.5-beta.1": ("nav:3", "tab:Roblox"),        # automation (beta) under Settings → Roblox
    "0.9.5-beta.2": ("nav:0",),                     # new start page: macro, events, live, quests
    "0.9.5-beta.4": ("nav:0", "nav:3", "tab:Program"),   # queue; events under Settings → Program
    "0.9.7-beta.1": ("nav:0",),                     # explore, Auto Roll, raids in the queue
    "0.9.7-beta.4": ("nav:1", "nav:2", "tab:Debug"),   # statistics/alerts without scrolling; debug as its own tab
    "0.9.7-beta.5": ("nav:3", "tab:Debug"),          # debug with on/off and the full log
    "0.9.8": ("nav:0", "nav:3"),                    # macro/queue (stable), settings search with Ctrl+F
    "0.9.9-beta.1": ("nav:0",),                     # start page for the macro, auto-collect, raid selection
    "0.9.9-beta.2": ("nav:3", "tab:Macro", "tab:Discord bot"),   # explore in settings, Discord bot
    "0.9.9-beta.4": ("nav:3", "tab:Macro"),          # check findings with the marking tool
    "0.9.9-beta.7": ("nav:0", "nav:3", "tab:Macro", "tab:Appearance"),   # farm routine, log, Night City
    "0.9.9-beta.8": ("nav:3", "tab:Macro"),          # findings without duplicates
    "0.9.9-beta.9": ("nav:0",),                      # Progressions: Auto All
    "0.9.9-beta.10": ("nav:3", "tab:Macro"),         # explore: all worlds, sideways lists
    "0.9.9-beta.11": ("nav:0",),                     # auto-collect fixed, routine without Progressions
    "0.9.9-beta.13": ("nav:1", "nav:3", "tab:Appearance"),   # raids per day; English as the default language
    "0.9.9-beta.14": ("nav:0",),                     # Fixer Gigs per slot, guild once per PC day
    "0.9.9-beta.15": ("nav:0",),                     # gig pills, faster guild claim
}


def pending(seen: list) -> set:
    """Not yet seen new features of the installed version."""
    return set(NEW_FEATURES.get(__version__, ())) - set(seen)


class _Dot(QObject):
    """Small dot at the top right of a button; follows its size."""

    def __init__(self, button: QWidget) -> None:
        super().__init__(button)
        self.button = button
        self.label = QLabel(button)
        self.label.setObjectName("newdot")
        size = theme.px(9)
        self.label.setFixedSize(size, size)
        self.label.setStyleSheet(f"background: {theme.color('accent')}; border-radius: {size // 2}px; "
                                 f"border: 2px solid {theme.color('sidebar')};")
        self.label.setToolTip("Neu")
        button.installEventFilter(self)
        self._place()
        self.label.show()

    def _place(self) -> None:
        self.label.move(self.button.width() - self.label.width() - theme.px(4), theme.px(4))
        self.label.raise_()

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._place()
        return False

    def remove(self) -> None:
        self.button.removeEventFilter(self)
        self.label.hide()                                  # gone right away (deleted on the next pass)
        self.label.deleteLater()
        self.deleteLater()


class NewDots:
    """Manages the dots; `seen` is the list from the settings, `save` saves it."""

    def __init__(self, settings, save) -> None:
        self._settings = settings
        self._save = save
        self._dots: dict[str, _Dot] = {}

    def attach(self, key: str, button: QWidget) -> None:
        if key in pending(self._settings.new_seen) and key not in self._dots:
            self._dots[key] = _Dot(button)

    def seen(self, key: str) -> None:
        dot = self._dots.pop(key, None)
        if dot is None:
            return
        dot.remove()
        self._settings.new_seen = sorted(set(self._settings.new_seen) | {key})
        self._save()

    def mark_all_seen(self) -> None:
        """New install: no dots."""
        for key in list(self._dots):
            self._dots.pop(key).remove()
        self._settings.new_seen = sorted(set(self._settings.new_seen) | set(NEW_FEATURES.get(__version__, ())))
