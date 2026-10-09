"""Global hotkeys via the Windows function RegisterHotKey (no extra package, no admin rights)."""
from __future__ import annotations

import logging
import re
import sys
import threading
from typing import Callable

from .i18n import tr

log = logging.getLogger("hotkeys")

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
_MODS = {"ctrl": MOD_CONTROL, "strg": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
         "shift": MOD_SHIFT, "win": MOD_WIN}
_SPECIAL = {"space": 0x20, "pause": 0x13, "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
            "pageup": 0x21, "pagedown": 0x22}


def parse_hotkey(text: str) -> tuple[int, int]:
    """'Ctrl+Alt+S' -> (modifier mask, virtual key code). Raises ValueError for invalid input."""
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError(tr("please give modifiers and a key, e.g. Ctrl+Alt+S"))
    mods = 0
    for part in parts[:-1]:
        if part not in _MODS:
            raise ValueError(tr("unknown modifier “{key}” (allowed: Ctrl, Alt, Shift, Win)", key=part))
        mods |= _MODS[part]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif re.fullmatch(r"f([1-9]|1\d|2[0-4])", key):
        vk = 0x70 + int(key[1:]) - 1
    elif key in _SPECIAL:
        vk = _SPECIAL[key]
    else:
        raise ValueError(tr("unknown key “{key}”", key=key))
    return mods, vk


class HotkeyListener(threading.Thread):
    """Registers hotkeys and calls the functions in the listener thread
    (the functions should only hand an action over to the UI)."""

    def __init__(self, bindings: dict[str, tuple[str, Callable[[], None]]]) -> None:
        super().__init__(name="hotkeys", daemon=True)
        self._bindings = bindings            # name -> (text, function)
        self.failed: list[str] = []
        self.ready = threading.Event()
        self._thread_id = 0

    def run(self) -> None:
        if sys.platform != "win32":
            self.failed = [f"{n} ({t})" for n, (t, _f) in self._bindings.items()]
            self.ready.set()
            return
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0x0400, 0x0400, 0)     # create the message queue

        actions: dict[int, Callable[[], None]] = {}
        for i, (name, (text, func)) in enumerate(self._bindings.items(), start=1):
            try:
                mods, vk = parse_hotkey(text)
            except ValueError:
                self.failed.append(f"{name} ({text})")
                continue
            if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                actions[i] = func
            else:
                self.failed.append(tr("{name} ({key}) – possibly used by another program", name=name, key=text))
        self.ready.set()

        while True:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result in (0, -1):
                break
            if msg.message == 0x0312 and msg.wParam in actions:              # WM_HOTKEY
                try:
                    actions[msg.wParam]()
                except Exception:
                    log.exception("Hotkey-Aktion fehlgeschlagen")
        for i in actions:
            user32.UnregisterHotKey(None, i)

    def stop(self) -> None:
        if sys.platform == "win32" and self._thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)   # WM_QUIT
        self.join(timeout=2)
