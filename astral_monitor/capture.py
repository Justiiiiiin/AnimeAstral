"""Bildquellen: Windows-Fenster-Capture (auch bei verdecktem Fenster) mit Bildschirm-Fallback.

Beide Quellen liefern nur die angeforderten Ausschnitte (billig) und das ganze Bild
nur auf Anfrage (z. B. für den Discord-Screenshot)."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional, Sequence

import cv2
import numpy as np

from . import winapi
from .imaging import crop_roi
from .settings import Roi

log = logging.getLogger("capture")


class CaptureError(RuntimeError):
    pass


@dataclass
class GrabResult:
    crops: list           # BGR-Ausschnitte in der Reihenfolge der angeforderten ROIs
    full: Optional[np.ndarray]
    size: tuple           # (Breite, Höhe) des Gesamtbildes


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
    """Windows Graphics Capture über das Paket „windows-capture“.
    Der Callback tut nichts, solange niemand ein Bild anfordert (minimale Last)."""

    name = "Fenster-Capture (WGC)"

    def __init__(self, title: str) -> None:
        self._title = title
        self._control = None
        self._pending: Optional[_Request] = None
        self._lock = threading.Lock()
        self._closed = threading.Event()

    def start(self) -> None:
        try:
            from windows_capture import WindowsCapture
        except Exception as exc:
            raise CaptureError("Das Paket „windows-capture“ fehlt (pip install windows-capture).") from exc
        hwnd = winapi.find_window(self._title)
        if hwnd is None:
            raise CaptureError(f"Fenster „{self._title}“ nicht gefunden. Ist Roblox gestartet?")
        if winapi.is_minimized(hwnd):
            raise CaptureError("Das Roblox-Fenster ist minimiert. Bitte wiederherstellen.")

        # Parameternamen unterscheiden sich je nach Version der Bibliothek -> der Reihe nach probieren
        attempts = [
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
            raise CaptureError(f"Fenster-Capture konnte nicht gestartet werden: {last_error}")

        if self.grab([], False, timeout=3.0) is None:
            self.stop()
            raise CaptureError("Vom Roblox-Fenster kommen keine Bilder an (minimiert oder verdeckt "
                               "durch Vollbild-Exklusivmodus?).")

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
                log.exception("Frame-Verarbeitung fehlgeschlagen")
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
    """Fallback: liest den Fensterbereich vom Bildschirm. Roblox muss sichtbar sein."""

    name = "Bildschirm-Capture (Fallback)"

    def __init__(self, title: str) -> None:
        self._title = title

    def start(self) -> None:
        if winapi.find_window(self._title) is None:
            raise CaptureError(f"Fenster „{self._title}“ nicht gefunden. Ist Roblox gestartet?")

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


def create_source(mode: str, title: str) -> FrameSource:
    """mode: auto | wgc | screen. Bei „auto“ erst WGC, sonst Bildschirm."""
    if mode == "screen":
        source: FrameSource = ScreenSource(title)
        source.start()
        return source
    try:
        source = WgcSource(title)
        source.start()
        return source
    except CaptureError as exc:
        if mode == "wgc":
            raise
        log.warning("%s – wechsle zur Bildschirm-Aufnahme.", exc)
        source = ScreenSource(title)
        source.start()
        return source
