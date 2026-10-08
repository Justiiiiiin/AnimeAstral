"""Einstellungen (werden als JSON gespeichert) und Standardwerte."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
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
DEFAULT_QUEST_ROI = Roi(0.880, 0.090, 1.000, 0.400)    # etwas größer: auch 5–6 Quests und lange Titel


def _load_regions() -> None:
    """Bereiche aus regions.json (vom Entwickler-Werkzeug gepflegt) übernehmen, falls vorhanden."""
    global DEFAULT_WAVE_ROI, DEFAULT_QUEST_ROI
    import json
    path = Path(__file__).with_name("regions.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        DEFAULT_WAVE_ROI = Roi.from_list(data["wave"])
        DEFAULT_QUEST_ROI = Roi.from_list(data["quest"])
    except (OSError, ValueError, KeyError, TypeError):
        pass


_load_regions()

# Erkennung ist seit 0.9.0 fest eingebaut (keine Einstellungen mehr): Raid-Ende bei 100/100 mit einer Lesung –
# so lief es beim Entwickler stundenlang stabil. Die Felder bleiben in der Datei (Downgrade auf ≤ 0.8.1).
FIXED_DETECTION = {"window_title": "Roblox", "capture_mode": "auto", "allowed_totals": "auto", "trigger_offset": 0,
                   "confirm_reads": 1, "cooldown_seconds": 60, "read_quests": True, "tesseract_path": "",
                   "debug_images": False}


def fix_detection(s) -> None:
    """Erkennungswerte auf die festen Werte setzen (ältere Dateien können eigene enthalten)."""
    for name, value in FIXED_DETECTION.items():
        setattr(s, name, value)
    s.wave_roi = Roi(**vars(DEFAULT_WAVE_ROI))
    s.quest_roi = Roi(**vars(DEFAULT_QUEST_ROI))
# Kulisse zur Raid-Erkennung: nur die Mitte, ohne Menüs/Leisten/Quest-Liste

# Spielseite für das Thumbnail im Discord-Profilstatus (Place-Nummer aus dem laufenden Roblox-Client, geprüft 06.10.2026)
RPC_GAME_LINK = "https://www.roblox.com/games/102072869879193/CYBER-Anime-Astral-Simulator"

# (Schlüssel, Anzeigename, Standard: senden, Standard: Ping)
EVENT_DEFS: list[tuple[str, str, bool, bool]] = [
    ("raid_done", N_("Raid beendet"), True, False),
    ("quest_update", N_("Quest-Fortschritt nach Raid"), True, False),
    ("quest_done", N_("Quest abgeschlossen"), True, False),
    ("roblox_down", N_("Roblox beendet / Disconnect"), True, True),
    ("rejoin", N_("Auto-Rejoin"), True, False),
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
# Seit 0.9.0 ein gleichmäßiger Takt (kein schnellerer Takt kurz vor Raid-Ende mehr): 100/100 steht bis zu ~1 s da
PRESETS: dict[str, dict] = {
    "eco": {"label": N_("Sparsam"), "interval": 0.8, "quest": 60.0},
    "balanced": {"label": N_("Ausgewogen"), "interval": 0.5, "quest": 30.0},
    "fast": {"label": N_("Schnell"), "interval": 0.3, "quest": 15.0},
}


def is_hex_color(value) -> bool:
    """Eigene Embed-Farbe: „#RRGGBB“."""
    return isinstance(value, str) and len(value) == 7 and value[0] == "#" and all(
        c in "0123456789abcdefABCDEF" for c in value[1:])


def order_raids(names: list, recent: list) -> list:
    """Raid-Auswahl: zuletzt benutzte zuerst (neueste oben), danach die übrigen alphabetisch."""
    known = set(names)
    first = [n for n in recent if n in known]
    return first + sorted((n for n in names if n not in first), key=str.lower)


def default_events() -> dict[str, dict[str, bool]]:
    return {k: {"send": send, "ping": ping} for k, _label, send, ping in EVENT_DEFS}


