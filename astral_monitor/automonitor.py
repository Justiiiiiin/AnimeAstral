"""Auto-Start (optional, Standard aus): Überwachung startet, sobald Anime Astral betreten wird, pausiert bei
Disconnect/Kick/Absturz und stoppt beim Verlassen. Grundlage ist der Spielzustand aus dem Roblox-Protokoll (rejoin.py) –
keine Bilderkennung, keine Eingaben.

Nur Übergänge lösen etwas aus (nicht der Zustand an sich): Wer selbst stoppt, während er im Spiel ist, bleibt gestoppt
bis zum nächsten Betreten; wer selbst startet, ohne im Spiel zu sein, wird nicht gestoppt. Die Entscheidungen fällt
`AutoMonitor.tick` (reine Logik, testbar), ausgeführt werden sie im Hauptfenster."""
from __future__ import annotations

from typing import Optional

from .i18n import tr

GAME_PLACE = 102072869879193      # Anime Astral (eine Place für Lobby und alle Raids, geprüft im Protokoll 06.10.2026)
START_DELAY = 5.0                 # nach dem Betreten kurz warten, bis das Fenster da ist
STOP_GRACE = 20.0                 # Verlassen erst nach dieser Zeit (Serverwechsel/Beitritt über Link treten sofort neu bei)
TROUBLE_STOP = 180.0              # ohne Auto-Rejoin: nach so langer Störung stoppen
RETRY_START = 30.0                # Start fehlgeschlagen (Fenster noch nicht da …): erneut versuchen

IN_GAME, TROUBLE, GONE, ELSEWHERE = "in_game", "trouble", "gone", "elsewhere"


def phase_of(status: str, place: Optional[int]) -> str:
    """Spielzustand aus rejoin.AutoRejoin (status, place)."""
    if status == "in_game":
        return IN_GAME if place == GAME_PLACE else ELSEWHERE
    if status in ("lost", "rejoining", "down", "gave_up"):
        return TROUBLE
    return GONE


class AutoMonitor:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.prev: Optional[str] = None
        self.start_at: Optional[float] = None
        self.stop_at: Optional[float] = None
        self.trouble_since: Optional[float] = None
        self.override = False               # selbst gestoppt, während im Spiel: bis zum nächsten Betreten nichts tun
        self.auto_paused = False            # nur selbst gesetzte Pausen werden automatisch aufgehoben

    # ------------------------------------------------------------------ Eingriffe des Nutzers
    def user_stopped(self) -> None:
        if self.prev in (IN_GAME, TROUBLE):
            self.override = True
        self.start_at = self.stop_at = None
        self.auto_paused = False

    def user_paused(self) -> None:
        self.auto_paused = False            # Pause/Fortsetzen von Hand hat Vorrang

    def start_failed(self, now: float) -> None:
        self.start_at = now + RETRY_START

    # ------------------------------------------------------------------ Entscheidung
    def tick(self, now: float, phase: str, running: bool, paused: bool, rejoin_on: bool,
             gave_up: bool = False) -> list[str]:
        """Rückgabe: Aktionen in Reihenfolge ("start", "pause", "resume", "stop")."""
        acts: list[str] = []
        if phase != self.prev:
            if phase == IN_GAME:
                if self.prev in (None, GONE, ELSEWHERE):
                    self.override = False   # neu betreten: eigene Entscheidung von vorher gilt nicht mehr
                self.start_at = now + START_DELAY
                self.stop_at = self.trouble_since = None
            elif phase == TROUBLE:
                self.trouble_since, self.stop_at = now, None
                if running and not paused:
                    acts.append("pause")
                    self.auto_paused = True
            elif self.prev in (IN_GAME, TROUBLE) and running:
                self.stop_at, self.start_at = now + STOP_GRACE, None
            self.prev = phase

        if phase == IN_GAME:
            if not running and not self.override and self.start_at is not None and now >= self.start_at:
                acts.append("start")
                self.start_at = None
            elif running and paused and self.auto_paused:
                acts.append("resume")
                self.auto_paused = False
        elif phase == TROUBLE and running and self.trouble_since is not None and (
                gave_up or (not rejoin_on and now - self.trouble_since >= TROUBLE_STOP)):
            acts.append("stop")
            self.trouble_since = None
            self.auto_paused = False
        if self.stop_at is not None and now >= self.stop_at:
            if running and phase != IN_GAME:
                acts.append("stop")
                self.auto_paused = False
            self.stop_at = None
        return acts

    def info(self, now: float, phase: str, running: bool) -> str:
        """Kurzer Hinweis für die Kopfzeile ("" = nichts Besonderes)."""
        if phase == IN_GAME and not running and self.override:
            return tr("stopped manually")
        if phase == IN_GAME and not running and self.start_at is not None:
            return tr("starts in {s} s", s=max(0, int(self.start_at - now + 0.99)))
        if phase == TROUBLE and running and self.auto_paused:
            return tr("paused (connection)")
        if self.stop_at is not None and running:
            return tr("stops in {s} s", s=max(0, int(self.stop_at - now + 0.99)))
        if phase in (GONE, ELSEWHERE) and not running:
            return tr("waiting for Anime Astral")
        return ""
