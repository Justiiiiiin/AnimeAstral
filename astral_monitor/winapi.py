"""Small Windows helpers (find window, size, minimized?) – without extra packages."""
from __future__ import annotations

import sys
from typing import Optional

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _user32.EnumWindows.argtypes = [_ENUMPROC, wintypes.LPARAM]


def find_window(title: str) -> Optional[int]:
    """Handle of the visible window with exactly this title (e.g. “Roblox”)."""
    if not IS_WIN:
        return None
    found: list[int] = []

    @_ENUMPROC
    def callback(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            length = _user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value == title:
                    found.append(int(hwnd))
                    return False
        return True

    _user32.EnumWindows(callback, 0)
    return found[0] if found else None


def trim_memory() -> bool:
    """Returns unneeded memory pages to Windows (start-up leftovers, driver and font pages).
    Measured: 178 MB -> permanently ~50 MB, the pages actually in use come back from the cache right away."""
    if not IS_WIN:
        return False
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetProcessWorkingSetSizeEx.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
    return bool(k32.SetProcessWorkingSetSizeEx(k32.GetCurrentProcess(), ctypes.c_size_t(-1), ctypes.c_size_t(-1), 0))


def refresh_shell_icons() -> None:
    """Refresh the Windows icon cache so shortcuts (start, desktop, taskbar) show the new logo after an update –
    a package update swaps the EXE, otherwise Windows keeps the old image for a long time."""
    if not IS_WIN:
        return
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)     # SHCNE_ASSOCCHANGED
        import subprocess
        subprocess.Popen(["ie4uinit.exe", "-show"], creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
    except Exception:
        pass


def is_minimized(hwnd: int) -> bool:
    return bool(IS_WIN and _user32.IsIconic(hwnd))


def client_rect(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """Client area in screen coordinates (left, top, right, bottom)."""
    if not IS_WIN:
        return None
    rect = wintypes.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    return origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom


def frame_rect(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """Visible window frame in screen coordinates (with the title bar, without the invisible resize border) – the
    area Windows Graphics Capture delivers. Fallback: GetWindowRect."""
    if not IS_WIN:
        return None
    rect = wintypes.RECT()
    try:
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
            return rect.left, rect.top, rect.right, rect.bottom          # 9 = DWMWA_EXTENDED_FRAME_BOUNDS
    except OSError:
        pass
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def capture_rect(hwnd: int, size: Optional[tuple[int, int]]) -> Optional[tuple[int, int, int, int]]:
    """Screen area that matches a captured image of size (width, height): window capture includes the title bar
    (frame_rect), the screen fallback only the client area (client_rect). Owner 09.10.2026: clicks landed ~22 px
    too low (below the raid gear) because the image had the title bar but the clicks used the client area."""
    client, frame = client_rect(hwnd), frame_rect(hwnd)
    if size is not None:
        for rect in (frame, client):
            if rect is not None and abs((rect[2] - rect[0]) - size[0]) <= 2 and abs((rect[3] - rect[1]) - size[1]) <= 2:
                return rect
    return client or frame


def set_titlebar(hwnd: int, dark: bool, caption_hex: str = "") -> None:
    """Windows title bar matching the design: dark/light and (Windows 11) in the color of the header."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes
        from ctypes import wintypes
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):                      # DWMWA_USE_IMMERSIVE_DARK_MODE (new / older Windows 10 builds)
            if dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        if caption_hex.startswith("#") and len(caption_hex) == 7:
            r, g, b = (int(caption_hex[i:i + 2], 16) for i in (1, 3, 5))
            colorref = ctypes.c_uint(r | (g << 8) | (b << 16))
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 35, ctypes.byref(colorref), ctypes.sizeof(colorref))  # Win 11
    except Exception:
        pass
