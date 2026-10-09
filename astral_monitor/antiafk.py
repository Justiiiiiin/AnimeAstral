"""Anti-AFK (optional, off by default): every N minutes bring each Roblox window to the front briefly, Esc 4×, back.

Since 0.9.5-beta.2 after the owner's proven AutoHotkey script: all clients, Esc instead of space, plus Esc sent
directly to the window, then clear Roblox's memory. Minimized windows are restored and stay open (minimized, the
capture gets no images – owner's wish). No waiting while the user is typing: right at the due time, so Roblox
doesn't stay in front for long while you play. It only waits while the macro is clicking."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from .i18n import tr

log = logging.getLogger("antiafk")

RETRY_SECONDS = 30.0         # retry after a failure (Roblox not found …)


class AntiAfk(threading.Thread):
    def __init__(self, get_settings: Callable, event: Callable[[str, str], None],
                 jump: Optional[Callable[[str], tuple[bool, str]]] = None,
                 idle_seconds: Optional[Callable[[], float]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 busy: Optional[Callable[[], bool]] = None) -> None:
        super().__init__(name="antiafk", daemon=True)
        self._busy = busy or _macro_busy
        self._get, self._event = get_settings, event
        self._jump = jump or jump_in_roblox
        self._idle = idle_seconds or user_idle_seconds   # no longer used (no waiting), kept for callers
        self._clock = clock
        self._halt = threading.Event()
        self._enabled = False
        self.next_at: Optional[float] = None       # time (clock) of the next jump; None = off

    def stop(self) -> None:
        self._halt.set()

    def seconds_left(self) -> Optional[float]:
        return None if self.next_at is None else max(0.0, self.next_at - self._clock())

    def run(self) -> None:
        while not self._halt.wait(0.5):
            try:
                self.tick(self._clock())
            except Exception:
                log.exception("Anti-AFK: unerwarteter Fehler")

    def tick(self, now: float) -> None:
        """One pass (public for tests)."""
        s = self._get()
        interval = max(1, min(19, int(s.anti_afk_minutes))) * 60
        if not s.anti_afk_enabled:
            self._enabled, self.next_at = False, None
            return
        if not self._enabled:                      # just switched on: first jump after one interval
            self._enabled, self.next_at = True, now + interval
            return
        if self.next_at is not None and self.next_at - now > interval:
            self.next_at = now + interval          # the interval was shortened
        if self.next_at is None or now < self.next_at:
            return
        if self._busy():                            # the macro is clicking right now: don't interfere
            return
        ok, info = self._jump(s.window_title)
        if ok:
            self.next_at = now + interval
            log.info("Anti-AFK: done (%s)", info)
            self._event(tr("Anti-AFK: kept Roblox active ({info})", info=info), "info")
        else:
            self.next_at = now + RETRY_SECONDS
            log.info("Anti-AFK: not possible – %s", info)
            self._event(tr("Anti-AFK: {reason}", reason=info), "warn")


def _macro_busy() -> bool:
    try:
        from .automation import macro_running
        return macro_running()
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ Windows
def user_idle_seconds() -> float:
    """Seconds since the user's last mouse/keyboard input (GetLastInputInfo)."""
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 999.0
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


ROBLOX_EXE = "robloxplayerbeta.exe"
ESC_PRESSES = 4              # even number: Roblox menu opens and closes again (no effect in the game)


def roblox_windows(title: str = "Roblox") -> list[int]:
    """All main windows of the Roblox clients (process RobloxPlayerBeta.exe) – minimized ones too, several too.
    Fallback: window with the title."""
    import ctypes
    from ctypes import wintypes

    from . import winapi
    pids: set[int] = set()
    try:
        import psutil
        pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info.get("name") or "").lower() == ROBLOX_EXE}
    except Exception:  # noqa: BLE001
        pass
    found: list[int] = []
    if pids:
        u32 = ctypes.windll.user32
        enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @enum
        def callback(hwnd, _lparam):
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids and u32.IsWindowVisible(hwnd) and u32.GetWindowTextLengthW(hwnd) \
                    and not u32.GetWindow(hwnd, 4):        # GW_OWNER: main windows only
                found.append(int(hwnd))
            return True
        u32.EnumWindows(callback, 0)
    if not found:
        hwnd = winapi.find_window(title)
        if hwnd is not None:
            found.append(hwnd)
    return found


