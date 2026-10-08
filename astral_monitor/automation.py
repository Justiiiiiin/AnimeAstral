"""Automatik (Beta, Standard aus, Wunsch des Eigentümers 07.10.2026): Wege im Spiel anhand der Oberflächen-Karte
(uimap) gehen – Teleporter öffnen, zur Welt scrollen, Symbol anklicken, prüfen, ob das richtige Menü offen ist;
Pets-Roll „Auto!“ drücken. Eingaben per SendInput (wie Anti-AFK, AutoHotkey und Autoclicker), nur mit Roblox im
Vordergrund. Not-Aus: Maus bewegen oder Esc – jede Aktion prüft das vorher.

Ablauf in einem eigenen Thread; Meldungen über log(text). Ohne Qt."""
from __future__ import annotations

import ctypes
import logging
import re
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Optional

import cv2
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


TASK_KINDS = ("raid", "autoroll", "gigs", "guild_claim", "wait",
              "raid_farm", "raid_leave", "raid_create", "raid_join", "navigate", "pets", "close")   # ab raid_farm: ältere
RAID_KINDS = ("raid", "raid_farm", "raid_create", "raid_join")     # Aufgaben, die in einen Raid/Modus führen
CLAIM_LIMIT = 8           # höchstens so viele „Claim“ je Seite (Schutz gegen Endlosschleifen)
GIGS_PETS = 3             # „Send Pets“: je Gig 1 Pet, reihum eins der letzten 3 (Eigentümer 08.10.2026)
GUILD_EVERY = 3 * 3600    # Gilden-Missionen: so oft nachsehen (Tagesaufgaben, Reset einmal am Tag)
EXTRA_RETRY = 15 * 60     # nach einem Fehlschlag frühestens so viel später erneut
RAID_GEAR = Path(__file__).with_name("uimap_static") / "raid_gear.png"   # Zahnrad oben rechts im Raid (fest, nicht aus der Karte)
GEAR_REGION = [0.4, 0.0, 0.9, 0.16]
LEAVE_REGION = [0.35, 0.0, 0.75, 0.2]
GEAR_HIT = 0.75


