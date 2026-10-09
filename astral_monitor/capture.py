"""Image sources: Windows window capture (also with a covered window) with a screen fallback.

Both sources deliver only the requested crops (cheap) and the whole image
only on request (e.g. for the Discord screenshot)."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional, Sequence

import cv2
import numpy as np

from . import winapi
from .i18n import N_, tr
from .imaging import crop_roi
from .settings import Roi

log = logging.getLogger("capture")


class CaptureError(RuntimeError):
    pass


@dataclass
class GrabResult:
    crops: list           # BGR crops in the order of the requested ROIs
    full: Optional[np.ndarray]
    size: tuple           # (width, height) of the whole image


class FrameSource:
    name = "?"

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def is_alive(self) -> bool:
        return True

    def grab(self, rois: Sequence[Roi], full: bool = False,
             timeout: float = 1.0) -> Optional[GrabResult]:
        raise NotImplementedError


class _Request:
    def __init__(self, rois: Sequence[Roi], full: bool) -> None:
        self.rois, self.full = list(rois), full
        self.event = threading.Event()
        self.result: Optional[GrabResult] = None


class WgcSource(FrameSource):
    """Windows Graphics Capture via the package “windows-capture”.
    The callback does nothing as long as nobody requests an image (minimal load)."""

    name = N_("Window capture (WGC)")

    def __init__(self, title: str, min_interval_ms: int = 125) -> None:
        self._title = title
        # Without throttling Windows delivers every game frame (up to 60/s) and the library copies each of them into
        # memory – measured ~7 % of a core. With 125 ms it's ~8 frames/s and ~0.8 %.
        self._min_interval_ms = int(min_interval_ms)
        self._control = None
        self._pending: Optional[_Request] = None
        self._lock = threading.Lock()
        self._closed = threading.Event()

    def start(self) -> None:
        try:
            from windows_capture import WindowsCapture
        except Exception as exc:
            raise CaptureError(tr("The package “windows-capture” is missing (pip install windows-capture).")) from exc
        hwnd = winapi.find_window(self._title)
        if hwnd is None:
            raise CaptureError(tr("Window “{title}” not found. Is Roblox running?", title=self._title))
        if winapi.is_minimized(hwnd):
            raise CaptureError(tr("The Roblox window is minimized. Please restore it."))

        # parameter names differ depending on the library version -> try them in order
        attempts = [
            dict(window_hwnd=hwnd, cursor_capture=False, draw_border=False,
                 minimum_update_interval=self._min_interval_ms),
            dict(window_hwnd=hwnd, cursor_capture=False, draw_border=False),
            dict(window_name=self._title, cursor_capture=False, draw_border=False),
            dict(window_name=self._title, capture_cursor=False, draw_border=False),
            dict(window_name=self._title),
        ]
        last_error: Optional[Exception] = None
        for kwargs in attempts:
            try:
                capture = WindowsCapture(**kwargs)
                self._install_handlers(capture)
                self._closed.clear()
                self._control = capture.start_free_threaded()
                break
            except Exception as exc:
                last_error, self._control = exc, None
        if self._control is None:
            raise CaptureError(tr("Window capture could not be started: {error}", error=last_error))

        if self.grab([], False, timeout=3.0) is None:
            self.stop()
            raise CaptureError(tr("No images are coming from the Roblox window (minimized or covered by exclusive "
                                  "fullscreen?)."))

    def _install_handlers(self, capture) -> None:
        @capture.event
        def on_frame_arrived(frame, capture_control):
            req = self._pending
            if req is None:
                return
            self._pending = None
            try:
                buf = frame.frame_buffer                       # BGRA
                h, w = buf.shape[:2]
                crops = [np.ascontiguousarray(crop_roi(buf, r)[:, :, :3]) for r in req.rois]
                full = np.ascontiguousarray(buf[:, :, :3]) if req.full else None
                req.result = GrabResult(crops, full, (w, h))
            except Exception:
                log.exception("Processing a frame failed")
            finally:
                req.event.set()

        @capture.event
        def on_closed():
            self._closed.set()

    def is_alive(self) -> bool:
        return self._control is not None and not self._closed.is_set()

    def grab(self, rois, full=False, timeout=1.0):
        if self._control is None or self._closed.is_set():
            return None
        with self._lock:
            request = _Request(rois, full)
            self._pending = request
            if not request.event.wait(timeout):
                self._pending = None
                return None
            return request.result

    def stop(self) -> None:
        control, self._control = self._control, None
        if control is not None:
            try:
                control.stop()
            except Exception:
                log.debug("Capture-Stopp meldete einen Fehler", exc_info=True)


class ScreenSource(FrameSource):
    """Fallback: reads the window area from the screen. Roblox must be visible."""

    name = N_("Screen capture (fallback)")

    def __init__(self, title: str) -> None:
        self._title = title

    def start(self) -> None:
        if winapi.find_window(self._title) is None:
            raise CaptureError(tr("Window “{title}” not found. Is Roblox running?", title=self._title))

    def grab(self, rois, full=False, timeout=1.0):
        from PIL import ImageGrab
        hwnd = winapi.find_window(self._title)
        if hwnd is None or winapi.is_minimized(hwnd):
            return None
        rect = winapi.client_rect(hwnd)
        if rect is None:
            return None
        left, top, right, bottom = rect
        w, h = right - left, bottom - top
        if w < 50 or h < 50:
            return None

        def shot(x0, y0, x1, y1):
            img = ImageGrab.grab(bbox=(left + x0, top + y0, left + x1, top + y1), all_screens=True)
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

        crops = [shot(*roi.abs_box(w, h)) for roi in rois]
        return GrabResult(crops, shot(0, 0, w, h) if full else None, (w, h))


def create_source(mode: str, title: str, min_interval_ms: int = 125) -> FrameSource:
    """mode: auto | wgc | screen. With “auto” first WGC, otherwise the screen."""
    if mode == "screen":
        source: FrameSource = ScreenSource(title)
        source.start()
        return source
    try:
        source = WgcSource(title, min_interval_ms)
        source.start()
        return source
    except CaptureError as exc:
        if mode == "wgc":
            raise
        log.warning("%s – switching to screen capture.", exc)
        source = ScreenSource(title)
        source.start()
        return source
