"""Einstellungen (werden als JSON gespeichert) und Standardwerte."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, fields
from typing import Optional

from . import app_paths
from .i18n import N_, tr

log = logging.getLogger("settings")


@dataclass
class Roi:
    """Bildausschnitt relativ zum Fenster (Werte 0..1)."""
    x0: float
    y0: float
    x1: float
    y1: float

    def is_valid(self) -> bool:
        return 0.0 <= self.x0 < self.x1 <= 1.0 and 0.0 <= self.y0 < self.y1 <= 1.0

    def abs_box(self, w: int, h: int) -> tuple[int, int, int, int]:
        """Pixelkoordinaten (x0, y0, x1, y1), sicher innerhalb des Bildes."""
        x0 = max(0, min(int(self.x0 * w), w - 1))
        y0 = max(0, min(int(self.y0 * h), h - 1))
        x1 = max(x0 + 1, min(int(round(self.x1 * w)), w))
        y1 = max(y0 + 1, min(int(round(self.y1 * h)), h))
        return x0, y0, x1, y1

    def as_list(self) -> list[float]:
        return [round(v, 5) for v in (self.x0, self.y0, self.x1, self.y1)]

    @classmethod
    def from_list(cls, values) -> "Roi":
        x0, y0, x1, y1 = (float(v) for v in values)
        return cls(x0, y0, x1, y1)


# Standardbereiche (Wellenzähler oben Mitte, Quest-Liste oben rechts). Der Suchbereich für den Wellenzähler
# ist absichtlich großzügig: das Programm findet „Wave x/100“ darin selbst, auch im Fenstermodus
# (Titelleiste) oder bei leicht verschobenem Layout.
DEFAULT_WAVE_ROI = Roi(0.30, 0.0, 0.70, 0.13)
DEFAULT_QUEST_ROI = Roi(0.905, 0.100, 1.000, 0.300)
# Kulisse zur Raid-Erkennung: nur die Mitte, ohne Menüs/Leisten/Quest-Liste
DEFAULT_SCENE_ROI = Roi(0.14, 0.10, 0.86, 0.68)

# Spielseite für das Thumbnail im Discord-Profilstatus (Place-Nummer aus dem laufenden Roblox-Client, geprüft 06.10.2026)
RPC_GAME_LINK = "https://www.roblox.com/games/102072869879193/CYBER-Anime-Astral-Simulator"

# (Schlüssel, Anzeigename, Standard: senden, Standard: Ping)
EVENT_DEFS: list[tuple[str, str, bool, bool]] = [
    ("raid_done", N_("Raid beendet"), True, False),
    ("raid_aborted", N_("Fehlversuch / Neustart"), False, False),
    ("quest_update", N_("Quest-Fortschritt nach Raid"), True, False),
    ("quest_done", N_("Quest abgeschlossen"), True, False),
    ("roblox_down", N_("Roblox beendet / Disconnect"), True, True),
    ("stall", N_("Stillstand-Alarm"), True, True),
    ("health", N_("Speicher-Warnung"), True, False),
    ("record", N_("Neuer Rekord (Welle)"), True, False),
    ("wall", N_("Wand durchbrochen"), True, False),
    ("report", N_("Bericht / Statistik-Karte"), True, False),
    ("uptime", N_("Uptime (nur ohne Live-Status)"), True, False),
    ("start_stop", N_("Start und Stopp"), True, False),
    ("error", N_("Programmfehler"), True, True),
]

# Prüfintervalle in Sekunden: ruhig, kurz vor Raid-Ende ("heiß"), Quest-Abstand
PRESETS: dict[str, dict] = {
    "eco": {"label": N_("Sparsam"), "idle": 2.0, "hot": 0.5, "quest": 60.0},
    "balanced": {"label": N_("Ausgewogen"), "idle": 1.0, "hot": 0.25, "quest": 30.0},
    "fast": {"label": N_("Schnell"), "idle": 0.5, "hot": 0.15, "quest": 15.0},
}


def default_events() -> dict[str, dict[str, bool]]:
    return {k: {"send": send, "ping": ping} for k, _label, send, ping in EVENT_DEFS}


def is_valid_webhook(url: str) -> bool:
    return url.startswith("https://") and "/api/webhooks/" in url


@dataclass
class Settings:
    # Discord
    webhook_url: str = ""
    username: str = "Anime Astral Monitor"
    ping_user_id: str = ""
    events: dict = field(default_factory=default_events)
    attach_quests: bool = True
    # Aufnahme
    window_title: str = "Roblox"
    capture_mode: str = "auto"          # auto | wgc | screen
    performance: str = "balanced"       # eco | balanced | fast
    low_priority: bool = True
    # Wellenzähler
    wave_roi: Roi = field(default_factory=lambda: Roi(**vars(DEFAULT_WAVE_ROI)))
    allowed_totals: str = "100"
    trigger_offset: int = 1             # 1 = ab 99/100 (also 99 oder 100)
    confirm_reads: int = 2
    cooldown_seconds: int = 60
    # Quests
    read_quests: bool = True
    quest_roi: Roi = field(default_factory=lambda: Roi(**vars(DEFAULT_QUEST_ROI)))
    # Raid-Erkennung (Referenzbilder)
    scene_roi: Roi = field(default_factory=lambda: Roi(**vars(DEFAULT_SCENE_ROI)))
    profile_min_inliers: int = 14
    # Wächter
    guard_enabled: bool = True
    stall_minutes: int = 10
    no_raid_minutes: int = 0            # 0 = aus
    disconnect_check: bool = True
    ram_alert_gb: float = 6.0           # 0 = aus
    # Live-Status (eine Nachricht, die sich selbst aktualisiert)
    status_enabled: bool = True
    status_interval: int = 60           # Sekunden zwischen Aktualisierungen
    status_auto_bottom: bool = False    # nach jeder Meldung des Programms automatisch neu nach unten senden
    report_on_stop: bool = False        # beim Stoppen eine Statistik-Karte an Discord senden
    # Hotkeys
    hotkey_toggle: str = "Ctrl+Alt+S"
    hotkey_pause: str = "Ctrl+Alt+P"
    hotkey_status: str = "Ctrl+Alt+B"
    # Einrichtung
    wizard_done: bool = False
    # Updates und Discord-Profilstatus
    update_check: bool = True
    update_last_check: float = 0.0
    update_skip: str = ""
    rpc_enabled: bool = False
    rpc_client_id: str = ""
    rpc_game_link: str = RPC_GAME_LINK
    # Oberfläche
    language: str = "de"                # de | en (gilt nach Neustart)
    close_to_tray: bool = True          # Fenster schließen = im Infobereich weiterlaufen
    anti_afk_enabled: bool = False      # alle N Minuten kurz zu Roblox, Leertaste, zurück (antiafk.py)
    anti_afk_minutes: int = 10
    private_server_link: str = ""       # roblox.com/games/…?privateServerLinkCode=… (nur lokal, roblox_join.py)
    # Sonstiges
    settings_version: int = 6
    uptime_minutes: int = 10
    total_offset: int = 0               # Startwert für "Raids gesamt"
    tesseract_path: str = ""
    debug_images: bool = False

    # ------------------------------------------------------------------ Helfer
    def allowed_totals_list(self) -> list[int]:
        out = []
        for part in self.allowed_totals.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit() and int(part) >= 2:
                out.append(int(part))
        return out

    def preset(self) -> dict:
        return PRESETS.get(self.performance, PRESETS["balanced"])

    def validate(self) -> Optional[str]:
        if not is_valid_webhook(self.webhook_url):
            return tr("Bitte eine gültige Discord-Webhook-URL eintragen (Seite „Meldungen“).")
        return self.validate_detection()

    def validate_detection(self) -> Optional[str]:
        if not self.wave_roi.is_valid():
            return tr("Der Bereich des Wellenzählers ist ungültig (Seite „Erkennung“).")
        if not self.allowed_totals_list():
            return tr("Bitte mindestens eine erlaubte Gesamtwellenzahl eintragen, z. B. 100.")
        if not 0 <= self.trigger_offset <= 5:
            return tr("Der Auslöser-Abstand muss zwischen 0 und 5 liegen.")
        if not 1 <= self.confirm_reads <= 4:
            return tr("Die Anzahl der Bestätigungen muss zwischen 1 und 4 liegen.")
        if self.cooldown_seconds < 0:
            return tr("Die Sperrzeit darf nicht negativ sein.")
        if not 1 <= self.uptime_minutes <= 1440:
            return tr("Das Uptime-Intervall muss zwischen 1 und 1440 Minuten liegen.")
        if self.read_quests and not self.quest_roi.is_valid():
            return tr("Der Quest-Bereich ist ungültig (Seite „Erkennung“).")
        if not self.scene_roi.is_valid():
            return tr("Der Szenen-Bereich ist ungültig (Seite „Raids“).")
        if not 1 <= self.profile_min_inliers <= 200:
            return tr("Die Mindest-Übereinstimmung muss zwischen 1 und 200 liegen.")
        if not 1 <= self.stall_minutes <= 240:
            return tr("Die Stillstand-Zeit muss zwischen 1 und 240 Minuten liegen.")
        if self.no_raid_minutes < 0 or self.ram_alert_gb < 0:
            return tr("Wächter-Werte dürfen nicht negativ sein.")
        from .hotkeys import parse_hotkey
        keys = ((N_("Start/Stopp"), self.hotkey_toggle), (N_("Pause"), self.hotkey_pause),
                (N_("Status neu senden"), self.hotkey_status))
        for name, text in keys:
            try:
                parse_hotkey(text)
            except ValueError as exc:
                return tr("Hotkey {name}: {error}", name=tr(name), error=exc)
        if len({t.strip().lower() for _n, t in keys}) < len(keys):
            return tr("Die Hotkeys müssen unterschiedlich sein.")
        if self.rpc_client_id.strip() and not self.rpc_client_id.strip().isdigit():
            return tr("Die Discord-Anwendungs-ID besteht nur aus Ziffern (Entwicklerportal → Anwendung → Allgemein).")
        if not 1 <= self.anti_afk_minutes <= 19:
            return tr("Der Anti-AFK-Abstand muss zwischen 1 und 19 Minuten liegen (Roblox trennt nach 20 Minuten).")
        if not 20 <= self.status_interval <= 3600:
            return tr("Das Intervall der Live-Status-Nachricht muss zwischen 20 und 3600 Sekunden liegen.")
        return None

    # ------------------------------------------------------------ Speichern/Laden
    def to_dict(self) -> dict:
        data = {}
        for f in fields(self):
            value = getattr(self, f.name)
            data[f.name] = value.as_list() if isinstance(value, Roi) else value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        s = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            try:
                if f.name in ("wave_roi", "quest_roi", "scene_roi"):
                    value = Roi.from_list(value)
                elif f.name == "events":
                    merged = default_events()
                    for key, entry in (value or {}).items():
                        if key in merged and isinstance(entry, dict):
                            for sub in ("send", "ping"):
                                if sub in entry:
                                    merged[key][sub] = bool(entry[sub])
                    value = merged
                setattr(s, f.name, value)
            except (TypeError, ValueError):
                log.warning("Einstellung %s ungültig, Standard bleibt.", f.name)
        if int(data.get("settings_version", 1) or 1) < 6:
            # Der frühere Standardlink zeigte auf eine falsche Spielnummer; eigene Links bleiben unverändert.
            if "9797806474" in s.rpc_game_link:
                s.rpc_game_link = RPC_GAME_LINK
        if int(data.get("settings_version", 1) or 1) < 5:
            s.settings_version = 5
            s.wizard_done = True              # bestehende Nutzer brauchen den Assistenten nicht
        if int(data.get("settings_version", 1) or 1) < 4:
            old = Roi(0.452, 0.004, 0.552, 0.040)            # alter, enger Standardbereich
            if all(abs(a - b) < 0.002 for a, b in zip(s.wave_roi.as_list(), old.as_list())):
                s.wave_roi = Roi(**vars(DEFAULT_WAVE_ROI))   # eigene Bereiche bleiben unverändert
            s.settings_version = 4
        if int(data.get("settings_version", 1) or 1) < 3:
            # Ab Version 0.3 zählen Fehlversuche in der Statistik; eine Meldung pro Neustart ist standardmäßig aus.
            s.events["raid_aborted"]["send"] = False
            s.settings_version = 3
        s.settings_version = max(s.settings_version, cls.settings_version)    # nach allen Schritten: aktueller Stand
        return s

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(app_paths.settings_file().read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (OSError, ValueError):
            return cls()

    def save(self) -> None:
        path = app_paths.settings_file()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
