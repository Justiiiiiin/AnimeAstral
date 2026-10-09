"""Settings (stored as JSON) and default values."""
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
    """Image crop relative to the window (values 0..1)."""
    x0: float
    y0: float
    x1: float
    y1: float

    def is_valid(self) -> bool:
        return 0.0 <= self.x0 < self.x1 <= 1.0 and 0.0 <= self.y0 < self.y1 <= 1.0

    def abs_box(self, w: int, h: int) -> tuple[int, int, int, int]:
        """Pixel coordinates (x0, y0, x1, y1), safely inside the image."""
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


# Default areas (wave counter top middle, quest list top right). The search area for the wave counter
# is generous on purpose: the program finds “Wave x/100” in it by itself, also in windowed mode
# (title bar) or with a slightly shifted layout.
DEFAULT_WAVE_ROI = Roi(0.30, 0.0, 0.70, 0.13)
DEFAULT_QUEST_ROI = Roi(0.880, 0.090, 1.000, 0.400)    # a bit larger: also 5–6 quests and long titles


def _load_regions() -> None:
    """Take over areas from regions.json (maintained by the developer tool), if present."""
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

# Recognition is built in since 0.9.0 (no settings anymore): raid end at 100/100 with one reading –
# that ran stable for hours on the developer's PC. The fields stay in the file (downgrade to ≤ 0.8.1).
FIXED_DETECTION = {"window_title": "Roblox", "capture_mode": "auto", "allowed_totals": "auto", "trigger_offset": 0,
                   "confirm_reads": 1, "cooldown_seconds": 60, "read_quests": True, "tesseract_path": "",
                   "debug_images": False}


def fix_detection(s) -> None:
    """Set the recognition values to the fixed values (older files can contain their own)."""
    for name, value in FIXED_DETECTION.items():
        setattr(s, name, value)
    s.wave_roi = Roi(**vars(DEFAULT_WAVE_ROI))
    s.quest_roi = Roi(**vars(DEFAULT_QUEST_ROI))
# Scenery for raid detection: only the middle, without menus/bars/quest list

# Game page for the thumbnail in the Discord profile status (place number from the running Roblox client, checked 06.10.2026)
RPC_GAME_LINK = "https://www.roblox.com/games/102072869879193/CYBER-Anime-Astral-Simulator"

# (key, display name, default: send, default: ping)
EVENT_DEFS: list[tuple[str, str, bool, bool]] = [
    ("raid_done", N_("Raid finished"), True, False),
    ("quest_update", N_("Quest progress after raid"), True, False),
    ("quest_done", N_("Quest completed"), True, False),
    ("roblox_down", N_("Roblox closed / disconnect"), True, True),
    ("rejoin", N_("Auto-rejoin"), True, False),
    ("stall", N_("Stall alert"), True, True),
    ("health", N_("Memory warning"), True, False),
    ("record", N_("New record (wave)"), True, False),
    ("wall", N_("Wall broken"), True, False),
    ("report", N_("Report / stats card"), True, False),
    ("uptime", N_("Uptime (only without live status)"), True, False),
    ("start_stop", N_("Start and stop"), True, False),
    ("error", N_("Program error"), True, True),
]

# Check intervals in seconds: calm, shortly before the raid end ("hot"), quest spacing
# Since 0.9.0 one even tick (no faster tick shortly before the raid end anymore): 100/100 shows for up to ~1 s
PRESETS: dict[str, dict] = {
    "eco": {"label": N_("Economy"), "interval": 0.8, "quest": 60.0},
    "balanced": {"label": N_("Balanced"), "interval": 0.5, "quest": 30.0},
    "fast": {"label": N_("Fast"), "interval": 0.3, "quest": 15.0},
}


def is_hex_color(value) -> bool:
    """Own embed color: “#RRGGBB”."""
    return isinstance(value, str) and len(value) == 7 and value[0] == "#" and all(
        c in "0123456789abcdefABCDEF" for c in value[1:])


def order_raids(names: list, recent: list) -> list:
    """Raid selection: recently used first (newest on top), then the rest alphabetically."""
    known = set(names)
    first = [n for n in recent if n in known]
    return first + sorted((n for n in names if n not in first), key=str.lower)


