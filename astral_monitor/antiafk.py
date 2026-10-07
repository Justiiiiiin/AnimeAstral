"""Anti-AFK (optional, Standard aus): alle N Minuten jedes Roblox-Fenster kurz nach vorne, 4× Esc, zurück.

Seit 0.9.5-beta.2 nach dem bewährten AutoHotkey-Skript des Eigentümers: alle Clients, Esc statt Leertaste, zusätzlich
Esc direkt an das Fenster, danach Roblox-Speicher leeren. Minimierte Fenster werden wiederhergestellt und bleiben offen
(minimiert liefert die Aufnahme keine Bilder – Wunsch des Eigentümers). Kein Warten, wenn der Nutzer gerade tippt:
sofort zum fälligen Zeitpunkt, damit Roblox beim Spielen nicht unnötig lange vorne bleibt. Nur während das Makro
klickt, wird gewartet."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from .i18n import tr

log = logging.getLogger("antiafk")

RETRY_SECONDS = 30.0         # nach einem Fehlschlag (Roblox nicht gefunden …) erneut versuchen


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
        self._idle = idle_seconds or user_idle_seconds   # nicht mehr genutzt (kein Warten), bleibt für Aufrufer
        self._clock = clock
        self._halt = threading.Event()
        self._enabled = False
        self.next_at: Optional[float] = None       # Zeitpunkt (clock) des nächsten Sprungs; None = aus

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
        """Ein Durchlauf (öffentlich für Tests)."""
        s = self._get()
        interval = max(1, min(19, int(s.anti_afk_minutes))) * 60
        if not s.anti_afk_enabled:
            self._enabled, self.next_at = False, None
            return
        if not self._enabled:                      # gerade eingeschaltet: erster Sprung nach einem Intervall
            self._enabled, self.next_at = True, now + interval
            return
        if self.next_at is not None and self.next_at - now > interval:
            self.next_at = now + interval          # Intervall wurde verkürzt
        if self.next_at is None or now < self.next_at:
            return
        if self._busy():                            # Makro klickt gerade: nicht dazwischenfunken
            return
        ok, info = self._jump(s.window_title)
        if ok:
            self.next_at = now + interval
            log.info("Anti-AFK: ausgeführt (%s)", info)
            self._event(tr("Anti-AFK: Roblox aktiv gehalten ({info})", info=info), "info")
        else:
            self.next_at = now + RETRY_SECONDS
            log.info("Anti-AFK: nicht möglich – %s", info)
            self._event(tr("Anti-AFK: {reason}", reason=info), "warn")


def _macro_busy() -> bool:
    try:
        from .automation import macro_running
        return macro_running()
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ Windows
def user_idle_seconds() -> float:
    """Sekunden seit der letzten Maus-/Tastatureingabe des Nutzers (GetLastInputInfo)."""
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 999.0
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


ROBLOX_EXE = "robloxplayerbeta.exe"
ESC_PRESSES = 4              # gerade Anzahl: Roblox-Menü auf und wieder zu (keine Wirkung im Spiel)


def roblox_windows(title: str = "Roblox") -> list[int]:
    """Alle Hauptfenster der Roblox-Clients (Prozess RobloxPlayerBeta.exe) – auch minimierte, auch mehrere.
    Fallback: Fenster mit dem Titel."""
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
                    and not u32.GetWindow(hwnd, 4):        # GW_OWNER: nur Hauptfenster
                found.append(int(hwnd))
            return True
        u32.EnumWindows(callback, 0)
    if not found:
        hwnd = winapi.find_window(title)
        if hwnd is not None:
            found.append(hwnd)
    return found


def wake_roblox(title: str) -> tuple[bool, str]:
    """Wie das bewährte AutoHotkey-Skript des Eigentümers: jedes Roblox-Fenster kurz nach vorne (minimierte werden
    wiederhergestellt und bleiben offen), 4× Esc per SendInput, zusätzlich 1× Esc direkt an das Fenster; danach
    Roblox-Arbeitsspeicher leeren und das vorherige Fenster zurückholen. Rückgabe (geklappt?, Beschreibung)."""
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.windll.user32
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.IsWindow.argtypes = [wintypes.HWND]
    u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    windows = roblox_windows(title)
    if not windows:
        return False, tr("Roblox-Fenster nicht gefunden")
    previous = u32.GetForegroundWindow()
    done = 0
    for hwnd in windows:
        if u32.IsIconic(hwnd):                     # minimiert: wiederherstellen und offen lassen (sonst keine Bilder)
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
        u32.PostMessageW(hwnd, 0x0100, 0x1B, 0x00010001)          # WM_KEYDOWN Esc (wie ControlSend)
        u32.PostMessageW(hwnd, 0x0101, 0x1B, 0xC0010001)          # WM_KEYUP
        done += 1
    trim_roblox_memory()
    if previous and previous not in windows and u32.IsWindow(previous):
        _restore(windows[-1], previous)
    if not done:
        return False, tr("Roblox ließ sich nicht nach vorne holen")
    return True, f"{done} Fenster"


def trim_roblox_memory() -> int:
    """Arbeitsspeicher der Roblox-Prozesse freigeben (EmptyWorkingSet, wie im AutoHotkey-Skript). Rückgabe: Anzahl."""
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
    except Exception:  # noqa: BLE001 – nur eine Zugabe
        log.debug("Roblox-Speicher leeren fehlgeschlagen", exc_info=True)
    return count


jump_in_roblox = wake_roblox                       # alter Name (Tests, ältere Aufrufer)


def _restore(roblox, previous) -> None:
    """Vorheriges Fenster wieder sichtbar nach vorne. Nur aktivieren reicht nicht: manche Programme (z. B. Electron-
    Apps) werden dadurch aktiv, aber nicht nach oben geholt – Roblox bliebe sichtbar davor (gemeldet 06.10.2026).
    Deshalb Roblox ganz nach hinten schieben und das vorherige Fenster ausdrücklich nach oben holen."""
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
    target = u32.GetAncestor(previous, 3) or previous          # GA_ROOTOWNER: das sichtbare Hauptfenster
    _bring_to_front(target)
    u32.BringWindowToTop(target)
    u32.SetWindowPos(target, wintypes.HWND(0), 0, 0, 0, 0, 0x0001 | 0x0002)   # HWND_TOP


def _bring_to_front(hwnd) -> bool:
    """SetForegroundWindow mit dem üblichen Alt-Trick (Windows erlaubt Hintergrundprogrammen sonst keinen Wechsel)."""
    import ctypes

    u32 = ctypes.windll.user32
    _key(0x12, down=True)                          # Alt kurz drücken: hebt die Fokussperre auf
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
    """Ein Tastenereignis per SendInput (mit Scan-Code, den Spiele bevorzugt auswerten)."""
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
