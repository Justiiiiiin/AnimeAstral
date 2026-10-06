"""Kern: Überwachungsschleife. Unabhängig von der Oberfläche (Kommunikation über Zustand + Event-Queue)."""
from __future__ import annotations

import collections
import logging
import queue
import threading
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from typing import Callable, Optional

import numpy as np

from . import app_paths, messages
from .capture import CaptureError, FrameSource, GrabResult, create_source
from .discord_client import DiscordSender
from .guard import DISCONNECT_ROI, Guard
from .imaging import change_fraction, encode_jpeg, to_gray
from .ocr import OcrEngine, OcrError
from .profiles import ProfileStore, RaidMatcher
from .presence import PresenceUpdater
from .status import StatusPublisher
from .quests import QuestReader
from .settings import Settings
from .stats import RunRecord, StatsStore
from .tracker import QuestTracker, WaveTracker
from .wave import WaveReader

log = logging.getLogger("engine")

CHANGE_FRACTION = 0.004     # so viel Bildänderung im Zählerbereich löst eine neue Lesung aus
STALE_SECONDS = 3.0         # spätestens alle X s trotzdem neu lesen
HOT_MARGIN = 5              # „heiß" = so viele Wellen vor dem Auslöser
BURST_SECONDS = 30.0        # so lange nach einem Raid wird auf Quest-Änderungen gewartet
BURST_INTERVAL = 4.0
SCENE_TRIES = 6             # so viele Vergleichsversuche pro Raid, dann „Unbekannt"
SCENE_EVERY = 1.5           # Sekunden zwischen den Versuchen
SCENE_VOTES = 2             # so viele übereinstimmende Treffer legen den Raid fest


class EngineError(RuntimeError):
    pass


@dataclass
class EngineState:
    running: bool = False
    paused: bool = False
    started_at: Optional[float] = None       # time.monotonic()
    source_info: str = "–"
    frame_size: tuple = (0, 0)
    wave_value: Optional[int] = None
    wave_total: Optional[int] = None
    info: str = "Gestoppt"
    read_ms: float = 0.0
    hot: bool = False
    profile: str = ""                        # erkannter Raid
    roblox_alive: Optional[bool] = None
    roblox_ram_mb: Optional[float] = None
    roblox_cpu: Optional[float] = None
    quests: list = None                      # list[dict]
    preview: Optional[np.ndarray] = None     # letzter Zählerausschnitt (BGR)

    def __post_init__(self) -> None:
        if self.quests is None:
            self.quests = []


class _EventLogHandler(logging.Handler):
    """Leitet Log-Zeilen in die Event-Queue der Oberfläche."""

    def __init__(self, target: "queue.Queue") -> None:
        super().__init__(level=logging.INFO)
        self._target = target

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._target.put_nowait(("log", {"level": record.levelname, "text": self.format(record)}))
        except queue.Full:
            pass


def setup_logging(events: "queue.Queue") -> None:
    root = logging.getLogger()
    if getattr(root, "_astral_ready", False):
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")
    file_handler = RotatingFileHandler(app_paths.log_file(), maxBytes=1_000_000,
                                       backupCount=2, encoding="utf-8")
    file_handler.setFormatter(fmt)
    gui_handler = _EventLogHandler(events)
    gui_handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    root.addHandler(file_handler)
    root.addHandler(gui_handler)
    root._astral_ready = True  # type: ignore[attr-defined]