def default_events() -> dict[str, dict[str, bool]]:
    return {k: {"send": send, "ping": ping} for k, _label, send, ping in EVENT_DEFS}


MAX_FAVORITES = 20
# Values that are stored encrypted in settings.json (secure.py) and blacked out in the diagnostics package
SECRET_FIELDS = ("webhook_url", "forum_webhook_url", "private_server_link", "ping_user_id", "rpc_client_id",
                 "roblox_username", "bot_token", "bot_users")
# With a forum webhook these messages go into one post per day instead of the main channel
DAILY_KINDS = ("raid_done", "quest_update", "quest_done", "record", "wall")


def clean_favorites(value) -> list[dict]:
    """Server favorites from the file: only valid entries {"name", "link"}, unique names, at most 20."""
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
    message_style: str = "detailed"     # Discord: “detailed” (fields, large image) or “compact” (one line)
    forum_webhook_url: str = ""         # optional: forum channel, one post per day for raid messages
    username: str = "Anime Astral Monitor"
    ping_user_id: str = ""
    events: dict = field(default_factory=default_events)
    attach_quests: bool = True
    # Capture
    window_title: str = "Roblox"
    capture_mode: str = "auto"          # fixed (since 0.9.0): window capture, otherwise screen
    performance: str = "balanced"       # eco | balanced | fast
    low_priority: bool = True
    # Wave counter
    wave_roi: Roi = field(default_factory=lambda: Roi(**vars(DEFAULT_WAVE_ROI)))
    allowed_totals: str = "auto"
    trigger_offset: int = 0             # fixed (since 0.9.0): raid end at 100/100
    confirm_reads: int = 1
    cooldown_seconds: int = 60
    # Quests
    read_quests: bool = True
    quest_roi: Roi = field(default_factory=lambda: Roi(**vars(DEFAULT_QUEST_ROI)))
    # Raid: chosen on the start page (no image recognition anymore)
    current_raid: str = ""
    roblox_username: str = ""           # own Roblox profile (name + avatar in sidebar/cards)
    recent_raids: list = field(default_factory=list)   # recently chosen raids, newest first
    # Guard
    guard_enabled: bool = True
    stall_minutes: int = 10
    no_raid_minutes: int = 0            # 0 = off
    ram_alert_gb: float = 6.0           # 0 = off
    # Live status (one message that updates itself)
    status_enabled: bool = True
    status_interval: int = 60           # seconds between updates
    status_auto_bottom: bool = False    # after every message of the program automatically send it again at the bottom
    report_on_stop: bool = False        # send a statistics card to Discord when stopping
    # Hotkeys
    hotkey_toggle: str = "Ctrl+Alt+S"
    hotkey_pause: str = "Ctrl+Alt+P"
    hotkey_status: str = "Ctrl+Alt+B"
    # Setup
    wizard_done: bool = False
    # Updates and Discord profile status
    update_check: bool = True
    update_last_check: float = 0.0
    update_skip: str = ""
    new_seen: list = field(default_factory=list)   # “New” dots already seen
    seen_version: str = ""              # “What's new” last shown for this version
    icons_refreshed: str = ""           # version for which the Windows icon cache was refreshed
    update_beta: bool = False           # offer betas (pre-releases)
    rpc_enabled: bool = False
    rpc_client_id: str = ""
    rpc_game_link: str = RPC_GAME_LINK
    # UI
    language: str = "en"                # en | de (takes effect after a restart; English default since 0.9.9)
    close_to_tray: bool = True          # closing the window = keep running in the tray
    ui_design: str = "nightcity"        # theme.DESIGNS (old designs stay selectable)
    ui_mode: str = "dark"               # dark | light | system
    ui_zoom: int = 75                   # 50–200 % (see more per page = smaller); default 75 % since 0.9.9
    ui_auto_fit: bool = True            # additionally fit to the window size (0.7–1.3)
    ui_reduce_motion: bool = False      # no cross-fades/switch animations (saves performance)
    ui_spooky: bool = True              # pumpkin night: now and then a face peeks up
    ui_seasonal: bool = False           # seasonal designs automatically (pumpkin night, frost)
    ui_intro: bool = True               # logo animation at start-up (skipped with “Reduce animations”)
    ui_background: str = ""             # own background image (file name in the data folder, empty = none)
    ui_background_dim: int = 70         # darken in % (readability)
    ui_accent: str = ""                 # own accent color “#RRGGBB” (empty = the design's color)
    anti_afk_enabled: bool = False      # every N minutes bring each Roblox window to the front briefly, Esc 4×, back (antiafk.py)
    anti_afk_minutes: int = 10
    automation_enabled: bool = False    # macro (beta): open menus via the UI map (automation.py)
    macro_queue: list = field(default_factory=list)    # farm routine: [{"kind": …, …}] (automation.TASK_KINDS)
    macro_loop: bool = False            # routine over and over again
    debug_view: bool = False            # Settings → Debug: collect and show the log live (off = saves load)
    macro_log_home: bool = False        # macro log also on the start page (otherwise only Settings → Macro)
    auto_gigs: bool = False             # macro: claim Fixer Gigs automatically + send new ones (by their times)
    auto_guild: bool = False            # macro: claim guild missions automatically (once a day)
    explore_minutes: int = 20           # Settings → Macro: explore at most this long
    explore_revisit: bool = True        # explore: reopen windows with problems / without a thorough look
    bot_enabled: bool = False           # Discord bot (the user's own bot) for remote control
    bot_token: str = ""                 # bot token (encrypted, SECRET_FIELDS)
    bot_users: str = ""                 # allowed Discord IDs (empty = ping ID from “Alerts”)
    bot_power: bool = False             # allow /pc shutdown/restart (off by default)
    auto_rejoin_enabled: bool = False   # rejoin after a disconnect/kick/crash (rejoin.py)
    auto_monitor: bool = False          # monitoring starts/stops with Anime Astral (automonitor.py)
    server_favorites: list = field(default_factory=list)   # [{"name", "link"}] – local only, diagnostics black out the links
    private_server_link: str = "" # roblox.com/games/…?privateServerLinkCode=… (local only, roblox_join.py)
    # Other
    settings_version: int = 13
    uptime_minutes: int = 10
    total_offset: int = 0               # start value for "raids total"
    tesseract_path: str = ""
    debug_images: bool = False

    # ------------------------------------------------------------------ Helpers
    def allowed_totals_list(self) -> list[int]:
        if self.allowed_totals.strip().lower() == "auto":
            # The game has raids with 30, 50, 100 and up to 2000 waves: all round totals from 20 to 2000.
            # Not “every number” – otherwise a misread like “10” instead of “100” would count as a new raid.
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
            return tr("Please enter a valid Discord webhook URL (page “Alerts”).")
        if self.forum_webhook_url and not is_valid_webhook(self.forum_webhook_url):
            return tr("The forum webhook is not a valid Discord webhook URL (“Alerts” page).")
        return self.validate_detection()

    def validate_detection(self) -> Optional[str]:
        """Checks the adjustable values (the recognition itself is built in since 0.9.0)."""
        if not 1 <= self.uptime_minutes <= 1440:
            return tr("The uptime interval must be between 1 and 1440 minutes.")
        if not 1 <= self.stall_minutes <= 240:
            return tr("The stall time must be between 1 and 240 minutes.")
        if self.no_raid_minutes < 0 or self.ram_alert_gb < 0:
            return tr("Guard values must not be negative.")
        from .hotkeys import parse_hotkey
        keys = ((N_("Start/stop"), self.hotkey_toggle), (N_("Pause"), self.hotkey_pause),
                (N_("Resend status"), self.hotkey_status))
        for name, text in keys:
            try:
                parse_hotkey(text)
            except ValueError as exc:
                return tr("Hotkey {name}: {error}", name=tr(name), error=exc)
        if len({t.strip().lower() for _n, t in keys}) < len(keys):
            return tr("The hotkeys must be different.")
        if self.rpc_client_id.strip() and not self.rpc_client_id.strip().isdigit():
            return tr("The Discord application ID consists of digits only (developer portal → application → "
                      "general).")
        if not 1 <= self.anti_afk_minutes <= 19:
            return tr("The anti-AFK interval must be between 1 and 19 minutes (Roblox disconnects after 20 "
                      "minutes).")
        if not 20 <= self.status_interval <= 3600:
            return tr("The live status interval must be between 20 and 3600 seconds.")
        return None

    # ------------------------------------------------------------ Save/load
    def to_dict(self, protect: bool = False) -> dict:
        """As a dict; with protect=True secrets for settings.json are encrypted locally (secure.py)."""
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
        for name in SECRET_FIELDS:                     # locally encrypted values (older files: plain text)
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
                log.warning("Setting %s invalid, keeping the default.", f.name)
        old_zoom = int(data.get("ui_zoom", 100) or 100)
        if int(data.get("settings_version", 1) or 1) < 10 and old_zoom == 100:
            s.ui_zoom = 75                   # 0.9.9: pages smaller (owner: 75 % instead of 50 %), own values stay
        elif int(data.get("settings_version", 1) or 1) == 10 and old_zoom == 50:
            s.ui_zoom = 75                   # 0.9.9-beta.1 had set 50 % – 75 % is nicer
        if int(data.get("settings_version", 1) or 1) < 8 and s.ui_design == "astral":
            s.ui_design = "nebula"           # “Astral” was just the default up to 0.6.6 – take over the new default design
        if int(data.get("settings_version", 1) or 1) < 12 and s.ui_design == "nebula":
            s.ui_design = "nightcity"        # 0.9.9-beta.7: new default design matching the game (Nebula stays selectable)
        if s.ui_design == "classic":
            s.ui_design = "nightcity"        # 0.9.9-beta.20: design “Classic” removed (owner: outdated, incomplete)
        from .hotkeys import english_hotkey
        s.hotkey_toggle, s.hotkey_pause, s.hotkey_status = (english_hotkey(s.hotkey_toggle),
                                                            english_hotkey(s.hotkey_pause),
                                                            english_hotkey(s.hotkey_status))
        if int(data.get("settings_version", 1) or 1) < 6:
            # The former default link pointed to a wrong game number; own links stay unchanged.
            if "9797806474" in s.rpc_game_link:
                s.rpc_game_link = RPC_GAME_LINK
        if int(data.get("settings_version", 1) or 1) < 5:
            s.settings_version = 5
            s.wizard_done = True              # existing users don't need the wizard
        if int(data.get("settings_version", 1) or 1) < 4:
            old = Roi(0.452, 0.004, 0.552, 0.040)            # old, narrow default area
            if all(abs(a - b) < 0.002 for a, b in zip(s.wave_roi.as_list(), old.as_list())):
                s.wave_roi = Roi(**vars(DEFAULT_WAVE_ROI))   # own areas stay unchanged
            s.settings_version = 4
        if int(data.get("settings_version", 1) or 1) < 3:
            # (formerly: message “failed attempt” off – since 0.7.1 there are no failed attempts anymore)
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
            s.ui_background = ""                    # only the own copy in the data folder
        try:
            s.ui_background_dim = min(95, max(0, int(s.ui_background_dim)))
        except (TypeError, ValueError):
            s.ui_background_dim = 70
        if s.ui_mode not in ("dark", "light", "system"):
            s.ui_mode = "dark"
        if not s.server_favorites and s.private_server_link:
            s.server_favorites = [{"name": "Server 1", "link": s.private_server_link}]   # link from 0.6.2/0.6.3
        s.settings_version = max(s.settings_version, cls.settings_version)    # after all steps: current state
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
        """Safe mode: default values only in memory – the saved settings stay untouched."""
        s = cls()
        s.wizard_done = True                        # no wizard
        s.update_check = False
        s.safe_mode = True
        return s

    def save(self) -> None:
        if getattr(self, "safe_mode", False):       # safe mode: overwrite nothing
            return
        path = app_paths.settings_file()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(protect=True), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
