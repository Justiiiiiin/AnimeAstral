"""Automatik (Beta, Standard aus, Wunsch des Eigentümers 07.10.2026): Wege im Spiel anhand der Oberflächen-Karte
(uimap) gehen – Teleporter öffnen, zur Welt scrollen, Symbol anklicken, prüfen, ob das richtige Menü offen ist;
Pets-Roll „Auto!“ drücken. Eingaben per SendInput (wie Anti-AFK, AutoHotkey und Autoclicker), nur mit Roblox im
Vordergrund. Not-Aus: Maus bewegen oder Esc – jede Aktion prüft das vorher.

Ablauf in einem eigenen Thread; Meldungen über log(text). Ohne Qt."""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

import numpy as np

from . import vision, winapi
from .i18n import tr
from .uimap import ROW, UiMap, match_row, world_number

_log = logging.getLogger("makro")

STEP_WAIT = 0.15          # Abstand der Prüfungen nach einem Klick
OPEN_TIMEOUT = 5.0        # so lange darf ein Menü zum Öffnen brauchen
SCROLL_NOTCHES = 4        # Mausrad-Rasten je Schritt
BAR_STEP = 0.15           # Scrollbalken je Schritt um diesen Anteil der Schiene ziehen
MAX_SCROLLS = 60
USER_MOVE_PX = 25         # Maus so weit von der gesetzten Stelle = der Nutzer greift ein -> Stopp
AUTO_SETTLE = 0.8         # nach „Auto!“ kurz warten, dann schließen (Auto-Roll läuft im Hintergrund weiter)


_ACTIVE = threading.Event()    # ein Makro-Ablauf läuft gerade (Anti-AFK wartet dann)


def macro_running() -> bool:
    return _ACTIVE.is_set()


class Stop(Exception):
    """Abbruch (Nutzer, Zeitüberschreitung, nicht gefunden) – Text = Grund für das Protokoll."""