def task_label(task: dict) -> str:
    """Anzeige einer Aufgabe der Warteschlange."""
    kind = task.get("kind")
    if kind == "autoroll":
        return tr("Auto Roll: {target}", target=task.get("target", "?"))
    if kind == "raid":
        until = task.get("until", "runs")
        text = tr("Raid: {target}", target=task.get("target", "?"))
        if until == "runs":
            text += " · " + tr("{runs} Raids", runs=int(task.get("runs", 1)))
        elif until == "minutes":
            text += " · " + tr("{minutes} Min.", minutes=int(task.get("minutes", 30)))
        else:
            text += " · " + tr("ohne Ende")
        if int(task.get("leave_wave", 0)):
            text += " · " + tr("Leave ab Welle {wave}", wave=int(task["leave_wave"]))
        return text + (" · " + tr("beitreten") if task.get("join") else "")
    if kind == "gigs":
        return tr("Fixer Gigs abholen")
    if kind == "guild_claim":
        return tr("Gilde: Missionen abholen")
    if kind == "raid_farm":
        text = tr("Raid farmen: {target} × {runs}", target=task.get("target", "?"), runs=int(task.get("runs", 1)))
        if int(task.get("leave_wave", 0)):
            text += " · " + tr("Leave ab Welle {wave}", wave=int(task["leave_wave"]))
        return text + (" · " + tr("beitreten") if task.get("join") else "")
    if kind == "raid_leave":
        return tr("Raid verlassen")
    if kind == "raid_create":
        return tr("Raid starten: {target}", target=task.get("target", "?"))
    if kind == "raid_join":
        return tr("Raid beitreten: {target}", target=task.get("target", "?"))
    if kind == "navigate":
        return tr("Öffnen: {target}", target=task.get("target", "?"))
    if kind == "pets":
        return tr("Pets rollen (Auto!): {world}", world=task.get("world", "?"))
    if kind == "close":
        return tr("Menü schließen")
    if kind == "wait":
        seconds = int(task.get("seconds", 60))
        return tr("Warten: {minutes} Min.", minutes=seconds // 60) if seconds % 60 == 0 and seconds >= 60 else \
            tr("Warten: {seconds} s", seconds=seconds)
    return str(kind)


class Stop(Exception):
    """Abbruch (Nutzer, Zeitüberschreitung, nicht gefunden) – Text = Grund für das Protokoll."""


class UserStop(Stop):
    """Vom Nutzer abgebrochen (Stopp, Esc, Maus, Roblox nicht vorne) – die Warteschlange endet sofort."""


def next_task(tasks: list[dict], index: int, loop: bool) -> Optional[dict]:
    """Aufgabe nach tasks[index] (mit Schleife wieder die erste), sonst None."""
    if index + 1 < len(tasks):
        return tasks[index + 1]
    return tasks[0] if loop and len(tasks) > 1 else None


def leave_before(task: dict, following: Optional[dict]) -> bool:
    """Raid verlassen, bevor es weitergeht? Nur wenn danach ein ANDERER Raid/Modus kommt (Eigentümer 08.10.2026) –
    für Auto Roll, Gigs, Gilde … bleibt man drin (Auto Retry farmt weiter)."""
    if following is None or following.get("kind") not in RAID_KINDS:
        return False
    return following.get("target") != task.get("target")


def _clusters(values: list[float], tol: float) -> list[list[float]]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def pet_tiles(frame: np.ndarray, grid: list[float], words: list[tuple[str, list[float]]]) -> list[list[float]]:
    """Kacheln eines Pet-Rasters aus den Namensschildern (siehe Navigator._pet_tiles); ohne Qt/OCR testbar."""
    found = [(b, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)) for w, b in words
             if len(re.sub(r"[^A-Za-z]", "", w)) >= 3 and b[3] - b[1] < 0.045]
    # Namenszeilen: mindestens drei Wörter mit ≥ 4 Buchstaben auf gleicher Höhe (Bildrauschen fällt so heraus)
    long_y = [m[1] for (b, m), (w, _x) in zip(found, [x for x in words if len(re.sub(r"[^A-Za-z]", "", x[0])) >= 3
                                                       and x[1][3] - x[1][1] < 0.045]) if len(re.sub(r"[^A-Za-z]", "", w)) >= 4]
    row_y = [float(np.median(c)) for c in _clusters(long_y, 0.02) if len(c) >= 3]
    if not row_y:
        return []
    labels = []                                           # Wörter eines Schilds („Kirito Armor“) zusammenfassen
    for y in row_y:
        boxes = sorted((b for b, m in found if abs(m[1] - y) <= 0.025), key=lambda b: b[0])
        for b in boxes:
            if labels and abs(labels[-1][1] - y) < 1e-6 and b[0] - labels[-1][2] < 0.02:
                labels[-1][2] = b[2]
            else:
                labels.append([b[0], y, b[2]])
    labels = [(None, ((x0 + x1) / 2, y)) for x0, y, x1 in labels]
    cols = [float(np.median(c)) for c in _clusters([m[0] for _b, m in labels], 0.03)]
    if len(cols) < 2:
        return []
    diffs = sorted(b - a for a, b in zip(cols, cols[1:]) if b - a > 0.04)
    if not diffs:
        return []
    steps = max(1, round((cols[-1] - cols[0]) / diffs[0]))  # kleinster Abstand ≈ eine Spalte (Lücken = fehlende
    pitch = (cols[-1] - cols[0]) / steps                     # Namen), genau über die ganze Breite gemittelt
    cols = [cols[0] + i * pitch for i in range(steps + 1)]
    row_pitch = min((b - a for a, b in zip(row_y, row_y[1:])), default=pitch * 1.75)
    fh, fw = frame.shape[:2]
    tiles = []
    for ly in row_y:
        for cx in cols:
            box = [cx - pitch * 0.45, ly - row_pitch * 0.82, cx + pitch * 0.45, ly + row_pitch * 0.08]
            named = any(box[0] <= m[0] <= box[2] and abs(m[1] - ly) <= 0.025 for _b, m in labels)
            crop = frame[max(0, int(box[1] * fh)):int(box[3] * fh), max(0, int(box[0] * fw)):int(box[2] * fw)]
            if named or (crop.size and vision.sharpness(crop) >= vision.SlotLayout.SHARP_MIN):
                tiles.append([round(v, 4) for v in box])
    return tiles