class Engine:
    def __init__(self, settings: Settings,
                 source_factory: Callable[[str, str], FrameSource] = create_source) -> None:
        self.settings = settings
        self._source_factory = source_factory
        self.events: "queue.Queue" = queue.Queue(maxsize=1000)
        setup_logging(self.events)

        self.stats = StatsStore(app_paths.history_file(), settings.total_offset)
        self.state = EngineState()
        self.sender = DiscordSender(lambda: self.settings)
        self.sender.start()
        self.publisher = StatusPublisher(lambda: self.settings, self.status_snapshot)
        self.publisher.start()
        self.presence = PresenceUpdater(lambda: self.settings, self.status_snapshot)
        self.presence.start()
        self._last_event_text = ""

        self._thread: Optional[threading.Thread] = None
        self._halt = threading.Event()
        self._pause = threading.Event()
        self._source: Optional[FrameSource] = None
        self._ocr: Optional[OcrEngine] = None
        self._ocr_path = None
        self.tracker = WaveTracker()
        self.quest_tracker = QuestTracker()
        self.wave_reader: Optional[WaveReader] = None
        self.quest_reader: Optional[QuestReader] = None
        # Verlauf der gelesenen Werte für die Diagnose: (Zeit, Welle, Gesamt, höchste Welle im Lauf, Info)
        self.trace: "collections.deque" = collections.deque(maxlen=4000)
        self.profile_store = ProfileStore(app_paths.profiles_dir())
        self.matcher: Optional[RaidMatcher] = None
        self.guard = Guard(lambda: self.settings, self.state, self._notify, self._event,
                           self._grab_full, self.get_ocr)
        self._reset_runtime()

    # ------------------------------------------------------------------ Steuerung
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.stats.set_offset(settings.total_offset)
        self.tracker.offset = settings.trigger_offset
        self.tracker.cooldown = settings.cooldown_seconds
        if self.wave_reader:
            self.wave_reader.set_allowed(settings.allowed_totals_list())
        if self.matcher:
            self.matcher.min_inliers = settings.profile_min_inliers
        self.presence.poke()

    def start(self) -> None:
        if self.running:
            return
        s = self.settings
        error = s.validate()
        if error:
            raise EngineError(error)
        ocr = self.get_ocr()
        try:
            source = self._source_factory(s.capture_mode, s.window_title)
        except CaptureError as exc:
            raise EngineError(str(exc)) from exc

        self._source = source
        self.wave_reader = WaveReader(ocr, s.allowed_totals_list())
        self.quest_reader = QuestReader(ocr)
        self.tracker = WaveTracker(s.trigger_offset, s.cooldown_seconds)
        self.quest_tracker = QuestTracker()
        self.matcher = RaidMatcher(self.profile_store, s.profile_min_inliers)
        self._reset_runtime()
        self.stats.begin_session()
        if s.low_priority:
            self._lower_priority()

        self._halt.clear()
        self._pause.clear()
        self.state = EngineState(running=True, started_at=time.monotonic(),
                                 source_info=source.name, info="Starte …")
        self.guard._state = self.state
        self.guard.reset(time.monotonic())
        self._thread = threading.Thread(target=self._loop, name="monitor", daemon=True)
        self._thread.start()
        log.info("Überwachung gestartet (%s). Wellenbereich %s, erlaubte Gesamtwerte %s, Auslöser ab Gesamt-%d.",
                 source.name, s.wave_roi.as_list(), s.allowed_totals_list(), s.trigger_offset)
        self._event("Überwachung gestartet", "info")
        self.publisher.request_update()
        self._notify("start_stop", "Monitor gestartet", messages.COLOR_INFO,
                     [("Versuche gesamt", messages.fmt_int(self.stats.snapshot().total_attempts), True),
                      ("Aufnahme", source.name, True)])

    def stop(self) -> None:
        if not self.running:
            return
        self._halt.set()
        self._thread.join(timeout=5)
        uptime = time.monotonic() - (self.state.started_at or time.monotonic())
        snap = self.stats.snapshot()
        if self._source:
            self._source.stop()
            self._source = None
        self.state = EngineState(running=False, info="Gestoppt")
        self.guard._state = self.state
        log.info("Überwachung gestoppt.")
        self._event("Überwachung gestoppt", "info")
        self.publisher.request_update()
        if self.settings.report_on_stop and self.stats.summary(self.stats.session_start).ok \
                + self.stats.summary(self.stats.session_start).failed:
            self.send_report(self.stats.session_start, None, "Session-Bericht")
        self._notify("start_stop", "Monitor beendet", messages.COLOR_GRAY,
                     [("Laufzeit", messages.fmt_duration(uptime), True),
                      ("Versuche Session", str(snap.session_attempts), True),
                      ("Wellen Session", messages.fmt_int(snap.session_waves), True),
                      ("Versuche gesamt", messages.fmt_int(snap.total_attempts), True)])

    def toggle_pause(self) -> bool:
        if self._pause.is_set():
            self._pause.clear()
        else:
            self._pause.set()
        return self._pause.is_set()

    def shutdown(self) -> None:
        self.stop()
        self.presence.stop()
        self.publisher.finish()
        self.publisher.join(timeout=10)
        self.sender.stop()
        self.sender.join(timeout=8)

    # ---------------------------------------------------------------- Hilfen für die GUI
    def get_ocr(self) -> OcrEngine:
        path = self.settings.tesseract_path
        if self._ocr is None or path != self._ocr_path:
            try:
                self._ocr = OcrEngine(path)
            except OcrError as exc:
                raise EngineError(str(exc)) from exc
            self._ocr_path = path
        return self._ocr

    def _grab_full(self) -> Optional[np.ndarray]:
        if self._source is None:
            return None
        res = self._source.grab([], True, 0.8)
        return res.full if res else None

    def grab_for_ui(self, with_quests: bool = False, full: bool = False,
                    with_scene: bool = False) -> Optional[GrabResult]:
        """Einmaliges Bild für Tests/Bereichsauswahl (nutzt die laufende Quelle oder eine kurze eigene).
        crops: [Wellenzähler, (Quests), (Szene)]"""
        s = self.settings
        rois = [s.wave_roi] + ([s.quest_roi] if with_quests else []) + ([s.scene_roi] if with_scene else [])
        if self._source is not None and self.running:
            return self._source.grab(rois, full, timeout=2.0)
        try:
            source = self._source_factory(s.capture_mode, s.window_title)
        except CaptureError as exc:
            raise EngineError(str(exc)) from exc
        try:
            return source.grab(rois, full, timeout=2.0)
        finally:
            source.stop()

    def test_wave(self) -> dict:
        res = self.grab_for_ui()
        if res is None:
            return {"ok": False, "error": "Kein Bild vom Roblox-Fenster erhalten."}
        reader = WaveReader(self.get_ocr(), self.settings.allowed_totals_list())
        t0 = time.perf_counter()
        reading = reader.read(res.crops[0])
        return {"ok": True, "crop": res.crops[0], "reading": reading, "size": res.size,
                "box": reader.box, "ms": (time.perf_counter() - t0) * 1000}

    def test_quests(self) -> dict:
        res = self.grab_for_ui(with_quests=True)
        if res is None:
            return {"ok": False, "error": "Kein Bild vom Roblox-Fenster erhalten."}
        reader = QuestReader(self.get_ocr())
        t0 = time.perf_counter()
        lines = reader.read(res.crops[1])
        return {"ok": True, "crop": res.crops[1], "lines": lines, "size": res.size,
                "ms": (time.perf_counter() - t0) * 1000}

    def status_snapshot(self) -> dict:
        """Zustandsabzug für die Live-Statusnachricht (läuft im Status-Thread, nur lesen)."""
        st, snap = self.state, self.stats.snapshot()
        status = "stopped" if not st.running else ("paused" if st.paused else "running")
        profile = st.profile if st.profile and st.profile != "Unbekannt" else ""
        started = st.started_at
        return {
            "status": status, "wave": st.wave_value if status != "stopped" else None,
            "total_waves": st.wave_total, "profile": profile,
            "session_ok": snap.session_ok, "session_failed": snap.session_failed, "total_ok": snap.total_ok,
            "session_attempts": snap.session_attempts, "session_waves": snap.session_waves,
            "total_attempts": snap.total_attempts, "waves_per_hour": snap.waves_per_hour, "avg_wave": snap.avg_wave,
            "avg_duration": snap.avg_duration, "per_hour": snap.per_hour,
            "uptime": (time.monotonic() - started) if started and st.running else None,
            "best_wave": self.stats.best_wave(profile or None) or None,
            "ram_mb": st.roblox_ram_mb if st.running else None,
            "quests": list(st.quests) if st.running else [], "last_event": self._last_event_text,
            "started_unix": (time.time() - (time.monotonic() - started)) if started and st.running else None,
        }

    def resend_status(self) -> None:
        """Statusnachricht löschen und ganz unten im Chat neu senden."""
        self.publisher.request_resend()

    def send_report(self, since: Optional[float], raid: Optional[str], title: str) -> bool:
        """Statistik-Karte erzeugen und an Discord senden."""
        if not self.settings.webhook_url:
            return False
        from .report_card import render_card
        png = render_card(self.stats, since, raid, title)
        entry = self.settings.events.get("report", {"send": True})
        if not entry.get("send"):
            return False
        payload, files = messages.build_message(self.settings, "report", title, messages.COLOR_OK,
                                                image=("bericht.png", png, "image/png"))
        self.sender.submit(payload, files)
        return True

    def _estimate(self, info: dict) -> tuple[Optional[float], str]:
        """Dauer eines Laufs; war der Start nicht zu sehen, wird sie aus der typischen Zeit pro Welle geschätzt."""
        if info.get("duration") is not None:
            return info["duration"], ""
        spw = self.stats.seconds_per_wave(self._raid_label(info.get("profile")) or None)
        if spw is None or not info.get("first_wave"):
            return None, ""
        return info.get("observed", 0.0) + max(0, info["first_wave"] - 1) * spw, "geschätzt"

    def capture_reference(self, name: str) -> Optional[str]:
        """Speichert die aktuelle Kulisse als Referenzbild für ein Raid-Profil."""
        res = self.grab_for_ui(with_scene=True)
        if res is None:
            return None
        path = self.profile_store.add_image(name, res.crops[1])
        return str(path)

    def reload_profiles(self) -> None:
        if self.matcher is not None:
            self.matcher.reload()

    def test_scene(self) -> dict:
        res = self.grab_for_ui(with_scene=True)
        if res is None:
            return {"ok": False, "error": "Kein Bild vom Roblox-Fenster erhalten."}
        matcher = RaidMatcher(self.profile_store, self.settings.profile_min_inliers)
        if not matcher.has_profiles:
            return {"ok": False, "error": "Noch keine Referenzbilder vorhanden."}
        t0 = time.perf_counter()
        scores = matcher.score(res.crops[1])
        return {"ok": True, "crop": res.crops[1], "scores": scores, "decision": matcher.decide(scores),
                "ms": (time.perf_counter() - t0) * 1000}

    # ------------------------------------------------------------------ Intern
    def _reset_runtime(self) -> None:
        self._was_visible: Optional[bool] = None
        self._next_status = 0.0
        self._trace_last = (None, None)
        self._trace_at = 0.0
        self._rec_run = None
        self._rec_votes: dict[str, int] = {}
        self._rec_tries = 0
        self._next_scene = 0.0
        self._prev_gray: Optional[np.ndarray] = None
        self._last_ocr = 0.0
        self._reading = None
        self._next_quest = 0.0
        self._next_uptime = 0.0
        self._burst_until = 0.0
        self._quests_before: list[dict] = []
        self._last_ok: Optional[float] = None
        self._missing_since: Optional[float] = None
        self._last_restart = 0.0
        self._error_times: dict[str, float] = {}
        self._debug_saved = 0.0

    def _event(self, text: str, level: str = "info") -> None:
        self._last_event_text = text
        try:
            self.events.put_nowait(("event", {"text": text, "level": level, "ts": time.time()}))
        except queue.Full:
            pass

    def _notify(self, kind: str, title: str, color: int, fields=None, description=None, image=None) -> None:
        entry = self.settings.events.get(kind, {"send": True})
        if not entry.get("send"):
            return
        if not self.settings.webhook_url:
            return
        payload, files = messages.build_message(self.settings, kind, title, color,
                                                fields, description, image)
        on_done = None
        if self.settings.status_enabled and self.settings.status_auto_bottom:
            on_done = lambda: self.publisher.request_resend(delay=1.0)     # Status wieder unter die neue Meldung
        self.sender.submit(payload, files, on_done)

    @staticmethod
    def _lower_priority() -> None:
        try:
            import psutil
            proc = psutil.Process()
            if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
                proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:
                proc.nice(5)
        except Exception:
            log.debug("Priorität konnte nicht gesenkt werden", exc_info=True)

    def _report_error(self, key: str, exc: BaseException) -> None:
        now = time.monotonic()
        if now - self._error_times.get(key, -1e9) < 600:
            return
        self._error_times[key] = now
        log.error("Fehler (%s): %s", key, exc, exc_info=exc)
        self._event(f"Fehler: {exc}", "error")
        self._notify("error", "Programmfehler", messages.COLOR_ERROR,
                     description=f"`{type(exc).__name__}`: {str(exc)[:500]}")

    def _debug_save(self, name: str, image: np.ndarray) -> None:
        if not self.settings.debug_images or time.monotonic() - self._debug_saved < 5:
            return
        self._debug_saved = time.monotonic()
        try:
            import cv2
            folder = app_paths.debug_dir()
            cv2.imwrite(str(folder / f"{time.strftime('%H%M%S')}_{name}.png"), image)
            files = sorted(folder.glob("*.png"))
            for old in files[:-40]:
                old.unlink(missing_ok=True)
        except Exception:
            log.debug("Debug-Bild konnte nicht gespeichert werden", exc_info=True)

    # ---------------------------------------------------------------- Hauptschleife
    def _loop(self) -> None:
        now = time.monotonic()
        self._next_quest = now + 2.0
        self._next_uptime = now + self.settings.uptime_minutes * 60
        next_tick = now

        while not self._halt.is_set():
            if self._pause.is_set():
                self.state.paused, self.state.info = True, "Pausiert"
                self._halt.wait(0.3)
                next_tick = time.monotonic()
                continue
            self.state.paused = False
            now = time.monotonic()
            try:
                self._tick(now)
            except OcrError as exc:
                self._report_error("ocr", exc)
            except Exception as exc:
                self._report_error("tick", exc)

            interval = self._interval()
            next_tick += interval
            if next_tick < time.monotonic():
                next_tick = time.monotonic() + interval
            self._halt.wait(max(0.0, next_tick - time.monotonic()))

    def _interval(self) -> float:
        preset = self.settings.preset()
        value = self.tracker.last_value
        if value is None:
            self.state.hot = False
            return preset["idle"] * (1.5 if self.state.wave_value is None else 1.0)
        total = self.tracker.total or max(self.settings.allowed_totals_list() or [100])
        hot = value >= total - self.settings.trigger_offset - HOT_MARGIN
        self.state.hot = hot
        return preset["hot"] if hot else preset["idle"]

    def _tick(self, now: float) -> None:
        s = self.settings
        guard = self.guard
        request = [("wave", s.wave_roi)]
        if s.read_quests and s.quest_roi.is_valid() and now >= self._next_quest:
            request.append(("quest", s.quest_roi))
        if self._want_scene(now):
            request.append(("scene", s.scene_roi))
        if guard.needs_center(now):
            request.append(("center", DISCONNECT_ROI))

        result = self._source.grab([roi for _name, roi in request], False, 1.0)
        if result is None:
            self._handle_no_frame(now)
        else:
            if self._missing_since is not None:
                log.info("Bilder vom Roblox-Fenster kommen wieder an")
            self._missing_since = None
            guard.on_frame()
            self.state.frame_size = result.size
            crops = {name: crop for (name, _roi), crop in zip(request, result.crops)}
            self._process_wave(crops["wave"], now)
            if "quest" in crops:
                self._process_quests(crops["quest"], now)
            if "scene" in crops:
                self._process_scene(crops["scene"], now)
            if "center" in crops:
                guard.check_disconnect(crops["center"], now)

        guard.poll_process(now)
        guard.check_stall(now, self.tracker.run is not None)
        self._log_status(now)
        if now >= self._next_uptime:
            self._next_uptime = now + s.uptime_minutes * 60
            self._send_uptime(now)

    def _handle_no_frame(self, now: float) -> None:
        if self._missing_since is None:
            self._missing_since = now
            log.warning("Keine Bilder vom Roblox-Fenster (Quelle: %s)", self.state.source_info)
        self.state.info = "Kein Bild – Roblox-Fenster nicht verfügbar"
        self.state.wave_value = None
        self.guard.on_missing(now)
        if not self._source.is_alive() and now - self._last_restart > 3:
            self._last_restart = now
            try:
                self._source.stop()
                self._source = self._source_factory(self.settings.capture_mode, self.settings.window_title)
                self.state.source_info = self._source.name
                log.info("Bildquelle neu verbunden.")
            except CaptureError:
                pass

    # ------------------------------------------------------------------- Wellenzähler
    def _process_wave(self, crop: np.ndarray, now: float) -> None:
        self.state.preview = crop
        # Jeden Takt lesen: der Wellenleser merkt sich Ort und bekannte Bilder (billig); so entsteht keine Verzögerung
        t0 = time.perf_counter()
        self._reading = self.wave_reader.read(crop)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._reading is not None and not self._reading.cached:
            self.state.read_ms = elapsed                     # nur echte Texterkennungen als Lesezeit anzeigen
        if self._reading is None and self.tracker.last_value is not None:
            self._debug_save("wave_unlesbar", crop)

        reading = self._reading
        if reading:
            self.state.wave_value, self.state.wave_total = reading.value, reading.total
            self.state.info = f"Wave {reading.value}/{reading.total}" + (" (Cache)" if reading.cached else "")
        else:
            self.state.wave_value = self.state.wave_total = None
            self.state.info = "Kein Wellenzähler im Bild"

        self.guard.on_wave(reading.value if reading else None, now)
        events = self.tracker.update(reading.value if reading else None,
                                     reading.total if reading else None, now)
        if self.tracker.run is None:
            self.state.profile = ""
            self.tracker.offset = self.settings.trigger_offset      # Profil-Auslöser nur während des Laufs
        self._trace_wave(reading, now)
        for kind, data in events:
            if kind == "candidate":
                self._on_candidate(now)
            elif kind == "run_end":
                self._on_run_end(data, now)

    def _trace_wave(self, reading, now: float) -> None:
        """Protokolliert Wechsel „sichtbar/unsichtbar“ und merkt sich den Wertverlauf für die Diagnose."""
        visible = reading is not None
        if visible != self._was_visible:
            self._was_visible = visible
            if visible:
                log.info("Wellenzähler sichtbar: %d/%d", reading.value, reading.total)
            else:
                log.info("Wellenzähler nicht sichtbar (zuletzt %s)", self.tracker.last_value)
        key = (reading.value, reading.total) if reading else (None, None)
        if key != self._trace_last or now - self._trace_at >= 15:
            self._trace_last, self._trace_at = key, now
            run = self.tracker.run
            self.trace.append((time.time(), key[0], key[1], run.max_wave if run else None,
                               self.state.info))

    def _log_status(self, now: float) -> None:
        if now < self._next_status:
            return
        self._next_status = now + 60
        run = self.tracker.run
        log.info("Status: Welle %s · Lauf %s · Lesezeit %.0f ms · Bild %s · Fehlversuche %d · Erfolge %d",
                 self.state.wave_value, f"höchste {run.max_wave}" if run else "keiner", self.state.read_ms,
                 "ok" if self._missing_since is None else "FEHLT",
                 sum(1 for r in self.stats.records if r.result != "ok" and r.ts_end >= self.stats.session_start),
                 sum(1 for r in self.stats.records if r.result == "ok" and r.ts_end >= self.stats.session_start))

    # --------------------------------------------------------------- Raid-Erkennung
    def _want_scene(self, now: float) -> bool:
        run = self.tracker.run
        if self.matcher is None or not self.matcher.has_profiles or run is None or run.completed:
            return False
        if run.profile is not None or now < self._next_scene:
            return False
        return True

    def _process_scene(self, crop: np.ndarray, now: float) -> None:
        run = self.tracker.run
        if run is None:
            return
        if self._rec_run is not run:                      # neuer Raid: Zähler zurücksetzen
            self._rec_run, self._rec_votes, self._rec_tries = run, {}, 0
        self._next_scene = now + SCENE_EVERY
        self._rec_tries += 1
        scores = self.matcher.score(crop)
        name = self.matcher.decide(scores)
        log.debug("Raid-Vergleich %d: %s -> %s", self._rec_tries, scores, name)
        if name:
            self._rec_votes[name] = self._rec_votes.get(name, 0) + 1
            if self._rec_votes[name] >= SCENE_VOTES:
                self._set_profile(run, name)
                return
        if self._rec_tries >= SCENE_TRIES:
            self._set_profile(run, "Unbekannt")
            best = ", ".join(f"{n}: {v}" for n, v in sorted(scores.items(), key=lambda kv: -kv[1])[:3])
            self._event(f"Raid nicht erkannt ({best}). Referenzbild ergänzen?", "warn")
            self._debug_save("raid_unbekannt", crop)

    def _set_profile(self, run, name: str) -> None:
        run.profile = name
        self.state.profile = name
        if name != "Unbekannt":
            self._event(f"Raid erkannt: {name}", "info")
            log.info("Raid erkannt: %s", name)
            offset = self.profile_store.settings(name).get("trigger_offset")
            if isinstance(offset, int) and 0 <= offset <= 5:
                self.tracker.offset = offset              # eigener Auslöser für dieses Profil
                log.info("Auslöser für %s: ab Gesamt-%d", name, offset)
            self.publisher.request_update()

    def _on_candidate(self, now: float) -> None:
        """Auslöser gesehen: mit frischen Bildern bestätigen und Screenshot aufnehmen."""
        s = self.settings
        reads = max(1, s.confirm_reads)
        full: Optional[np.ndarray] = None
        if reads == 1:
            res = self._source.grab([], True, 0.8)
            full = res.full if res else None
        else:
            for i in range(reads - 1):
                res = self._source.grab([s.wave_roi], i == reads - 2, 0.8)
                if res is None:
                    return
                again = self.wave_reader.read(res.crops[0])
                if not again or again.value < again.total - self.tracker.offset:
                    self._debug_save("bestaetigung_fehlgeschlagen", res.crops[0])
                    return
                if res.full is not None:
                    full = res.full

        info = self.tracker.confirm(now)
        cycle = None if self._last_ok is None else now - self._last_ok
        self._last_ok = now
        raid = self._raid_label(info.get("profile"))
        fails = self.stats.fails_since_last_ok()
        duration, note = self._estimate(info)
        record = RunRecord(time.time(), duration, cycle, info["max_wave"], info["total"], "ok", note, raid)
        self.stats.add(record)
        self.guard.on_raid_end(now)
        snap = self.stats.snapshot()
        dur_text = messages.fmt_duration_est(duration, bool(note))
        log.info("Raid beendet (#%d, Dauer %s).", snap.total_ok, dur_text)
        self._event(f"Raid beendet · #{messages.fmt_int(snap.total_ok)}"
                    f"{' · ' + raid if raid else ''} · {dur_text}", "ok")
        self._send_raid(snap, record, full, fails=fails)
        self.publisher.request_update()

        self._burst_until = now + BURST_SECONDS
        self._next_quest = now + BURST_INTERVAL
        self._quests_before = self.quest_tracker.snapshot()

    def _on_run_end(self, info: dict, now: float) -> None:
        if info["result"] == "ok_late":
            cycle = None if self._last_ok is None else now - self._last_ok
            self._last_ok = now
            fails = self.stats.fails_since_last_ok()
            duration, note = self._estimate(info)
            record = RunRecord(time.time(), duration, cycle, info["max_wave"], info["total"], "ok",
                               "; ".join(x for x in (note, "spät erkannt, kein Screenshot") if x),
                               self._raid_label(info.get("profile")))
            self.stats.add(record)
            self.guard.on_raid_end(now)
            snap = self.stats.snapshot()
            self._event(f"Raid beendet (spät erkannt) · #{messages.fmt_int(snap.total_ok)}", "ok")
            self._send_raid(snap, record, None, late=True, fails=fails)
            self.publisher.request_update()
            self._burst_until, self._next_quest = now + BURST_SECONDS, now + BURST_INTERVAL
            self._quests_before = self.quest_tracker.snapshot()
            return
        raid = self._raid_label(info.get("profile"))
        duration, note = self._estimate(info)
        prev_best, prev_count = self.stats.best_wave(raid or None), self.stats.attempts(raid or None)
        record = RunRecord(time.time(), duration, None, info["max_wave"], info["total"],
                           "abgebrochen", note, raid)
        self.stats.add(record)
        dur = messages.fmt_duration_est(duration, bool(note))
        text = (f"Fehlversuch bei Welle {info['max_wave']}/{info['total']} · {dur}"
                + (f" ({raid})" if raid else ""))
        log.info(text)
        self._event(text, "warn")
        fields = [("Höchste Welle", f"{info['max_wave']}/{info['total']}", True), ("Dauer", dur, True)]
        if raid:
            fields.insert(0, ("Raid", raid, True))
        self._notify("raid_aborted", "Fehlversuch / Neustart", messages.COLOR_WARN, fields)
        if raid and prev_count >= 5 and info["max_wave"] > prev_best:
            self._event(f"Neuer Rekord in {raid}: Welle {info['max_wave']} (vorher {prev_best})", "ok")
            self._notify("record", f"🏆 Neuer Rekord: Welle {info['max_wave']}", messages.COLOR_OK,
                         [("Raid", raid, True), ("Bisher", str(prev_best), True),
                          ("Versuche", str(prev_count + 1), True)])
        self.publisher.request_update()

    @staticmethod
    def _raid_label(profile: Optional[str]) -> str:
        return "" if not profile or profile == "Unbekannt" else profile

    def _send_raid(self, snap, record: RunRecord, full: Optional[np.ndarray], late: bool = False,
                   fails: tuple = (0, None)) -> None:
        elapsed = time.time() - self.stats.session_start
        avg = snap.avg_duration
        if record.raid:
            per = next((p for p in self.stats.per_raid() if p["raid"] == record.raid), None)
            avg = per["avg"] if per and per["avg"] else avg
        fields = [
            ("Raid", f"#{messages.fmt_int(snap.total_ok)}" + (f" · {record.raid}" if record.raid else ""), True),
            ("Dauer", messages.fmt_duration_est(record.duration_s, record.estimated), True),
            ("Ø Dauer" + (f" ({record.raid})" if record.raid else ""), messages.fmt_duration(avg), True),
            ("Raids pro Stunde", f"{snap.per_hour:.1f}".replace(".", ",") if snap.per_hour else "–", True),
            ("Session", f"{snap.session_ok} Raids · {messages.fmt_duration(elapsed)}", True),
            ("Zykluszeit", messages.fmt_duration(record.cycle_s), True),
        ]
        if fails[0]:
            fields.insert(3, ("Fehlversuche davor", f"{fails[0]} · Ø {messages.fmt_duration(fails[1])}", True))
        quests = self.quest_tracker.snapshot()
        if self.settings.attach_quests and quests:
            fields.append(("Quests (Stand vor diesem Raid)", messages.quest_text(quests), False))
        image = ("raid.jpg", encode_jpeg(full)) if full is not None else None
        self._notify("raid_done", "Raid erfolgreich beendet!", messages.COLOR_OK, fields,
                     "Ohne Screenshot erkannt." if late else None, image)

    def _send_uptime(self, now: float) -> None:
        if self.settings.status_enabled and self.settings.webhook_url:
            return                                  # die Live-Statusnachricht ersetzt das Lebenszeichen
        snap = self.stats.snapshot()
        uptime = now - (self.state.started_at or now)
        fields = [("Uptime", messages.fmt_duration(uptime), True),
                  ("Versuche Session", str(snap.session_attempts), True),
                  ("Wellen Session", messages.fmt_int(snap.session_waves), True),
                  ("Versuche gesamt", messages.fmt_int(snap.total_attempts), True)]
        quests = self.quest_tracker.snapshot()
        if self.settings.attach_quests and quests:
            fields.append(("Quests", messages.quest_text(quests), False))
        self._notify("uptime", "🟢 Lebenszeichen", messages.COLOR_GRAY, fields)

    # ---------------------------------------------------------------------- Quests
    def _process_quests(self, crop: np.ndarray, now: float) -> None:
        in_burst = now < self._burst_until
        try:
            lines = self.quest_reader.read(crop)
        finally:
            self._next_quest = now + (BURST_INTERVAL if in_burst else self.settings.preset()["quest"])
        if not lines:
            self._debug_save("quests_leer", crop)
            return
        changes, completed = self.quest_tracker.update(lines)
        self.state.quests = self.quest_tracker.snapshot()

        for change in changes:
            q = change.quest
            self._event(f"Quest: {q.title} · {change.old} → {change.new}/{q.total or '?'}", "info")
        for quest in completed:
            self._event(f"Quest abgeschlossen: {quest.title}", "ok")
            self._notify("quest_done", "✅ Quest abgeschlossen", messages.COLOR_OK,
                         [("Quest", quest.title, False)])
        if changes and in_burst:
            self._burst_until = 0.0
            lines_txt = "\n".join(
                f"• {c.quest.title}: {messages.fmt_int(c.old)} → **{messages.fmt_int(c.new)}**"
                f"/{messages.fmt_int(c.quest.total) if c.quest.total else '?'}" for c in changes)
            self._notify("quest_update", "Quest-Fortschritt", messages.COLOR_INFO,
                         [("Änderungen", lines_txt, False),
                          ("Alle Quests", messages.quest_text(self.state.quests), False)])
