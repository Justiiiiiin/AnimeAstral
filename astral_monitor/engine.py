"""Kern: Überwachungsschleife. Unabhängig von der Oberfläche (Kommunikation über Zustand + Event-Queue)."""
from __future__ import annotations

import collections
import logging
import queue
import threading
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import app_paths, messages
from .antiafk import AntiAfk, _macro_busy
from .rejoin import AutoRejoin
from .i18n import N_, dec, tr
from .capture import CaptureError, FrameSource, GrabResult, create_source
from .discord_client import DiscordSender
from .guard import Guard
from .ocr import OcrEngine, OcrError
from .profiles import ProfileStore
from .presence import PresenceUpdater
from .status import StatusPublisher
from .quests import QuestReader
from .settings import DAILY_KINDS, Settings, is_valid_webhook
from .stats import RunRecord, StatsStore
from .raidsense import DropIndex, DropWatcher, RaidSense, read_drop_words, read_raid_window
from .tracker import QuestTracker, WaveTracker
from .wave import WaveReader

log = logging.getLogger("engine")

BURST_SECONDS = 30.0        # so lange nach einem Raid wird auf Quest-Änderungen gewartet
BURST_INTERVAL = 4.0
RAID_PROBE_SECONDS = 3.0     # Raid-Fenster suchen – nur ohne sichtbaren Wellenzähler (Lobby), ~15 ms
DROP_SECONDS = 90.0          # im Raid: Drop-Feld so oft lesen (~0,3–0,7 s) – Raid über eindeutige Drops erkennen


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
    info: str = N_("Stopped")              # Anzeige über tr()
    read_ms: float = 0.0
    profile: str = ""                        # gewählter Raid (Startseite)
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
                 source_factory: Callable[..., FrameSource] = create_source) -> None:
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
        self.anti_afk = AntiAfk(lambda: self.settings, self._event)    # läuft auch ohne Überwachung (Standard aus)
        self.anti_afk.start()
        self.rejoin = AutoRejoin(lambda: self.settings, self._event, self._notify)    # ebenso (Standard aus)
        self.rejoin.start()

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
        self.raid_sense = RaidSense()                     # Raid-Name aus dem Raid-Fenster (raidsense.py)
        self._raid_menu = None
        self._next_raid_probe = 0.0
        self.drop_watch = DropWatcher()
        self._drop_index = None
        self._drop_index_at = float("-inf")
        self._next_drops = 0.0
        self.profile_store.remove_reference_images()     # Bilder der früheren Raid-Erkennung (bis 0.6.3) entfernen
        self.guard = Guard(lambda: self.settings, self.state, self._notify, self._event, self._grab_full)
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
            source = self._source_factory(s.capture_mode, s.window_title, min_interval_ms=self._frame_interval_ms())
        except CaptureError as exc:
            raise EngineError(str(exc)) from exc

        self._source = source
        self.wave_reader = WaveReader(ocr, s.allowed_totals_list())
        self.quest_reader = QuestReader(ocr)
        self.quest_reader.names = tuple(self.profile_store.names())
        self.tracker = WaveTracker(s.trigger_offset, s.cooldown_seconds)
        self.quest_tracker = QuestTracker()
        self._reset_runtime()
        self.stats.begin_session()
        if s.low_priority:
            self._lower_priority()

        self._halt.clear()
        self._pause.clear()
        self.state = EngineState(running=True, started_at=time.monotonic(),
                                 source_info=source.name, info=tr("Starting …"))
        self.guard._state = self.state
        self.guard.reset(time.monotonic())
        self._thread = threading.Thread(target=self._loop, name="monitor", daemon=True)
        self._thread.start()
        log.info("Überwachung gestartet (%s). Wellenbereich %s, erlaubte Gesamtwerte %s, Auslöser ab Gesamt-%d.",
                 source.name, s.wave_roi.as_list(), s.allowed_totals_list(), s.trigger_offset)
        self._event(tr("Monitoring started"), "info")
        self.publisher.request_update()
        self._notify("start_stop", tr("Monitor started"), messages.COLOR_INFO,
                     [(tr("Attempts total"), messages.fmt_k(self.stats.snapshot().total_attempts), True),
                      (tr("Capture"), source.name, True)])

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
        self.state = EngineState(running=False, info=tr("Stopped"))
        self.guard._state = self.state
        log.info("Überwachung gestoppt.")
        self._event(tr("Monitoring stopped"), "info")
        self.publisher.request_update()
        if self.settings.report_on_stop and self.stats.summary(self.stats.session_start).attempts:
            self.send_report(self.stats.session_start, None, tr("Session report"))
        self._notify("start_stop", tr("Monitor stopped"), messages.COLOR_GRAY,
                     [(tr("Running time"), messages.fmt_duration(uptime), True),
                      (tr("Attempts session"), str(snap.session_attempts), True),
                      (tr("Waves session"), messages.fmt_int(snap.session_waves), True),
                      (tr("Attempts total"), messages.fmt_k(snap.total_attempts), True)])

    def toggle_pause(self) -> bool:
        if self._pause.is_set():
            self._pause.clear()
        else:
            self._pause.set()
        return self._pause.is_set()

    def shutdown(self) -> None:
        self.stop()
        self.anti_afk.stop()
        self.rejoin.stop()
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

    def grab_for_ui(self, with_quests: bool = False, full: bool = False) -> Optional[GrabResult]:
        """Einmaliges Bild für Tests/Bereichsauswahl (nutzt die laufende Quelle oder eine kurze eigene).
        crops: [Wellenzähler, (Quests)]"""
        s = self.settings
        rois = [s.wave_roi] + ([s.quest_roi] if with_quests else [])
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
            "session_attempts": snap.session_attempts, "session_waves": snap.session_waves,
            "total_attempts": snap.total_attempts, "waves_per_hour": snap.waves_per_hour, "avg_wave": snap.avg_wave,
            "avg_duration": snap.avg_duration, "per_hour": snap.per_hour,
            "uptime": (time.monotonic() - started) if started and st.running else None,
            "best_wave": self.stats.best_wave(profile or None) or None,
            "wall": self.stats.wall(profile or None),
            "ram_mb": st.roblox_ram_mb if st.running else None,
            "quests": list(st.quests) if st.running else [], "last_event": self._last_event_text,
            "started_unix": (time.time() - (time.monotonic() - started)) if started and st.running else None,
        }

    def resend_status(self) -> None:
        """Statusnachricht löschen und ganz unten im Chat neu senden."""
        self.publisher.request_resend()

    def send_report(self, since: Optional[float], raid: Optional[str], title: str, stats=None) -> bool:
        """Statistik-Karte erzeugen und an Discord senden. Gezeichnet wird im Hintergrund (~0,2 s), damit weder die
        Oberfläche noch die Erkennung wartet. Rückgabe: wird gesendet (Webhook und Ereignis eingeschaltet)."""
        if not self.settings.webhook_url or not self.settings.events.get("report", {"send": True}).get("send"):
            return False

        def work() -> None:
            from .report_card import render_card
            try:
                png = render_card(stats or self.stats, since, raid, title)
            except Exception:
                log.exception("Statistik-Karte konnte nicht gezeichnet werden")
                return
            payload, files = messages.build_message(self.settings, "report", title, messages.COLOR_OK,
                                                    image=("bericht.png", png, "image/png"))
            self.sender.submit(payload, files)

        threading.Thread(target=work, name="card", daemon=True).start()
        return True

    def send_month(self, year: int, month: int, stats=None) -> bool:
        """Monatsrückblick als Bild an Discord (Ereignis „Bericht / Statistik-Karte“)."""
        if not self.settings.webhook_url or not self.settings.events.get("report", {"send": True}).get("send"):
            return False
        from .report_card import month_title, render_month_card
        title = "📅 " + tr("Monthly recap {month}", month=month_title(year, month))

        def work() -> None:
            try:
                png = render_month_card(stats or self.stats, year, month)
            except Exception:
                log.exception("Monatsrückblick konnte nicht gezeichnet werden")
                return
            payload, files = messages.build_message(self.settings, "report", title, messages.COLOR_INFO,
                                                    image=("monat.png", png, "image/png"))
            self.sender.submit(payload, files)

        threading.Thread(target=work, name="card", daemon=True).start()
        return True

    def _estimate(self, info: dict) -> tuple[Optional[float], str]:
        """Dauer eines Laufs; war der Start nicht zu sehen, wird sie aus der typischen Zeit pro Welle geschätzt."""
        if info.get("duration") is not None:
            return info["duration"], ""
        spw = self.stats.seconds_per_wave(self._raid_label(info.get("profile")) or None)
        if spw is None or not info.get("first_wave"):
            return None, ""
        return info.get("observed", 0.0) + max(0, info["first_wave"] - 1) * spw, "geschätzt"

    def archive_stats(self) -> Optional[Path]:
        """Statistik archivieren und bei null beginnen (auch der Startwert der Raid-Nummer)."""
        path = self.stats.archive(app_paths.archive_dir())
        if path is not None:
            self.settings.total_offset = 0
            self.publisher.request_update()
        return path

    def rename_raid(self, old: str, new: str) -> str:
        """Raid umbenennen: Profil-Ordner, Verlauf und aktuelle Auswahl. Rückgabe: neuer Name."""
        name = self.profile_store.rename(old, new)
        self.stats.rename_raid(old, name)
        self.settings.recent_raids = [name if n == old else n for n in self.settings.recent_raids]
        if self.settings.current_raid == old:
            self.set_current_raid(name)
        return name

    # ------------------------------------------------------------------ Intern
    def _reset_runtime(self) -> None:
        self._was_visible: Optional[bool] = None
        self._next_status = 0.0
        self._trace_last = (None, None)
        self._trace_at = 0.0
        self._reading = None
        self._next_quest = 0.0
        self._next_uptime = 0.0
        self._burst_until = 0.0
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
        daily = kind in DAILY_KINDS and is_valid_webhook(self.settings.forum_webhook_url)
        on_done = None
        if self.settings.status_enabled and self.settings.status_auto_bottom and not daily:
            on_done = lambda: self.publisher.request_resend(delay=1.0)     # Status wieder unter die neue Meldung
        self.sender.submit(payload, files, on_done, daily=daily)

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
        self._event(tr("Error: {error}", error=exc), "error")
        self._notify("error", tr("Program error"), messages.COLOR_ERROR,
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
                self.state.paused, self.state.info = True, tr("Paused")
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

    def _frame_interval_ms(self) -> int:
        """Bildabstand der Fenster-Aufnahme: halber „heißer“ Takt, damit kurz vor Raid-Ende kein Bild fehlt."""
        return int(min(250, max(50, self.settings.preset()["interval"] * 1000 / 2)))

    def _interval(self) -> float:
        """Gleichmäßiger Takt (seit 0.9.0 kein schnellerer „heißer“ Takt mehr); ohne sichtbaren Zähler etwas ruhiger."""
        interval = self.settings.preset()["interval"]
        return interval * (1.5 if self.state.wave_value is None and self.tracker.last_value is None else 1.0)

    def _tick(self, now: float) -> None:
        s = self.settings
        guard = self.guard
        request = [("wave", s.wave_roi)]
        if s.read_quests and s.quest_roi.is_valid() and now >= self._next_quest:
            request.append(("quest", s.quest_roi))

        busy = _macro_busy()                                   # Makro setzt seinen Raid selbst
        in_raid = self.state.wave_value is not None
        probe = not busy and not in_raid and now >= self._next_raid_probe      # Lobby: Raid-Fenster offen?
        drops = not busy and in_raid and now >= self._next_drops               # im Raid: Drop-Feld lesen
        if probe:
            self._next_raid_probe = now + RAID_PROBE_SECONDS
        if drops:
            self._next_drops = now + DROP_SECONDS
        result = self._source.grab([roi for _name, roi in request], probe or drops, 1.0)
        if result is None:
            self._handle_no_frame(now)
        else:
            if self._missing_since is not None:
                log.info("Bilder vom Roblox-Fenster kommen wieder an")
            self._missing_since = None
            guard.on_frame()
            self.state.frame_size = result.size
            crops = {name: crop for (name, _roi), crop in zip(request, result.crops)}
            if probe and result.full is not None:
                self._probe_raid(result.full, now)
            if drops and result.full is not None:
                self._read_drops(result.full, now)
            self._process_wave(crops["wave"], now)
            if "quest" in crops:
                if _macro_busy():                            # Makro öffnet Menüs (ganze Bildschirme verdecken die
                    self._next_quest = now + BURST_INTERVAL  # Quest-Liste): später lesen statt Unsinn zu werten
                else:
                    self._process_quests(crops["quest"], now)

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
        self.state.info = tr("No image – Roblox window not available")
        self.state.wave_value = None
        self.guard.on_missing(now)
        if not self._source.is_alive() and now - self._last_restart > 3:
            self._last_restart = now
            try:
                self._source.stop()
                self._source = self._source_factory(self.settings.capture_mode, self.settings.window_title,
                                                    min_interval_ms=self._frame_interval_ms())
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
            self.state.info = f"Wave {messages.fmt_wave(reading.value, reading.total)}" + (
                " (Cache)" if reading.cached else "")
        else:
            self.state.wave_value = self.state.wave_total = None
            self.state.info = tr("No wave counter on screen")

        self.guard.on_wave(reading.value if reading else None, now)
        self.raid_sense.wave_visible(reading is not None, now)
        if _macro_busy():
            self.tracker.hold()                              # Makro öffnet Menüs: Lesungen nicht werten
            events = []
        else:
            events = self.tracker.update(reading.value if reading else None,
                                         reading.total if reading else None, now)
        run = self.tracker.run
        if run is not None and run.profile is None:
            seen = self.raid_sense.take(now)               # Raid-Fenster kurz vorher offen + teleportiert
            if seen:
                self._adopt_raid(seen)
        if run is None:
            self.state.profile = self.settings.current_raid
        elif run.profile is None and self.settings.current_raid:
            self._set_profile(run, self.settings.current_raid)     # neuer Versuch: gewählter Raid
        self._trace_wave(reading, now)
        for kind, data in events:
            if kind == "candidate":
                self._on_candidate(now)
            elif kind == "run_end":
                self._on_run_end(data, now)

    def _probe_raid(self, frame: np.ndarray, now: float) -> None:
        """Ist ein Raid-Fenster offen? Dann Namen merken (raidsense). Fehler hier dürfen die Überwachung nie stören."""
        try:
            if self._raid_menu is None:
                from . import vision
                from .uimap import UiMap
                umap = UiMap.load()
                lists = umap.list_windows()
                image = umap.image(lists[0]) if lists else None
                if image is None:
                    self._next_raid_probe = float("inf")     # ohne Karte keine Fenster-Erkennung
                    return
                self._raid_menu = vision.MenuFrame(lists[0], image, None)
            name = read_raid_window(frame, self._raid_menu, self.get_ocr())
            if name:
                self.raid_sense.seen_name(name, self.profile_store.names(), now)
        except Exception as exc:  # noqa: BLE001
            log.debug("Raid-Fenster nicht lesbar: %s", exc)

    def _read_drops(self, frame: np.ndarray, now: float) -> None:
        """Drop-Feld lesen; liegt zweimal hintereinander derselbe Raid vorne (nur eindeutige Drops), gilt er."""
        try:
            if self._drop_index is None or now - self._drop_index_at > 600:
                from .uimap import UiMap
                self._drop_index = DropIndex.from_map(UiMap.load())       # lernt das Erkunden dazu
                self._drop_index_at = now
            if not self._drop_index.unique:
                self._next_drops = now + 600                 # noch keine Drop-Listen: selten nachsehen
                return
            box = self.wave_reader.box                       # Größe des Wellenzählers = GUI-Größe des Spiels
            text_h = float(box[3] - box[1]) / 2 if box is not None else None   # Textzeile ohne Rand (PAD_Y)
            votes = self._drop_index.votes(read_drop_words(frame, self.get_ocr(), text_h))
            raid = self.drop_watch.feed(votes)
            if votes:
                log.debug("Drops: %s", votes)
            if raid and raid != self.settings.current_raid:
                log.info("Raid erkannt (Drops): %s", raid)
                self._adopt_raid(raid)
        except Exception as exc:  # noqa: BLE001 – darf die Überwachung nie stören
            log.debug("Drops nicht lesbar: %s", exc)

    def _adopt_raid(self, name: str) -> None:
        """Gelesenen Raid übernehmen – neu anlegen, falls es ihn noch nicht gibt."""
        try:
            if not any(n.lower() == name.lower() for n in self.profile_store.names()):
                name = self.profile_store.create(name)
                log.info("Neuer Raid angelegt: %s", name)
        except ValueError:
            pass
        if self.settings.current_raid != name:
            log.info("Raid erkannt (Raid-Fenster): %s", name)
            self.set_current_raid(name)
            try:
                self.settings.save()
            except OSError:
                pass

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
        log.info("Status: Welle %s · Lauf %s · Lesezeit %.0f ms · Bild %s · Versuche %d",
                 self.state.wave_value, f"höchste {run.max_wave}" if run else "keiner", self.state.read_ms,
                 "ok" if self._missing_since is None else "FEHLT",
                 sum(1 for r in self.stats.records if r.ts_end >= self.stats.session_start))

    # --------------------------------------------------------------- Raid-Auswahl
    def set_current_raid(self, name: str) -> None:
        """Raid aus der Auswahl auf der Startseite (keine Bilderkennung mehr – die Kamera ist frei einstellbar).
        Gilt sofort, auch für den gerade laufenden Versuch."""
        self.settings.current_raid = name
        if name:
            self.settings.recent_raids = ([name] + [n for n in self.settings.recent_raids if n != name])[:20]
        run = self.tracker.run
        if run is not None and not run.completed:
            self._set_profile(run, name)
        self.state.profile = name
        self.publisher.request_update()
        self.presence.poke()

    def _set_profile(self, run, name: str) -> None:
        run.profile = name or None
        self.state.profile = name

    def _on_candidate(self, now: float) -> None:
        """Letzte Welle gesehen (z. B. 100/100, 50/50): Raid zählt (eine Lesung genügt – sie steht bis zu ~1 s da)."""
        self._finish_run(self.tracker.confirm(now), now)

    def _on_run_end(self, info: dict, now: float) -> None:
        """Raid ohne gesehene letzte Welle beendet (früher aufgehört oder verpasst) – zählt genauso."""
        self._finish_run(info, now)

    def _finish_run(self, info: dict, now: float) -> None:
        """Jedes Raid-Ende: eintragen, melden, Rekord/Wand prüfen. Einen „Fehlversuch“ gibt es nicht – in Anime
        Astral kommt man nur unterschiedlich weit, jede Welle gibt Belohnungen."""
        cycle = None if self._last_ok is None else now - self._last_ok
        self._last_ok = now
        raid = self._raid_label(info.get("profile"))
        duration, note = self._estimate(info)
        prev_best, prev_count = self.stats.best_wave(raid or None), self.stats.attempts(raid or None)
        wall = self.stats.wall(raid) if raid else None
        record = RunRecord(time.time(), duration, cycle, info["max_wave"], info["total"], "ok", note, raid)
        self.stats.add(record)
        self.guard.on_raid_end(now)
        snap = self.stats.snapshot()
        dur_text = messages.fmt_duration_est(duration, record.estimated)
        log.info("Raid beendet (#%d, Welle %d/%d, Dauer %s).", snap.total_attempts, info["max_wave"], info["total"],
                 dur_text)
        self._event(tr("Raid finished · #{count} · wave {wave}", count=messages.fmt_int(snap.total_attempts),
                       wave=messages.fmt_wave(info["max_wave"], info["total"])) + (f" · {raid}" if raid else "")
                    + f" · {dur_text}", "ok")
        self._send_raid(snap, record)
        if wall and info["max_wave"] > wall.wave:
            log.info("Wand durchbrochen in %s: Welle %d (Wand %d nach %d Versuchen)",
                     raid, info["max_wave"], wall.wave, wall.streak)
            self._event(tr("Wall broken in {raid}: wave {wave} (previously {streak}× at wave {wall})",
                           raid=raid, wave=info["max_wave"], streak=wall.streak, wall=wall.wave), "ok")
            self._notify("wall", tr("🎉 Wall broken: wave {wave}", wave=info["max_wave"]), messages.COLOR_OK,
                         [(tr("Raid"), raid, True), (tr("Wall"), tr("Wave {wave}", wave=wall.wave), True),
                          (tr("Attempts at it"), str(wall.streak), True)])
        elif raid and prev_count >= 5 and info["max_wave"] > prev_best:
            self._event(tr("New record in {raid}: wave {wave} (previously {before})", raid=raid, wave=info["max_wave"],
                           before=prev_best), "ok")
            self._notify("record", tr("🏆 New record: wave {wave}", wave=info["max_wave"]), messages.COLOR_OK,
                         [(tr("Raid"), raid, True), (tr("Previous"), str(prev_best), True),
                          (tr("Attempts"), str(prev_count + 1), True)])
        self.publisher.request_update()
        self._burst_until = now + BURST_SECONDS
        self._next_quest = now + BURST_INTERVAL

    @staticmethod
    def _raid_label(profile: Optional[str]) -> str:
        return "" if not profile or profile == "Unbekannt" else profile

    def _send_raid(self, snap, record: RunRecord) -> None:
        """Raid-Meldung als Text (seit 0.9.0 ohne Screenshot – im Spiel ohne Aussagekraft)."""
        elapsed = time.time() - self.stats.session_start
        avg = snap.avg_duration
        if record.raid:
            per = next((p for p in self.stats.per_raid() if p["raid"] == record.raid), None)
            avg = per["avg"] if per and per["avg"] else avg
        fields = [
            (tr("Raid"), f"#{messages.fmt_int(snap.total_attempts)}" + (f" · {record.raid}" if record.raid else ""), True),
            (tr("Wave"), messages.fmt_wave(record.max_wave, record.total_waves), True),
            (tr("Duration"), messages.fmt_duration_est(record.duration_s, record.estimated), True),
            (tr("Avg. duration") + (f" ({record.raid})" if record.raid else ""), messages.fmt_duration(avg), True),
            (tr("Attempts per hour"), dec(f"{snap.per_hour:.1f}") if snap.per_hour else "–", True),
            (tr("Session"), tr("{count} raids · {time}", count=snap.session_attempts,
                               time=messages.fmt_duration(elapsed)), True),
        ]
        quests = self.quest_tracker.snapshot()
        if self.settings.attach_quests and quests:
            fields.append((tr("Quests (before this raid)"), messages.quest_text(quests), False))
        self._notify("raid_done", tr("Raid finished · wave {wave}",
                                     wave=messages.fmt_wave(record.max_wave, record.total_waves)),
                     messages.COLOR_OK, fields)

    def _send_uptime(self, now: float) -> None:
        if self.settings.status_enabled and self.settings.webhook_url:
            return                                  # die Live-Statusnachricht ersetzt das Lebenszeichen
        snap = self.stats.snapshot()
        uptime = now - (self.state.started_at or now)
        fields = [(tr("Uptime"), messages.fmt_duration(uptime), True),
                  (tr("Attempts session"), str(snap.session_attempts), True),
                  (tr("Waves session"), messages.fmt_int(snap.session_waves), True),
                  (tr("Attempts total"), messages.fmt_k(snap.total_attempts), True)]
        quests = self.quest_tracker.snapshot()
        if self.settings.attach_quests and quests:
            fields.append((tr("Quests"), messages.quest_text(quests), False))
        self._notify("uptime", tr("🟢 Heartbeat"), messages.COLOR_GRAY, fields)

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
            self._event(tr("Quest: {title} · {old} → {new}/{total}", title=q.title, old=change.old, new=change.new,
                           total=q.total or "?"), "info")
        for quest in completed:
            self._event(tr("Quest completed: {title}", title=quest.title), "ok")
            self._notify("quest_done", tr("✅ Quest completed"), messages.COLOR_OK,
                         [(tr("Quest"), quest.title, False)])
        if changes and in_burst:
            self._burst_until = 0.0
            lines_txt = "\n".join(
                f"• {c.quest.title}: {messages.fmt_int(c.old)} → **{messages.fmt_int(c.new)}**"
                f"/{messages.fmt_k(c.quest.total) if c.quest.total else '?'}" for c in changes)
            self._notify("quest_update", tr("Quest progress"), messages.COLOR_INFO,
                         [(tr("Changes"), lines_txt, False),
                          (tr("All quests"), messages.quest_text(self.state.quests), False)])