def parse_timer(text: str) -> Optional[int]:
    """„1:20:40“ / „33:57“ -> Sekunden (Fixer-Gigs-Zeiten), sonst None."""
    m = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})", text.strip())
    if not m:
        return None
    h, mnt, s = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    return h * 3600 + mnt * 60 + s if mnt < 60 and s < 60 else None


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
        self.raid_count: Optional[Callable[[], int]] = None     # Anzahl gezählter Raid-Enden (Überwachung)
        self.monitoring: Optional[Callable[[], bool]] = None    # läuft die Überwachung?
        self.start_monitoring: Optional[Callable[[], None]] = None   # Überwachung starten (über die Oberfläche)
        self.set_raid: Optional[Callable[[str], None]] = None        # Raid-Name für die Statistik setzen
        self._in_raid: Optional[str] = None               # Ziel des Raids, in dem das Makro gerade farmt
        self.gigs_next = 0.0                              # Fixer Gigs: frühestens dann wieder nachsehen (monotonic)
        self.guild_next = 0.0                             # Gilden-Missionen: frühestens dann wieder
        self.auto_gigs: Callable[[], bool] = lambda: False     # Schalter „Automatisch abholen“ (Einstellungen)
        self.auto_guild: Callable[[], bool] = lambda: False

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

    def explore(self, minutes: float, data_dir) -> bool:
        """Erkunden: neue Welten/Fenster selbst öffnen, einordnen, schließen (explorer.py)."""
        from .explorer import Explorer
        return self.start(tr("Erkunden ({minutes} Min.)", minutes=minutes),
                          lambda: Explorer(self, minutes, data_dir).run())

    def map_opened(self, button: dict) -> bool:
        return self.map.window_for(button) is not None

    def run_queue(self, tasks: list[dict], loop: bool = False) -> bool:
        """Warteschlange: Aufgaben nacheinander; mit loop von vorn, bis „Stopp“/Esc/Maus. Aufgaben siehe task_label."""
        tasks = [dict(t) for t in tasks if t.get("kind") in TASK_KINDS]
        if not tasks:
            return False
        return self.start(tr("Warteschlange ({count} Aufgaben)", count=len(tasks)), lambda: self._queue(tasks, loop))

    def _queue(self, tasks: list[dict], loop: bool) -> None:
        rounds = 0
        while True:
            rounds += 1
            if loop:
                self.log(tr("Durchlauf {n}", n=rounds))
            for i, task in enumerate(tasks):
                self.log(f"{i + 1}/{len(tasks)}  {task_label(task)}")
                following = next_task(tasks, i, loop)
                self._run_extras()                        # fällige Gigs/Gilde zuerst
                for attempt in (1, 2):                    # einmal wiederholen, dann überspringen
                    try:
                        self._task(task, following)
                        break
                    except UserStop:
                        raise
                    except Stop as exc:
                        if attempt == 2:
                            self.log("⚠ " + tr("Übersprungen: {reason}", reason=exc))
                        else:
                            self.log("⚠ " + tr("{reason} – versuche es noch einmal.", reason=exc))
                            self._close_any_quiet()
                time.sleep(0.6)                           # Spiel kurz Luft lassen
            if not loop:
                return

    def _task(self, task: dict, following: Optional[dict] = None) -> None:
        kind = task.get("kind")
        if kind == "wait":
            self._idle_wait(float(task.get("seconds", 60)))
            return
        self._focus()                                     # nach Warten/Anti-AFK wieder Roblox vorne
        if kind == "raid":
            self._raid_task(task, following)
        elif kind == "gigs":
            self._gigs()
        elif kind == "guild_claim":
            self._guild_claim()
        elif kind == "autoroll":
            self._autoroll(self._window(task.get("target", "")))
        elif kind == "raid_farm":
            self._raid_farm(self._window(task.get("target", "")), bool(task.get("join")), int(task.get("runs", 1)),
                            int(task.get("leave_wave", 0)))
        elif kind == "raid_leave":
            self._leave_raid()
        elif kind in ("raid_create", "raid_join"):
            self._raid(self._window(task.get("target", "")), join=kind == "raid_join")
        elif kind == "navigate":
            self._open(self._window(task.get("target", "")))
        elif kind == "pets":
            self._pets_auto(task.get("world", ""), bool(task.get("close", True)))
        elif kind == "close":
            self._close_any()

    # ------------------------------------------------------------------ Aufgaben im Fenster
    def autoroll(self, target: str) -> bool:
        return self.start(tr("Auto Roll: {target}", target=target), lambda: self._autoroll(self._window(target)))

    def _window_area(self, window: dict) -> tuple[list[float], np.ndarray]:
        """Lage des offenen Fensters (Standard-Rahmen, Vorlage oder ganzer Bildschirm) und aktuelles Bild."""
        frame = self._frame()
        kind, st = self._screen(frame)
        if kind == "template":
            return st.window["roi"], frame
        if kind == "menu":
            return st[0], frame
        return [0.0, 0.0, 1.0, 1.0], frame

    def _press(self, window: dict, *labels: tuple[str, ...]) -> str:
        """Knopf im offenen Fenster über seine Beschriftung finden und drücken (z. B. („auto", „roll“), („join",)).
        Mehrteilige Beschriftungen: Wörter nebeneinander in einer Zeile. Rückgabe: gedrückte Beschriftung."""
        roi, frame = self._window_area(window)
        words = vision.words_in(frame, roi, self._ocr)
        norm = [(re.sub(r"[^a-z0-9]", "", w.lower()), b) for w, b in words]
        for label in labels:
            for i, (w, box) in enumerate(norm):
                if w != label[0]:
                    continue
                boxes = [box]
                for part in label[1:]:                    # nächstes Wort rechts daneben, gleiche Zeile
                    nxt = next((b for v, b in norm if v == part and 0 <= b[0] - boxes[-1][2] < 0.03
                                and abs((b[1] + b[3]) / 2 - (boxes[-1][1] + boxes[-1][3]) / 2) < 0.015), None)
                    if nxt is None:
                        boxes = []
                        break
                    boxes.append(nxt)
                if boxes:
                    area = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                            max(b[3] for b in boxes)]
                    text = " ".join(label)
                    self.log(tr("Klicke „{button}“.", button=text))
                    self._click_roi(area)
                    return text
        raise Stop(tr("Knopf „{button}“ nicht gefunden in „{name}“.", button=" / ".join(" ".join(x) for x in labels),
                      name=window["name"]))

    def _autoroll(self, window: dict) -> None:
        """Fenster öffnen, „Auto Roll“ (Gacha, Titans) bzw. „Auto!“ (Pets) drücken, gleich wieder schließen – das
        Spiel rollt im Hintergrund weiter."""
        self._open(window)
        auto = self.map.element(window, "Auto!")
        if auto is not None:
            self.log(tr("Klicke „Auto!“."))
            self._click_roi(auto["roi"])
        else:
            self._press(window, ("auto", "roll"), ("autoroll",), ("auto",))
        time.sleep(AUTO_SETTLE)
        self.log(tr("Auto-Roll läuft im Hintergrund – schließe das Menü."))
        self._close_any()

    def _raid(self, window: dict, join: bool) -> None:
        """Raid-Fenster öffnen und „Create“/„Start“ (eigener Raid, kostet einen Schlüssel) bzw. „Join“ drücken.
        Was danach kommt (Lobby, Teleport), wird protokolliert und als Bild für die Fehlersuche gespeichert."""
        self._open(window)
        if join:
            self._press(window, ("join",))
        else:
            self._press(window, ("create",), ("start",))
        time.sleep(3.0)
        frame = self._frame()
        kind, st = self._screen(frame)
        self.log(tr("Danach: {state}", state=(st[1] if kind == "menu" else kind) or "?"))
        try:
            from .app_paths import debug_dir
            path = debug_dir() / f"makro_raid_{time.strftime('%H%M%S')}.jpg"
            small = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(str(path))
        except Exception:  # noqa: BLE001 – nur Hilfe für die Fehlersuche
            pass

    # ------------------------------------------------------------------ Raid: Zahnrad, Auto Retry, Auto Leave
    def _gear(self, frame: np.ndarray) -> Optional[list[float]]:
        """Zahnrad oben rechts neben Welle/Timer – nur im Raid sichtbar."""
        if not hasattr(self, "_gear_tpl"):
            self._gear_tpl = cv2.imdecode(np.fromfile(str(RAID_GEAR), dtype=np.uint8), cv2.IMREAD_COLOR)
        score, box = vision.find_multiscale(frame, self._gear_tpl, GEAR_REGION)
        return box if score >= GEAR_HIT else None

    def _labels(self, frame: np.ndarray) -> dict:
        """Beschriftungen im Zahnrad-Menü: {"retry": Lage, "leave": Lage, "wave": Lage des Wellen-Felds}."""
        words = vision.words_in(frame, [0.2, 0.1, 0.8, 0.9], self._ocr)
        norm = [(re.sub(r"[^a-z0-9]", "", w.lower()), b) for w, b in words]
        out = {}
        for key, second in (("retry", "retry"), ("leave", "leave")):
            for w, b in norm:
                if w != "auto":
                    continue
                nxt = next((b2 for w2, b2 in norm if w2 == second and 0 <= b2[0] - b[2] < 0.03
                            and abs((b2[1] + b2[3]) / 2 - (b[1] + b[3]) / 2) < 0.015), None)
                if nxt is not None:
                    out[key] = [b[0], min(b[1], nxt[1]), nxt[2], max(b[3], nxt[3])]
                    break
        if "leave" in out:                                # Feld „Wave 85“ direkt unter „Auto Leave“
            lv = out["leave"]
            field = next((b for w, b in norm if w == "wave" and 0 < b[1] - lv[3] < 0.08
                          and abs(b[0] - lv[0]) < 0.12), None)
            if field is not None:
                out["wave"] = field
        return out

    def _open_raid_settings(self) -> dict:
        frame = self._frame()
        labels = self._labels(frame)
        if "retry" in labels or "leave" in labels:
            return labels
        gear = self._gear(frame)
        if gear is None:
            raise Stop(tr("Kein Raid-Zahnrad gefunden – bist du im Raid?"))
        self.log(tr("Öffne die Raid-Einstellungen (Zahnrad)."))
        self._click_roi(gear)
        end = time.monotonic() + 4
        while time.monotonic() < end:
            time.sleep(0.4)
            labels = self._labels(self._frame())
            if "retry" in labels and "leave" in labels:
                return labels
        raise Stop(tr("Raid-Einstellungen gingen nicht auf."))

    def _set_toggle(self, key: str, on: bool) -> None:
        """Schalter „Auto Retry“/„Auto Leave“ setzen und nachprüfen (Meldungen verdecken oft – mehrmals lesen)."""
        name = "Auto Retry" if key == "retry" else "Auto Leave"
        for _ in range(8):
            frame = self._frame()
            label = self._labels(frame).get(key)
            if label is None:
                time.sleep(0.4)
                continue
            state = vision.toggle_state(frame, label)
            if state is None:                             # verdeckt: kurz warten, erneut lesen
                time.sleep(0.5)
                continue
            if state == on:
                self.log(tr("{name}: {state}", name=name, state=tr("an") if on else tr("aus")))
                return
            cy = (label[1] + label[3]) / 2
            self._click((label[2] + 0.05, cy))           # Schalter rechts neben der Beschriftung
            time.sleep(0.7)
        raise Stop(tr("„{name}“ ließ sich nicht sicher umschalten.", name=name))

    def _set_leave_wave(self, wave: int) -> None:
        labels = self._labels(self._frame())
        field = labels.get("wave")
        if field is None:
            raise Stop(tr("Feld für die Welle (Auto Leave) nicht gefunden."))
        from .antiafk import _key
        self._click_roi(field)
        time.sleep(0.3)
        for _ in range(6):                                # alte Zahl löschen
            _key(0x08, True, 0x0E)
            _key(0x08, False, 0x0E)
            time.sleep(0.04)
        scans = {"1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A,
                 "0": 0x0B}
        for ch in str(int(wave)):
            _key(ord(ch), True, scans[ch])
            _key(ord(ch), False, scans[ch])
            time.sleep(0.05)
        _key(0x0D, True, 0x1C)                            # Enter
        _key(0x0D, False, 0x1C)
        self.log(tr("Auto Leave ab Welle {wave}.", wave=wave))
        time.sleep(0.4)

    def _close_raid_settings(self) -> None:
        frame = self._frame()
        labels = self._labels(frame)
        if not labels:
            return
        anchor = labels.get("retry") or labels.get("leave")
        region = [anchor[0], max(0.0, anchor[1] - 0.2), min(1.0, anchor[2] + 0.25), anchor[1]]
        score, box = vision.find_multiscale(frame, self._menu.x_tpl, region, (0.4, 0.5, 0.6, 0.7, 0.8, 1.0))
        if score >= 0.6 and box is not None:
            self._click_roi(box)                          # rosa X oben rechts am Menü
        else:
            gear = self._gear(frame)
            if gear is not None:
                self._click_roi(gear)                     # Zahnrad schließt es wieder
        time.sleep(0.6)

    def _leave_raid(self) -> None:
        """Raid verlassen: erst Auto Retry aus (sonst wird man wieder hineingeworfen), dann LEAVE!."""
        self._open_raid_settings()
        self._set_toggle("retry", False)
        self._close_raid_settings()
        box = vision.find_word(self._frame(), LEAVE_REGION, self._ocr, "leave", "leave!")
        if box is None:
            raise Stop(tr("„LEAVE!“ nicht gefunden."))
        self.log(tr("Klicke „{button}“.", button="LEAVE!"))
        self._click_roi(box)
        time.sleep(3.0)

    def _raid_farm(self, window: dict, join: bool, runs: int, leave_wave: int) -> None:
        """Raid starten/beitreten, Auto Retry an (+ Auto Leave ab Welle N), warten bis die Überwachung N Raid-Enden
        gezählt hat, dann Auto Retry aus und verlassen."""
        if self.monitoring is None or self.raid_count is None or not self.monitoring():
            raise Stop(tr("Für „Raid farmen“ muss die Überwachung laufen (sie zählt die Raids)."))
        self._raid(window, join)
        end = time.monotonic() + 120                      # bis man im Raid ist (Teleport, Lobby)
        while self._gear(self._frame()) is None:
            if time.monotonic() > end:
                raise Stop(tr("Nicht im Raid angekommen."))
            time.sleep(1.0)
        self._open_raid_settings()
        self._set_toggle("retry", True)
        self._set_toggle("leave", leave_wave > 0)
        if leave_wave > 0:
            self._set_leave_wave(leave_wave)
        self._close_raid_settings()
        start = self.raid_count()
        self.log(tr("Farme {runs} Raids …", runs=runs))
        _ACTIVE.clear()                                   # beim Warten darf das Anti-AFK laufen
        try:
            last = 0
            while True:
                done = self.raid_count() - start
                if done >= runs:
                    break
                if done != last:
                    last = done
                    self.log(tr("{done}/{runs} Raids", done=done, runs=runs))
                if self._halt.wait(2.0):
                    raise UserStop(tr("Gestoppt."))
                if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                    raise UserStop(tr("Abgebrochen (Esc)."))
        finally:
            _ACTIVE.set()
        self._focus()
        self._leave_raid()

    # ------------------------------------------------------------------ Automatisch abholen (eigene Schalter)
    def due_extras(self) -> list[str]:
        """Fällige Zusatzaufgaben: Fixer Gigs (nach ihren Zeiten) und Gilden-Missionen (alle GUILD_EVERY) – keine
        Aufgaben der Warteschlange, sondern eigene Schalter; laufen zwischen den Aufgaben und während ein Raid farmt."""
        now = time.monotonic()
        due = []
        if self.auto_gigs() and now >= self.gigs_next and self.map.container("Fixer Gigs") is not None:
            due.append("gigs")
        if self.auto_guild() and now >= self.guild_next:
            due.append("guild")
        return due

    def run_extras(self) -> bool:
        """Von der Oberfläche, wenn sonst nichts läuft."""
        return self.start(tr("Automatisch abholen"), self._run_extras)

    def _run_extras(self) -> None:
        for kind in self.due_extras():
            self._focus()
            try:
                if kind == "gigs":
                    self._gigs()
                else:
                    self._guild_claim()
                    self.guild_next = time.monotonic() + GUILD_EVERY
            except UserStop:
                raise
            except Stop as exc:
                self.log("⚠ " + tr("{task}: {reason} – nächster Versuch in 15 Min.",
                                   task=tr("Fixer Gigs") if kind == "gigs" else tr("Gilde"), reason=exc))
                if kind == "gigs":
                    self.gigs_next = time.monotonic() + EXTRA_RETRY
                else:
                    self.guild_next = time.monotonic() + EXTRA_RETRY
                self._close_any_quiet()

    def _extras_while_waiting(self) -> None:
        """Beim Warten (Raid farmt, „Warten“): fällige Zusatzaufgaben einschieben, danach weiter warten."""
        if not self.due_extras():
            return
        _ACTIVE.set()
        try:
            self._run_extras()
        finally:
            _ACTIVE.clear()

    # ------------------------------------------------------------------ Raid (eine Aufgabe statt vier)
    def _ensure_monitoring(self) -> None:
        if self.monitoring is None or self.raid_count is None:
            raise Stop(tr("Für Raids muss die Überwachung laufen (sie zählt die Raids)."))
        if self.monitoring():
            return
        if self.start_monitoring is None:
            raise Stop(tr("Für Raids muss die Überwachung laufen (sie zählt die Raids)."))
        self.log(tr("Starte die Überwachung (zählt die Raids)."))
        self.start_monitoring()
        end = time.monotonic() + 15
        while not self.monitoring():
            if time.monotonic() > end:
                raise Stop(tr("Überwachung ließ sich nicht starten."))
            self._check()
            time.sleep(0.3)

    def _raid_task(self, task: dict, following: Optional[dict]) -> None:
        """Raid starten/beitreten (außer man farmt schon genau diesen), Auto Retry + Auto Leave einstellen, bis zum
        Ende farmen (N Raids, M Minuten oder ohne Ende), danach nur verlassen, wenn ein anderer Raid/Modus folgt."""
        target = task.get("target", "")
        self._ensure_monitoring()
        if self.set_raid is not None:
            self.set_raid(target)
        leave_wave = int(task.get("leave_wave", 0))
        if self._in_raid == target and self._gear(self._frame()) is not None:
            self.log(tr("Schon im Raid „{name}“ – farme weiter.", name=target))
        else:
            if self._gear(self._frame()) is not None:     # noch in einem anderen Raid
                self._leave_raid()
            self._in_raid = None
            self._raid(self._window(target), bool(task.get("join")))
            end = time.monotonic() + 120                  # bis man im Raid ist (Teleport, Lobby)
            while self._gear(self._frame()) is None:
                if time.monotonic() > end:
                    raise Stop(tr("Nicht im Raid angekommen."))
                time.sleep(1.0)
            self._in_raid = target
        self._open_raid_settings()
        self._set_toggle("retry", True)
        self._set_toggle("leave", leave_wave > 0)
        if leave_wave > 0:
            self._set_leave_wave(leave_wave)
        self._close_raid_settings()
        until = task.get("until", "runs")
        runs, minutes = int(task.get("runs", 1)), float(task.get("minutes", 30))
        start, t0 = self.raid_count(), time.monotonic()
        self.log({"runs": tr("Farme {runs} Raids …", runs=runs),
                  "minutes": tr("Farme {minutes} Min. …", minutes=int(minutes))}.get(until, tr("Farme ohne Ende …")))
        _ACTIVE.clear()                                   # beim Warten darf das Anti-AFK laufen
        try:
            last = 0
            while True:
                done = self.raid_count() - start
                if until == "runs" and done >= runs:
                    break
                if until == "minutes" and time.monotonic() - t0 >= minutes * 60:
                    break
                if done != last:
                    last = done
                    self.log(tr("{done} Raids fertig", done=done))
                self._extras_while_waiting()
                if self._halt.wait(2.0):
                    raise UserStop(tr("Gestoppt."))
                if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                    raise UserStop(tr("Abgebrochen (Esc)."))
        finally:
            _ACTIVE.set()
        self._focus()
        if leave_before(task, following):
            self.log(tr("Als Nächstes kommt ein anderer Raid – verlasse diesen."))
            self._leave_raid()
            self._in_raid = None
        else:
            self.log(tr("Bleibe im Raid (Auto Retry farmt weiter)."))

    # ------------------------------------------------------------------ Claim-Hilfen
    def _words(self) -> tuple[list[tuple[str, list[float]]], list[float]]:
        roi, frame = self._window_area({"name": "?"})
        return vision.words_in(frame, roi, self._ocr), roi

    def _find(self, words, *wanted: str) -> Optional[list[float]]:
        want = {w.lower() for w in wanted}
        return next((b for w, b in words if re.sub(r"[^a-z]", "", w.lower()) in want), None)

    def _claim_all(self, where: str) -> int:
        """Alle sichtbaren „Claim“-Knöpfe drücken (nach jedem Klick neu lesen – die Liste kann sich verschieben)."""
        count = 0
        for _ in range(CLAIM_LIMIT):
            words, _roi = self._words()
            box = self._find(words, "claim")
            if box is None:
                break
            self.log(tr("Klicke „{button}“.", button="Claim"))
            self._click_roi(box)
            count += 1
            time.sleep(1.0)
        self.log(tr("{where}: {count}× abgeholt.", where=where, count=count))
        return count

    def _close_any_quiet(self) -> None:
        try:
            self._close_any()
        except Stop:
            pass

    def _snap(self, tag: str) -> None:
        """Bild für die Fehlersuche (debug/makro_<tag>_<zeit>.jpg) – bei unbekannten Schritten."""
        try:
            from .app_paths import debug_dir
            frame = self._frame()
            small = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            path = debug_dir() / f"makro_{tag}_{time.strftime('%H%M%S')}.jpg"
            cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(str(path))
        except Exception:  # noqa: BLE001 – nur Hilfe für die Fehlersuche
            pass

    # ------------------------------------------------------------------ Gilde: Missionen
    def _guild_claim(self) -> None:
        """Gilde öffnen (Knopf unten links) → „Missions“ → „Personal“ und „Guild Weekly“ abholen → schließen."""
        button = next((e for e in self.map.hud() if e["name"] == "Guild"), None)
        if button is None:
            raise Stop(tr("Der Gilden-Knopf steht nicht in der Karte."))
        self._close_any()
        self.log(tr("Klicke „{button}“.", button="Guild"))
        self._click_roi(button["roi"])
        end = time.monotonic() + OPEN_TIMEOUT
        while self._screen(self._frame())[0] == "none":
            if time.monotonic() > end:
                raise Stop(tr("Gilde ging nicht auf."))
            time.sleep(STEP_WAIT)
        time.sleep(0.6)
        guild = {"name": "Guild"}
        self._press(guild, ("missions",))
        time.sleep(1.0)
        total = 0
        for tab, label in ((("personal",), "Personal"), (("guild", "weekly"), "Guild Weekly")):
            try:
                self._press(guild, tab)
            except Stop:
                self.log(tr("Reiter „{tab}“ nicht gefunden.", tab=label))
                continue
            time.sleep(1.0)
            total += self._claim_all(label)
        if not total:
            self._snap("gilde")
        self._close_any()

    # ------------------------------------------------------------------ Fixer Gigs (W21)
    def _gigs(self) -> None:
        """Fixer Gigs öffnen, fertige Gigs abholen („Claim“), neue mit „Send Pets“ losschicken (die letzten Pets im
        Pets-Fenster), Laufzeiten merken – vor Ablauf wird die Aufgabe übersprungen."""
        wait = self.gigs_next - time.monotonic()
        if wait > 0:
            self.log(tr("Fixer Gigs: nichts fertig – nächste in {minutes} Min.", minutes=int(wait // 60) + 1))
            return
        window = self._window("Fixer Gigs")
        self._open(window)
        time.sleep(0.8)
        self._claim_all("Fixer Gigs")
        for nth in range(1, GIGS_PETS + 1):               # je freiem Platz: „Send Pets“ mit einem Pet
            words, _roi = self._words()
            box = self._send_box(words)
            if box is None:
                break
            self.log(tr("Klicke „{button}“.", button="Send Pets"))
            self._click_roi(box)
            time.sleep(1.2)
            self._send_pets(nth)
            if not self._is_open(window, self._frame()):
                self._open(window)
                time.sleep(0.8)
        words, _roi = self._words()
        times = [s for w, _b in words for s in [parse_timer(re.sub(r"[^0-9:]", "", w))] if s]
        if times:
            self.gigs_next = time.monotonic() + min(times) + 30
            self.log(tr("Fixer Gigs: nächste fertig in {minutes} Min.", minutes=int(min(times) // 60) + 1))
        else:
            self.gigs_next = time.monotonic() + 20 * 60      # Zeiten nicht lesbar: kürzester Gig dauert 20 Min.
        self._close_any()

    @staticmethod
    def _send_box(words) -> Optional[list[float]]:
        """„SEND PETS“ (zwei Wörter nebeneinander) bzw. „SEND“ allein."""
        norm = [(re.sub(r"[^a-z]", "", w.lower()), b) for w, b in words]
        return next((b for w, b in norm if w in ("send", "sendpets")), None)

    def _send_pets(self, nth: int = 1) -> None:
        """Pets-Fenster nach „Send Pets“: ganz nach unten scrollen, EIN Pet anklicken – beim n-ten Gig das n-te von
        hinten (also reihum eins der letzten GIGS_PETS, egal welches) –, bestätigen.
        Unbekannte Schritte werden protokolliert und als Bild gespeichert (debug/makro_gigs_*.jpg)."""
        roi, frame = self._window_area({"name": "Pets"})
        x0, y0, x1, y1 = roi
        grid = [x0 + 0.06 * (x1 - x0), y0 + 0.30 * (y1 - y0), x0 + 0.94 * (x1 - x0), y0 + 0.86 * (y1 - y0)]
        center = ((grid[0] + grid[2]) / 2, (grid[1] + grid[3]) / 2)
        last = None
        for _ in range(25):                               # bis die Liste unten steht
            self._wheel(center, -SCROLL_NOTCHES)
            time.sleep(0.35)
            frame = self._frame()
            fh, fw = frame.shape[:2]
            small = cv2.resize(frame[int(grid[1] * fh):int(grid[3] * fh), int(grid[0] * fw):int(grid[2] * fw)],
                               (96, 48), interpolation=cv2.INTER_AREA)
            if last is not None and float(cv2.absdiff(small, last).mean()) < 2.0:
                break
            last = small
        tiles = self._pet_tiles(frame, grid)
        if not tiles:
            self.log(tr("Keine Pets im Fenster erkannt."))
            self._snap("gigs_pets")
            self._close_any_quiet()
            return
        box = tiles[-min(nth, len(tiles))]
        self._click_roi(box)
        time.sleep(0.4)
        self.log(tr("Pet Nr. {n} von hinten ausgewählt.", n=min(nth, len(tiles))))
        words, _roi = self._words()
        confirm = self._find(words, "send", "confirm", "done", "select", "ok", "start")
        if confirm is None:
            self.log(tr("Bestätigen-Knopf nicht gefunden – Bild gespeichert (debug)."))
            self._snap("gigs_bestaetigen")
            return
        self._click_roi(confirm)
        time.sleep(1.0)

    def _pet_tiles(self, frame: np.ndarray, grid: list[float]) -> list[list[float]]:
        """Pet-Kacheln im Raster (Lese-Reihenfolge). Das Raster ergibt sich aus den Namensschildern unten in den
        Kacheln („Maine“, „Rias“ …): Zeilen = gleiche Höhe, Spalten = gleicher Abstand. Eine Kachel zählt, wenn ein
        Name darin steht oder ihr Inhalt scharf ist (leere Felder sind glatt)."""
        return pet_tiles(frame, grid, vision.words_in(frame, grid, self._ocr))

    def _idle_wait(self, seconds: float) -> None:
        """Warten ohne Eingaben: Maus/Fenster frei, Anti-AFK darf in der Zeit laufen; Esc/„Stopp“ brechen ab."""
        _ACTIVE.clear()
        try:
            end = time.monotonic() + max(0.0, seconds)
            next_check = time.monotonic() + 5
            while time.monotonic() < end:
                if time.monotonic() >= next_check:
                    next_check = time.monotonic() + 5
                    self._extras_while_waiting()
                if self._halt.wait(0.25):
                    raise UserStop(tr("Gestoppt."))
                if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                    raise UserStop(tr("Abgebrochen (Esc)."))
        finally:
            _ACTIVE.set()

    def _focus(self) -> None:
        from .antiafk import _bring_to_front
        u32 = ctypes.windll.user32
        u32.GetForegroundWindow.restype = wintypes.HWND
        if u32.GetForegroundWindow() != self._hwnd:
            if not _bring_to_front(self._hwnd):
                raise Stop(tr("Roblox ließ sich nicht nach vorne holen."))
            time.sleep(0.25)
        self._cursor = None                               # Maus darf sich zwischen den Aufgaben bewegt haben

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
            raise UserStop(tr("Gestoppt."))
        u32 = ctypes.windll.user32
        if u32.GetAsyncKeyState(0x1B) & 0x8000:           # Esc
            raise UserStop(tr("Abgebrochen (Esc)."))
        if self._cursor is not None:
            pt = wintypes.POINT()
            u32.GetCursorPos(ctypes.byref(pt))
            if abs(pt.x - self._cursor[0]) > USER_MOVE_PX or abs(pt.y - self._cursor[1]) > USER_MOVE_PX:
                raise UserStop(tr("Abgebrochen – Maus wurde bewegt."))
        u32.GetForegroundWindow.restype = wintypes.HWND
        if u32.GetForegroundWindow() != self._hwnd:
            raise UserStop(tr("Abgebrochen – Roblox ist nicht mehr im Vordergrund."))

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