MAX_FAVORITES = 20
# Werte, die in settings.json verschlüsselt liegen (secure.py) und im Diagnose-Paket geschwärzt werden
SECRET_FIELDS = ("webhook_url", "forum_webhook_url", "private_server_link", "ping_user_id", "rpc_client_id",
                 "roblox_username", "bot_token", "bot_users")
# Diese Meldungen landen – mit Forum-Webhook – in einem Beitrag pro Tag statt im Hauptkanal
DAILY_KINDS = ("raid_done", "quest_update", "quest_done", "record", "wall")


def clean_favorites(value) -> list[dict]:
    """Server-Favoriten aus der Datei: nur gültige Einträge {"name", "link"}, Namen eindeutig, höchstens 20."""
    out, seen = [], set()
    for entry in value if isinstance(value, list) else []:
        if not isinstance(entry, dict):
            continue
        name = " ".join(str(entry.get("name", "")).split())[:40]
        link = str(entry.get("link", "")).strip()
        if name and link and name.lower() not in seen:
            seen.add(name.lower())
            out.append({"name": name, "link": link})
    return out[:MAX_FAVORITES]


def is_valid_webhook(url: str) -> bool:
    return url.startswith("https://") and "/api/webhooks/" in url


@dataclass
class Settings:
    # Discord
    webhook_url: str = ""
    message_style: str = "detailed"     # Discord: „detailed“ (Felder, großes Bild) oder „compact“ (eine Zeile)
    forum_webhook_url: str = ""         # optional: Forum-Kanal, Raid-Meldungen je Tag ein Beitrag
    username: str = "Anime Astral Monitor"
    ping_user_id: str = ""
    events: dict = field(default_factory=default_events)
    attach_quests: bool = True
    # Aufnahme
    window_title: str = "Roblox"
    capture_mode: str = "auto"          # fest (seit 0.9.0): Fenster-Aufnahme, sonst Bildschirm
    performance: str = "balanced"       # eco | balanced | fast
    low_priority: bool = True
    # Wellenzähler
    wave_roi: Roi = field(default_factory=lambda: Roi(**vars(DEFAULT_WAVE_ROI)))
    allowed_totals: str = "auto"
    trigger_offset: int = 0             # fest (seit 0.9.0): Raid-Ende bei 100/100
    confirm_reads: int = 1
    cooldown_seconds: int = 60
    # Quests
    read_quests: bool = True
    quest_roi: Roi = field(default_factory=lambda: Roi(**vars(DEFAULT_QUEST_ROI)))
    # Raid: auf der Startseite ausgewählt (keine Bilderkennung mehr)
    current_raid: str = ""
    roblox_username: str = ""           # eigenes Roblox-Profil (Name + Avatar in Seitenleiste/Karten)
    recent_raids: list = field(default_factory=list)   # zuletzt gewählte Raids, neueste zuerst
    # Wächter
    guard_enabled: bool = True
    stall_minutes: int = 10
    no_raid_minutes: int = 0            # 0 = aus
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
    new_seen: list = field(default_factory=list)   # angesehene „Neu“-Punkte
    seen_version: str = ""              # „Was ist neu“ zuletzt für diese Version gezeigt
    icons_refreshed: str = ""           # Version, für die der Windows-Symbolspeicher erneuert wurde
    update_beta: bool = False           # Betas (Vorabversionen) anbieten
    rpc_enabled: bool = False
    rpc_client_id: str = ""
    rpc_game_link: str = RPC_GAME_LINK
    # Oberfläche
    language: str = "de"                # de | en (gilt nach Neustart)
    close_to_tray: bool = True          # Fenster schließen = im Infobereich weiterlaufen
    ui_design: str = "nebula"           # theme.DESIGNS (alte Designs bleiben wählbar)
    ui_mode: str = "dark"               # dark | light | system
    ui_zoom: int = 75                   # 50–200 % (mehr pro Seite sehen = kleiner); seit 0.9.9 Standard 75 %
    ui_auto_fit: bool = True            # zusätzlich an die Fenstergröße anpassen (0,7–1,3)
    ui_reduce_motion: bool = False      # keine Überblendungen/Schalter-Animationen (spart Leistung)
    ui_spooky: bool = True              # Kürbisnacht: ab und zu lugt ein Gesicht hervor
    ui_seasonal: bool = False           # Saison-Designs automatisch (Kürbisnacht, Frost)
    ui_intro: bool = True               # Logo-Animation beim Start (entfällt bei „Animationen reduzieren“)
    ui_background: str = ""             # eigenes Hintergrundbild (Dateiname im Datenordner, leer = keins)
    ui_background_dim: int = 70         # Abdunkeln in % (Lesbarkeit)
    ui_accent: str = ""                 # eigene Akzentfarbe „#RRGGBB“ (leer = Farbe des Designs)
    anti_afk_enabled: bool = False      # alle N Minuten jedes Roblox-Fenster kurz vor, 4× Esc, zurück (antiafk.py)
    anti_afk_minutes: int = 10
    automation_enabled: bool = False    # Makro (Beta): Menüs per Oberflächen-Karte öffnen (automation.py)
    macro_queue: list = field(default_factory=list)    # Makro-Warteschlange: [{"kind": …, …}] (automation.TASK_KINDS)
    macro_loop: bool = False            # Warteschlange immer wieder von vorn
    debug_view: bool = False            # Einstellungen → Debug: Protokoll live sammeln und zeigen (aus = spart Last)
    auto_gigs: bool = False             # Makro: Fixer Gigs automatisch abholen + neu losschicken (nach ihren Zeiten)
    auto_guild: bool = False            # Makro: Gilden-Missionen automatisch abholen (alle paar Stunden)
    explore_minutes: int = 20           # Einstellungen → Makro: Erkunden höchstens so lange
    explore_revisit: bool = True        # Erkunden: Fenster mit Problemen / ohne Tiefen-Durchsicht erneut öffnen
    bot_enabled: bool = False           # Discord-Bot (eigener Bot des Nutzers) zur Fernsteuerung
    bot_token: str = ""                 # Bot-Token (verschlüsselt, SECRET_FIELDS)
    bot_users: str = ""                 # erlaubte Discord-IDs (leer = Ping-ID aus „Meldungen“)
    bot_power: bool = False             # /pc herunterfahren/neu starten erlauben (Standard aus)
    auto_rejoin_enabled: bool = False   # nach Disconnect/Kick/Absturz neu beitreten (rejoin.py)
    auto_monitor: bool = False          # Überwachung startet/stoppt mit Anime Astral (automonitor.py)
    server_favorites: list = field(default_factory=list)   # [{"name", "link"}] – nur lokal, Diagnose schwärzt die Links
    private_server_link: str = "" # roblox.com/games/…?privateServerLinkCode=… (nur lokal, roblox_join.py)
    # Sonstiges
    settings_version: int = 11
    uptime_minutes: int = 10
    total_offset: int = 0               # Startwert für "Raids gesamt"
    tesseract_path: str = ""
    debug_images: bool = False

    # ------------------------------------------------------------------ Helfer
    def allowed_totals_list(self) -> list[int]:
        if self.allowed_totals.strip().lower() == "auto":
            # Im Spiel gibt es Raids mit 30, 50, 100 und bis zu 2000 Wellen: alle runden Gesamtzahlen von 20 bis 2000.
            # Nicht „jede Zahl“ – sonst würde eine Fehllesung wie „10“ statt „100“ als neuer Raid gelten.
            return sorted(set(range(20, 2001, 10)) | {25, 75})
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
        if self.forum_webhook_url and not is_valid_webhook(self.forum_webhook_url):
            return tr("Der Forum-Webhook ist keine gültige Discord-Webhook-URL (Seite „Meldungen“).")
        return self.validate_detection()

    def validate_detection(self) -> Optional[str]:
        """Prüft die einstellbaren Werte (die Erkennung selbst ist seit 0.9.0 fest eingebaut)."""
        if not 1 <= self.uptime_minutes <= 1440:
            return tr("Das Uptime-Intervall muss zwischen 1 und 1440 Minuten liegen.")
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
    def to_dict(self, protect: bool = False) -> dict:
        """Als Dict; mit protect=True sind Geheimnisse für settings.json lokal verschlüsselt (secure.py)."""
        data = {}
        for f in fields(self):
            value = getattr(self, f.name)
            data[f.name] = value.as_list() if isinstance(value, Roi) else value
        if protect:
            from .secure import protect as enc
            for name in SECRET_FIELDS:
                data[name] = enc(data[name])
            data["server_favorites"] = [{"name": f["name"], "link": enc(f["link"])} for f in data["server_favorites"]]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        from .secure import unprotect
        data = dict(data)
        for name in SECRET_FIELDS:                     # lokal verschlüsselte Werte (ältere Dateien: Klartext)
            if isinstance(data.get(name), str):
                data[name] = unprotect(data[name])
        if isinstance(data.get("server_favorites"), list):
            data["server_favorites"] = [dict(f, link=unprotect(f.get("link", ""))) if isinstance(f, dict) else f
                                        for f in data["server_favorites"]]
        s = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            try:
                if f.name in ("wave_roi", "quest_roi"):
                    value = Roi.from_list(value)
                elif f.name == "events":
                    merged = default_events()
                    for key, entry in (value or {}).items():
                        if key in merged and isinstance(entry, dict):
                            for sub in ("send", "ping"):
                                if sub in entry:
                                    merged[key][sub] = bool(entry[sub])
                            if is_hex_color(entry.get("color")):
                                merged[key]["color"] = entry["color"].upper()
                    value = merged
                setattr(s, f.name, value)
            except (TypeError, ValueError):
                log.warning("Einstellung %s ungültig, Standard bleibt.", f.name)
        old_zoom = int(data.get("ui_zoom", 100) or 100)
        if int(data.get("settings_version", 1) or 1) < 10 and old_zoom == 100:
            s.ui_zoom = 75                   # 0.9.9: Seiten kleiner (Eigentümer: 75 % statt 50 %), eigene Werte bleiben
        elif int(data.get("settings_version", 1) or 1) == 10 and old_zoom == 50:
            s.ui_zoom = 75                   # 0.9.9-beta.1 hatte 50 % gesetzt – 75 % ist angenehmer
        if int(data.get("settings_version", 1) or 1) < 8 and s.ui_design == "astral":
            s.ui_design = "nebula"           # „Astral“ war bis 0.6.6 nur der Standard – neues Standarddesign übernehmen
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
            # (früher: Meldung „Fehlversuch“ aus – seit 0.7.1 gibt es keine Fehlversuche mehr)
            s.settings_version = 3
        s.server_favorites = clean_favorites(s.server_favorites)
        fix_detection(s)
        try:
            s.ui_zoom = min(200, max(50, int(s.ui_zoom)))
        except (TypeError, ValueError):
            s.ui_zoom = 100
        if s.message_style not in ("detailed", "compact"):
            s.message_style = "detailed"
        if not is_hex_color(s.ui_accent):
            s.ui_accent = ""
        if not (isinstance(s.ui_background, str) and s.ui_background.startswith("background.")
                and "/" not in s.ui_background and "\\" not in s.ui_background):
            s.ui_background = ""                    # nur die eigene Kopie im Datenordner
        try:
            s.ui_background_dim = min(95, max(0, int(s.ui_background_dim)))
        except (TypeError, ValueError):
            s.ui_background_dim = 70
        if s.ui_mode not in ("dark", "light", "system"):
            s.ui_mode = "dark"
        if not s.server_favorites and s.private_server_link:
            s.server_favorites = [{"name": "Server 1", "link": s.private_server_link}]   # Link aus 0.6.2/0.6.3
        s.settings_version = max(s.settings_version, cls.settings_version)    # nach allen Schritten: aktueller Stand
        return s

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(app_paths.settings_file().read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (OSError, ValueError):
            return cls()

    @classmethod
    def safe_defaults(cls) -> "Settings":
        """Abgesicherter Start: Standardwerte nur im Speicher – die gespeicherten Einstellungen bleiben unberührt."""
        s = cls()
        s.wizard_done = True                        # kein Assistent
        s.update_check = False
        s.safe_mode = True
        return s

    def save(self) -> None:
        if getattr(self, "safe_mode", False):       # abgesicherter Start: nichts überschreiben
            return
        path = app_paths.settings_file()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(protect=True), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