def wake_roblox(title: str) -> tuple[bool, str]:
    """Like the owner's proven AutoHotkey script: bring each Roblox window to the front briefly (minimized ones are
    restored and stay open), Esc 4× via SendInput, plus Esc 1× directly to the window; then clear Roblox's working
    memory and bring back the previous window. Returns (worked?, description)."""
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.windll.user32
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.IsWindow.argtypes = [wintypes.HWND]
    u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    windows = roblox_windows(title)
    if not windows:
        return False, tr("Roblox window not found")
    previous = u32.GetForegroundWindow()
    done = 0
    for hwnd in windows:
        if u32.IsIconic(hwnd):                     # minimized: restore and leave open (otherwise no images)
            u32.ShowWindow(hwnd, 9)                # SW_RESTORE
            time.sleep(0.15)
        if not _bring_to_front(hwnd):
            continue
        time.sleep(0.05)
        for _ in range(ESC_PRESSES):
            _key(0x1B, down=True, scan=0x01)
            time.sleep(0.03)
            _key(0x1B, down=False, scan=0x01)
            time.sleep(0.1)
        u32.PostMessageW(hwnd, 0x0100, 0x1B, 0x00010001)          # WM_KEYDOWN Esc (like ControlSend)
        u32.PostMessageW(hwnd, 0x0101, 0x1B, 0xC0010001)          # WM_KEYUP
        done += 1
    trim_roblox_memory()
    if previous and previous not in windows and u32.IsWindow(previous):
        _restore(windows[-1], previous)
    if not done:
        return False, tr("Roblox could not be brought to the front")
    return True, f"{done} Fenster"


def trim_roblox_memory() -> int:
    """Free the working memory of the Roblox processes (EmptyWorkingSet, as in the AutoHotkey script). Returns the
    count."""
    import ctypes
    count = 0
    try:
        import psutil
        k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        k32.OpenProcess.restype = ctypes.c_void_p
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() != ROBLOX_EXE:
                continue
            handle = k32.OpenProcess(0x0100 | 0x0400, False, p.pid)   # SET_QUOTA | QUERY_INFORMATION
            if handle:
                if psapi.EmptyWorkingSet(ctypes.c_void_p(handle)):
                    count += 1
                k32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:  # noqa: BLE001 – only an extra
        log.debug("Roblox-Speicher leeren fehlgeschlagen", exc_info=True)
    return count


jump_in_roblox = wake_roblox                       # old name (tests, older callers)


def _restore(roblox, previous) -> None:
    """Bring the previous window visibly back to the front. Activating alone isn't enough: some programs (e.g.
    Electron apps) become active but aren't raised – Roblox would stay visible in front (reported 06.10.2026).
    So push Roblox to the very back and explicitly raise the previous window."""
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.windll.user32
    u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, wintypes.UINT]
    u32.GetAncestor.restype = wintypes.HWND
    u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    flags = 0x0001 | 0x0002 | 0x0010              # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    u32.SetWindowPos(roblox, wintypes.HWND(1), 0, 0, 0, 0, flags)   # HWND_BOTTOM
    if not previous or not u32.IsWindow(previous):
        return
    target = u32.GetAncestor(previous, 3) or previous          # GA_ROOTOWNER: the visible main window
    _bring_to_front(target)
    u32.BringWindowToTop(target)
    u32.SetWindowPos(target, wintypes.HWND(0), 0, 0, 0, 0, 0x0001 | 0x0002)   # HWND_TOP


def _bring_to_front(hwnd) -> bool:
    """SetForegroundWindow with the usual Alt trick (otherwise Windows doesn't let background programs switch)."""
    import ctypes

    u32 = ctypes.windll.user32
    _key(0x12, down=True)                          # press Alt briefly: lifts the focus lock
    _key(0x12, down=False)
    u32.SetForegroundWindow(hwnd)
    for _ in range(10):
        if u32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.03)
    return False


def _press_space() -> None:
    _key(0x20, down=True, scan=0x39)
    time.sleep(0.08)
    _key(0x20, down=False, scan=0x39)


def _key(vk: int, down: bool, scan: int = 0) -> None:
    """One key event via SendInput (with the scan code that games prefer to evaluate)."""
    import ctypes
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    flags = (0x0008 if scan else 0) | (0 if down else 0x0002)      # KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP
    inp = INPUT(type=1)                                             # INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(0 if scan else vk, scan, flags, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