class Navigator:
    def __init__(self, source_factory: Callable, window_title: str, ocr_factory: Callable,
                 log: Callable[[str], None], uimap: Optional[UiMap] = None) -> None:
        self.source_factory = source_factory              # () -> Bildquelle (grab(rois, full, timeout))
        self.window_title = window_title
        self.ocr_factory = ocr_factory
        self._ui_log = log
        self.map = uimap or UiMap.load()
        self._halt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._source = None
        self._ocr = None
        self._hwnd = None
        self._cursor: Optional[tuple[int, int]] = None
        self._names: dict[bytes, str] = {}
        self._menu: Optional[vision.MenuFrame] = None
        self._rows: Optional[vision.RowFinder] = None
        self._templates: list = []

    def log(self, text: str) -> None:
        _log.info("Makro: %s", text)
        self._ui_log(text)

    # ------------------------------------------------------------------ Steuerung
    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._halt.set()

    def start(self, label: str, job: Callable[[], None]) -> bool:
        if self.busy:
            return False
        self._halt.clear()
        self._thread = threading.Thread(target=self._run, args=(label, job), daemon=True, name="Automatik")
        self._thread.start()
        return True

    def navigate(self, target: str) -> bool:
        return self.start(tr("Hin navigieren: {target}", target=target), lambda: self._open(self._window(target)))

    def pets_auto(self, world: str, close_after: bool = True) -> bool:
        return self.start(tr("Pets rollen: {world}", world=world), lambda: self._pets_auto(world, close_after))

    def close_menu(self) -> bool:
        return self.start(tr("Menü schließen"), self._close_any)

    def _run(self, label: str, job: Callable[[], None]) -> None:
        self.log("▶ " + label)
        _ACTIVE.set()
        try:
            self._prepare()
            job()
            self.log("✔ " + tr("Fertig."))
        except Stop as exc:
            self.log("■ " + str(exc))
        except Exception as exc:  # noqa: BLE001 – nie den Thread hart abbrechen lassen
            self.log("✖ " + tr("Fehler: {error}", error=exc))
        finally:
            _ACTIVE.clear()
            if self._source is not None:
                try:
                    self._source.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._source = None

    def _prepare(self) -> None:
        if not self.map.entries:
            raise Stop(tr("Keine Oberflächen-Karte vorhanden."))
        self._hwnd = winapi.find_window(self.window_title)
        if self._hwnd is None:
            raise Stop(tr("Roblox-Fenster nicht gefunden"))
        if winapi.is_minimized(self._hwnd):
            raise Stop(tr("Roblox ist minimiert"))
        if self._ocr is None:
            self._ocr = self.ocr_factory()                # eigene Texterkennung (nicht die der Überwachung)
        if self._menu is None:
            lists = self.map.list_windows()
            if not lists:
                raise Stop(tr("Die Karte hat keinen Teleporter mit Welten."))
            lw = lists[0]
            img = self.map.image(lw)
            row = next((r for r in self.map.rows(lw) if self.map.image(r) is not None), None)
            if img is None or row is None:
                raise Stop(tr("Der Karte fehlen Erkennungsbilder."))
            self._menu = vision.MenuFrame(lw, img, self._ocr)
            self._rows = vision.RowFinder(row, self.map.image(row))
            self._templates = vision.template_menus(self.map)
        self._source = self.source_factory()
        from .antiafk import _bring_to_front
        if not _bring_to_front(self._hwnd):
            raise Stop(tr("Roblox ließ sich nicht nach vorne holen."))
        time.sleep(0.25)
        self._cursor = None

    # ------------------------------------------------------------------ Bild + Zustand
    def _frame(self) -> np.ndarray:
        self._check()
        res = self._source.grab([], full=True, timeout=1.5)
        if res is None or res.full is None:
            raise Stop(tr("Kein Bild vom Roblox-Fenster."))
        return res.full

    def _screen(self, frame: np.ndarray) -> tuple[str, object]:
        """("template", Vorlage) | ("menu", (lage, titel, x)) | ("none", None)."""
        for t in self._templates:
            if t.seen(frame):
                return "template", t
        st = self._menu.state(frame, self._ocr)
        return ("menu", st) if st is not None else ("none", None)

    # ------------------------------------------------------------------ Wege
    def _window(self, name: str) -> dict:
        w = self.map.container(name)
        if w is None:
            raise Stop(tr("„{name}“ steht nicht in der Karte.", name=name))
        return w

    def _open(self, window: dict) -> None:
        """Fenster öffnen: über seinen Knopf – liegt der in einer Welt-Zeile, vorher Teleporter + zur Welt scrollen;
        liegt er in einem anderen Fenster, erst jenes öffnen."""
        if self._is_open(window, self._frame()):
            self.log(tr("„{name}“ ist schon offen.", name=window["name"]))
            return
        button = self.map.opener_of(window)
        if button is None:
            raise Stop(tr("Für „{name}“ ist kein Knopf hinterlegt.", name=window["name"]))
        holder = self.map.parent(button)
        if holder is not None and holder.get("name") == window.get("name"):
            holder = None                                 # Knopf versehentlich „im“ eigenen Fenster eingetragen
        if holder is not None and holder.get("kind") == ROW:
            row_list = self.map.parent(holder)
            self._open_list(row_list)
            box = self._scroll_to(row_list, holder)
            self.log(tr("Welt „{world}“ gefunden – klicke „{button}“.", world=holder["name"], button=button["name"]))
            self._click_rel(box, button["rel"])
        else:
            if holder is not None and not self._is_open(holder, self._frame()):
                self._open(holder)
            elif holder is None:
                self._close_any()
            self.log(tr("Klicke „{button}“.", button=button["name"]))
            self._click_roi(button["roi"])
        self._wait_open(window)

    def _open_list(self, row_list: dict) -> None:
        kind, st = self._screen(self._frame())
        if kind == "menu" and self._menu.is_base(st[1]):
            return                                        # Teleporter ist schon offen
        if kind != "none":
            self._close_any()
        opener = self.map.opener_of(row_list)
        if opener is None:
            raise Stop(tr("Für „{name}“ ist kein Knopf hinterlegt.", name=row_list["name"]))
        self.log(tr("Öffne „{name}“.", name=row_list["name"]))
        self._click_roi(opener["roi"])
        end = time.monotonic() + OPEN_TIMEOUT
        while time.monotonic() < end:
            time.sleep(STEP_WAIT)
            kind, st = self._screen(self._frame())
            if kind == "menu" and self._menu.is_base(st[1]):
                return
        raise Stop(tr("„{name}“ ging nicht auf.", name=row_list["name"]))

    def _visible_rows(self, frame: np.ndarray, row_list: dict) -> list[tuple[dict, list[float]]]:
        rows = self.map.rows(row_list)
        out = []
        for r in self._rows.find(frame, row_list["roi"]):
            import cv2
            key = (cv2.resize(cv2.cvtColor(r.image, cv2.COLOR_BGR2GRAY), (96, 12)) // 16).tobytes()
            name = self._names.get(key)
            if name is None:
                name = self._names[key] = vision.read_row_name(r.image, self._ocr)
            hit = match_row(name, rows)
            if hit is not None:
                out.append((hit, r.roi))
        return out

    def _scroll_to(self, row_list: dict, target: dict) -> list[float]:
        """Zur Welt-Zeile scrollen und ihre aktuelle Lage liefern. Erst Mausrad über der Liste (vorher Maus bewegen,
        sonst ignoriert Roblox das Rad); bewegt sich die Liste damit nicht, den Scrollbalken ziehen."""
        want = world_number(target["name"])
        x0, y0, x1, y1 = row_list["roi"]
        over = ((x0 + x1) / 2, (y0 + y1) / 2)
        last = None
        stuck = 0
        use_bar = False
        for step in range(MAX_SCROLLS):
            frame = self._frame()
            visible = self._visible_rows(frame, row_list)
            for row, roi in visible:
                if row["name"] == target["name"]:
                    return roi
            numbers = [n for n in (world_number(r["name"]) for r, _ in visible) if n is not None]
            if want is None or not numbers:
                direction = -1                            # nichts lesbar: nach unten suchen
            else:
                direction = -1 if want > max(numbers) else 1
            # Lage der sichtbaren Zeilen vergleichen (nicht nur Namen: kleine Schritte zeigen dieselben Welten)
            layout = tuple((r["name"], round(roi[1], 3)) for r, roi in visible)
            moved = last is None or layout != last
            last = layout
            _log.info("Makro: Schritt %d, sichtbar %s, Ziel %s (%s), Richtung %s, bewegt %s", step,
                      [f"{n}@{y}" for n, y in layout], target["name"], want, "runter" if direction < 0 else "hoch",
                      moved)
            if not moved:
                stuck += 1
                if not use_bar and stuck >= 2:            # Mausrad wirkt nicht: Scrollbalken versuchen
                    use_bar = self._scrollbar(row_list) is not None
                    if use_bar:
                        self.log(tr("Mausrad bewegt die Liste nicht – ziehe den Scrollbalken."))
                        stuck = 0
                if stuck >= 3:
                    raise Stop(tr("Welt „{world}“ nicht gefunden (Liste bewegt sich nicht).",
                                  world=target["name"]))
            else:
                stuck = 0
            if use_bar:
                self._drag_scrollbar(row_list, frame, direction)
            else:
                self._wheel(over, direction * SCROLL_NOTCHES)
            time.sleep(0.45)                              # Liste gleitet nach
        raise Stop(tr("Welt „{world}“ nicht gefunden.", world=target["name"]))

    def _scrollbar(self, row_list: dict) -> Optional[dict]:
        return next((e for e in self.map.children(row_list) if e.get("kind") == "Scrollbalken" and e.get("roi")), None)

    def _drag_scrollbar(self, row_list: dict, frame: np.ndarray, direction: int) -> None:
        """Griff des Scrollbalkens suchen (hellster Abschnitt der Schiene) und ein Stück nach oben/unten ziehen."""
        bar = self._scrollbar(row_list)
        if bar is None:
            raise Stop(tr("Kein Scrollbalken in der Karte."))
        fh, fw = frame.shape[:2]
        x0, y0, x1, y1 = bar["roi"]
        strip = frame[int(y0 * fh):int(y1 * fh), max(0, int(x0 * fw) - 2):int(x1 * fw) + 2]
        if strip.size == 0:
            raise Stop(tr("Kein Scrollbalken in der Karte."))
        rows = strip.mean(axis=(1, 2))                    # Helligkeit je Bildzeile
        bright = rows > (np.median(rows) + 25)
        ys = np.flatnonzero(bright)
        if ys.size:
            grip = (ys[0] + ys[-1]) / 2 / len(rows)       # Mitte des Griffs (Anteil der Schiene)
        else:
            grip = 0.0 if direction < 0 else 1.0          # Griff nicht erkennbar: am Ende anfassen
        start = (x0 + x1) / 2, y0 + grip * (y1 - y0)
        delta = (y1 - y0) * BAR_STEP * (1 if direction < 0 else -1)
        end = start[0], min(y1, max(y0, start[1] + delta))
        _log.info("Makro: Scrollbalken ziehen %.3f -> %.3f (Griff %s)", start[1], end[1], bool(ys.size))
        self._drag(start, end)

    def _drag(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        self._check()
        sx, sy = self._point(*start)
        ex, ey = self._point(*end)
        u32 = ctypes.windll.user32
        u32.SetCursorPos(sx - 2, sy - 2)
        for _ in range(3):
            _mouse(0x0001, 1, 1)
            time.sleep(0.025)
        u32.SetCursorPos(sx, sy)
        time.sleep(0.06)
        _mouse(0x0002)                                    # drücken
        steps = 12
        for k in range(1, steps + 1):                     # gleichmäßig ziehen (Roblox braucht Zwischenschritte)
            u32.SetCursorPos(sx, int(sy + (ey - sy) * k / steps))
            _mouse(0x0001, 0, 0)
            time.sleep(0.02)
        time.sleep(0.05)
        _mouse(0x0004)                                    # loslassen
        self._cursor = (ex, ey)

    def _is_open(self, window: dict, frame: np.ndarray) -> bool:
        kind, st = self._screen(frame)
        template = self.map.template_of(window)
        if kind == "template":
            return template is not None and st.window["name"] == template["name"]
        if kind == "menu" and template is None:
            if (window.get("extra") or {}).get("template"):
                return False
            if self.map.list_windows() and window["name"] == self.map.list_windows()[0]["name"]:
                return self._menu.is_base(st[1])
            return vision.similar_title(st[1], window["name"])
        return False

    def _wait_open(self, window: dict) -> None:
        end = time.monotonic() + OPEN_TIMEOUT
        seen = ""
        while time.monotonic() < end:
            time.sleep(STEP_WAIT)
            frame = self._frame()
            if self._is_open(window, frame):
                self.log(tr("„{name}“ ist offen.", name=window["name"]))
                return
            kind, st = self._screen(frame)
            if kind == "menu" and st[1] and not self._menu.is_base(st[1]):
                seen = st[1]
        if seen:                                          # ein Menü ist offen, Titel passt aber nicht genau
            self.log(tr("Offen ist „{title}“ – passt der Name „{name}“?", title=seen, name=window["name"]))
            return
        raise Stop(tr("„{name}“ ging nicht auf.", name=window["name"]))

    def _close_any(self) -> None:
        for _ in range(3):
            kind, st = self._screen(self._frame())
            if kind == "none":
                return
            if kind == "template":
                close = self.map.close_element(st.window)
                if close is None:
                    raise Stop(tr("Kein Schließen-Knopf in „{name}“.", name=st.window["name"]))
                self.log(tr("Schließe „{name}“.", name=st.window["name"]))
                self._click_roi(close["roi"])
            else:
                self.log(tr("Schließe „{name}“.", name=st[1] or "?"))
                self._click(st[2])
            time.sleep(0.6)
        raise Stop(tr("Menü ließ sich nicht schließen."))

    def _pets_auto(self, world: str, close_after: bool = True) -> None:
        window = self._window(f"{world} Pets-Roll")
        self._open(window)
        auto = self.map.element(window, "Auto!")
        cost = self.map.element(window, "Kosten (Yen)")
        if cost is not None:
            text = vision.read_text(self._frame(), cost["roi"], self._ocr)
            self.log(tr("Kosten pro Pet: {cost}", cost=text or "?"))
        if auto is None:
            raise Stop(tr("„Auto!“ fehlt in der Karte."))
        self.log(tr("Klicke „Auto!“."))
        self._click_roi(auto["roi"])
        if close_after:
            self._close_after_auto(window)

    def _close_after_auto(self, window: dict) -> None:
        """Nach „Auto!“ sofort schließen: das Spiel rollt im Hintergrund weiter (bis die Yen alle sind). Warten wäre
        unnötig lang (Wunsch des Eigentümers 07.10.2026)."""
        close = self.map.close_element(window)
        if close is None:
            return                                        # Karte unvollständig: offen lassen
        time.sleep(AUTO_SETTLE)                           # Spiel den Klick auf „Auto!“ verarbeiten lassen
        self.log(tr("Auto-Roll läuft im Hintergrund – schließe das Menü."))
        self._click_roi(close["roi"])

    # ------------------------------------------------------------------ Eingaben (nur mit Roblox vorne)
    def _check(self) -> None:
        if self._halt.is_set():
            raise Stop(tr("Gestoppt."))
        u32 = ctypes.windll.user32
        if u32.GetAsyncKeyState(0x1B) & 0x8000:           # Esc
            raise Stop(tr("Abgebrochen (Esc)."))
        if self._cursor is not None:
            pt = wintypes.POINT()
            u32.GetCursorPos(ctypes.byref(pt))
            if abs(pt.x - self._cursor[0]) > USER_MOVE_PX or abs(pt.y - self._cursor[1]) > USER_MOVE_PX:
                raise Stop(tr("Abgebrochen – Maus wurde bewegt."))
        u32.GetForegroundWindow.restype = wintypes.HWND
        if u32.GetForegroundWindow() != self._hwnd:
            raise Stop(tr("Abgebrochen – Roblox ist nicht mehr im Vordergrund."))

    def _point(self, fx: float, fy: float) -> tuple[int, int]:
        rect = winapi.client_rect(self._hwnd)
        if rect is None:
            raise Stop(tr("Roblox-Fenster nicht gefunden"))
        left, top, right, bottom = rect
        return int(left + fx * (right - left)), int(top + fy * (bottom - top))

    def _click_roi(self, roi: list[float]) -> None:
        self._click(((roi[0] + roi[2]) / 2, (roi[1] + roi[3]) / 2))

    def _click_rel(self, box: list[float], rel: list[float]) -> None:
        x0, y0, x1, y1 = box
        self._click((x0 + (rel[0] + rel[2]) / 2 * (x1 - x0), y0 + (rel[1] + rel[3]) / 2 * (y1 - y0)))

    def _click(self, pos: tuple[float, float]) -> None:
        self._check()
        x, y = self._point(*pos)
        u32 = ctypes.windll.user32
        u32.SetCursorPos(x - 3, y - 3)
        time.sleep(0.04)
        for _ in range(3):                                # echte Bewegung, sonst kein „Hover“ in Roblox
            _mouse(0x0001, 1, 1)
            time.sleep(0.025)
        u32.SetCursorPos(x, y)
        self._cursor = (x, y)
        time.sleep(0.07)
        _mouse(0x0002)                                    # links drücken
        time.sleep(0.06)
        _mouse(0x0004)                                    # loslassen
        time.sleep(0.12)

    def _wheel(self, pos: tuple[float, float], notches: int) -> None:
        self._check()
        x, y = self._point(*pos)
        u32 = ctypes.windll.user32
        u32.SetCursorPos(x - 3, y - 3)
        for _ in range(3):                                # echte Bewegung: sonst gilt die Liste nicht als „unter der
            _mouse(0x0001, 1, 1)                          # Maus“ und Roblox ignoriert das Rad
            time.sleep(0.025)
        u32.SetCursorPos(x, y)
        self._cursor = (x, y)
        time.sleep(0.08)
        step = 1 if notches > 0 else -1
        for _ in range(abs(notches)):
            _mouse(0x0800, data=120 * step)               # MOUSEEVENTF_WHEEL (+ = hoch, - = runter)
            time.sleep(0.05)


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> None:
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    inp = INPUT(type=0)
    inp.mi = MOUSEINPUT(dx, dy, ctypes.c_uint32(data & 0xFFFFFFFF).value, flags, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
