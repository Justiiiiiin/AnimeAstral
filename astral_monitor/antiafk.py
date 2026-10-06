"""Anti-AFK (optional, Standard aus): alle N Minuten kurz zu Roblox wechseln, einmal Leertaste, zurück.

Die EINZIGE Stelle, an der das Programm Eingaben an Roblox sendet – auf ausdrücklichen Wunsch des Eigentümers. Roblox
nimmt Tasten nur im Vordergrund an (getestet: Fenster-Nachrichten an das Hintergrundfenster wirken nicht), deshalb der
kurze Fensterwechsel. Damit der Tastendruck nicht in einem anderen Programm landet, wird gewartet, bis der Nutzer
2 Sekunden lang nichts eingegeben hat (höchstens 60 s, danach beim nächsten Durchlauf erneut)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from .i18n import tr

log = logging.getLogger("antiafk")

QUIET_SECONDS = 2.0          # so lange keine eigene Eingabe des Nutzers, bevor gewechselt wird
MAX_WAIT = 60.0              # länger nicht auf Ruhe warten – dann Versuch im nächsten Durchlauf
RETRY_SECONDS = 30.0         # nach einem Fehlschlag (Roblox nicht gefunden …) erneut versuchen


class AntiAfk(threading.Thread):
    def __init__(self, get_settings: Callable, event: Callable[[str, str], None],
                 jump: Optional[Callable[[str], tuple[bool, str]]] = None,
                 idle_seconds: Optional[Callable[[], float]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(name="antiafk", daemon=True)
        self._get, self._event = get_settings, event
        self._jump = jump or jump_in_roblox
        self._idle = idle_seconds or user_idle_seconds
        self._clock = clock
        self._halt = threading.Event()
        self._enabled = False
        self.next_at: Optional[float] = None       # Zeitpunkt (clock) des nächsten Sprungs; None = aus
        self._waiting_since: Optional[float] = None
        self.last_result = ""

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
            self._enabled, self.next_at, self._waiting_since = False, None, None
            return
        if not self._enabled:                      # gerade eingeschaltet: erster Sprung nach einem Intervall
            self._enabled, self.next_at = True, now + interval
            return
        if self.next_at is not None and self.next_at - now > interval:
            self.next_at = now + interval          # Intervall wurde verkürzt
        if self.next_at is None or now < self.next_at:
            return
        if self._idle() < QUIET_SECONDS:           # Nutzer tippt/klickt gerade: kurz warten
            if self._waiting_since is None:
                self._waiting_since = now
            if now - self._waiting_since < MAX_WAIT:
                return
            self._waiting_since = None
            self.next_at = now + RETRY_SECONDS
            log.info("Anti-AFK: Nutzer durchgehend aktiv – übersprungen")
            return
        self._waiting_since = None
        ok, info = self._jump(s.window_title)
        self.last_result = info
        if ok:
            self.next_at = now + interval
            log.info("Anti-AFK: gesprungen (%s)", info)
            self._event(tr("Anti-AFK: gesprungen"), "info")
        else:
            self.next_at = now + RETRY_SECONDS
            log.info("Anti-AFK: nicht möglich – %s", info)
            self._event(tr("Anti-AFK: {reason}", reason=info), "warn")


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


def jump_in_roblox(title: str) -> tuple[bool, str]:
    """Roblox nach vorne, Leertaste, vorheriges Fenster zurück. Rückgabe (geklappt?, Beschreibung)."""
    import ctypes
    from ctypes import wintypes

    from . import winapi

    u32 = ctypes.windll.user32
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.SetForegroundWindow.argtypes = [wintypes.HWND]
    u32.IsWindow.argtypes = [wintypes.HWND]
    hwnd = winapi.find_window(title)
    if hwnd is None:
        return False, tr("Roblox-Fenster nicht gefunden")
    if winapi.is_minimized(hwnd):
        return False, tr("Roblox ist minimiert")
    previous = u32.GetForegroundWindow()
    switched = previous != hwnd
    if switched and not _bring_to_front(hwnd):
        return False, tr("Roblox ließ sich nicht nach vorne holen")
    time.sleep(0.15)                               # Roblox die Aktivierung verarbeiten lassen
    _press_space()
    time.sleep(0.1)
    if switched and previous and u32.IsWindow(previous):
        _bring_to_front(previous)
    return True, ("mit Fensterwechsel" if switched else "Roblox war schon vorne")


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
