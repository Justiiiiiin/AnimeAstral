"""Seite „Überwachung": Steuerung, Kennzahlen, Live-Erkennung, Quests, Ereignisse."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from .. import messages
from ..i18n import dec, tr
from . import theme
from .widgets import Card, ComboBox, QuestRow, StatCard, bgr_to_pixmap, label, smooth

LEVEL_TOKENS = {"ok": "accent", "warn": "warn", "error": "danger", "info": "info"}


def wave_token(wave: int, best: int) -> str:
    """Farbe der Wellenzahl je nach Nähe zur Bestwelle: neuer Rekord (gold), knapp davor (türkis), gut (violett)."""
    if best <= 0:
        return ""
    if wave >= best:
        return "warn"
    if wave >= best * 0.9:
        return "accent"
    if wave >= best * 0.6:
        return "info"
    return ""


class MonitorPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.engine = main.engine
        self._last_preview_id = None
        self._quest_rows: list[QuestRow] = []
        self._last_snap = 0.0
        self._was_running = None

        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 16)

        # Kopfzeile
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label(tr("Überwachung"), "h1"))
        self.subtitle = label("", "muted")
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        raid_box = QVBoxLayout()
        theme.track_spacing(raid_box, 2)
        raid_box.addWidget(label(tr("Aktueller Raid"), "small"))
        self.raid_combo = ComboBox()
        theme.track_min_width(self.raid_combo, 220)
        self.raid_combo.setToolTip(tr("Welcher Raid gerade läuft – gilt sofort, auch für den laufenden Versuch. "
                                      "Raids anlegen und umbenennen unter „Raids“."))
        self.raid_combo.activated.connect(self._raid_chosen)
        raid_box.addWidget(self.raid_combo)
        head.addLayout(raid_box)
        head.addSpacing(theme.px(8))
        self.btn_status = QPushButton(tr("Status neu senden"))
        self.btn_status.setToolTip(tr("Löscht die Statusnachricht in Discord und sendet sie ganz unten im Chat neu."))
        self.btn_status.clicked.connect(self.main.resend_status)
        head.addWidget(self.btn_status)
        self.btn_pause = QPushButton(tr("Pause"))
        self.btn_pause.clicked.connect(self.main.toggle_pause)
        self.btn_start = QPushButton(tr("Starten"))
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self.main.toggle_monitoring)
        head.addWidget(self.btn_pause)
        head.addWidget(self.btn_start)
        root.addLayout(head)

        # Kennzahlen
        kpis = QHBoxLayout()
        theme.track_spacing(kpis, 12)
        self.k_total = StatCard(tr("Versuche gesamt"))
        self.k_session = StatCard(tr("Versuche (Session)"))
        self.k_waves = StatCard(tr("Wellen (Session)"))
        self.k_avg = StatCard(tr("Ø Endwelle"))
        self.k_rate = StatCard(tr("Wellen pro Stunde"))
        for card in (self.k_total, self.k_session, self.k_waves, self.k_avg, self.k_rate):
            kpis.addWidget(card, 1)
        root.addLayout(kpis)

        # Mitte
        mid = QHBoxLayout()
        theme.track_spacing(mid, 16)
        left = QVBoxLayout()
        theme.track_spacing(left, 16)

        live = Card(tr("Live-Erkennung"))
        self.preview = label(tr("Hier erscheint nach dem Start der Wellenzähler aus dem Spiel."), "preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        theme.track_min_height(self.preview, 70)
        live.body.addWidget(self.preview)
        self.wave = label("–", "wave")
        self.wave.setAlignment(Qt.AlignmentFlag.AlignCenter)
        live.body.addWidget(self.wave)
        self.wave_bar = QProgressBar()
        self.wave_bar.setRange(0, 100)
        live.body.addWidget(self.wave_bar)
        info = QHBoxLayout()
        self.i_trigger = label("", "small")
        self.i_read = label("", "small")
        self.i_mode = label("", "small")
        for lbl in (self.i_trigger, self.i_read, self.i_mode):
            info.addWidget(lbl, 1)
        live.body.addLayout(info)
        self.status_line = label("", "muted")
        live.body.addWidget(self.status_line)
        self.i_raid = label("", "small")
        self.i_proc = label("", "small")
        self.i_self = label("", "small")
        live.body.addWidget(self.i_raid)
        live.body.addWidget(self.i_proc)
        live.body.addWidget(self.i_self)
        self._self_proc = None
        self._next_self = 0.0
        self._next_wall, self._wall = 0.0, None
        self._next_best, self._best = 0.0, 0
        self._wave_color = None
        try:
            import psutil
            self._self_proc = psutil.Process()
            self._self_proc.cpu_percent(None)          # Messung beginnen
            self._cpu_count = psutil.cpu_count() or 1
        except Exception:
            self._self_proc = None
        left.addWidget(live)

        quests = Card(tr("Quests"))
        self.quest_box = QVBoxLayout()
        theme.track_spacing(self.quest_box, 6)
        self.quest_empty = label(tr("Noch keine Quests gelesen."), "muted")
        self.quest_box.addWidget(self.quest_empty)
        quests.body.addLayout(self.quest_box)
        left.addWidget(quests)
        left.addStretch(1)
        mid.addLayout(left, 3)

        events = Card(tr("Ereignisse"))
        self.events_empty = label(tr("Noch keine Ereignisse – Start, Raids, Alarme und Rejoins erscheinen hier."),
                                  "empty", wrap=True)
        events.body.addWidget(self.events_empty)
        self.events = QListWidget()
        smooth(self.events)
        events.body.addWidget(self.events, 1)
        mid.addWidget(events, 2)
        root.addLayout(mid, 1)

    def _raid_chosen(self, _index: int) -> None:
        name = self.raid_combo.currentData()
        if name is None:                               # „Raids anlegen …“
            self.reload_raids()
            self.main.nav.button(3).click()
            return
        self.main.select_raid(name)

    def recolor(self) -> None:
        """Nach Design-/Farbwechsel: Ereignisse und Wellenzahl in den neuen Farben."""
        self._wave_color = None
        for i in range(self.events.count()):
            item = self.events.item(i)
            token = LEVEL_TOKENS.get(item.data(Qt.ItemDataRole.UserRole) or "info", "info")
            item.setForeground(QColor(theme.color(token)))

    def reload_raids(self) -> None:
        """Auswahlliste neu füllen (nach Anlegen/Umbenennen/Löschen) und den gewählten Raid markieren."""
        current = self.engine.settings.current_raid
        self.raid_combo.blockSignals(True)
        self.raid_combo.clear()
        self.raid_combo.addItem(tr("– kein Raid gewählt –"), "")
        for name in self.engine.profile_store.names():
            self.raid_combo.addItem(name, name)
        if self.raid_combo.count() == 1:
            self.raid_combo.addItem(tr("Raids anlegen …"), None)
        index = self.raid_combo.findData(current)
        self.raid_combo.setCurrentIndex(max(0, index))
        self.raid_combo.blockSignals(False)

    # ---------------------------------------------------------------- Ereignisse
    def add_event(self, data: dict) -> None:
        stamp = time.strftime("%H:%M:%S", time.localtime(data.get("ts", time.time())))
        item = QListWidgetItem(f"{stamp}   {data['text']}")
        item.setData(Qt.ItemDataRole.UserRole, data.get("level", "info"))
        item.setForeground(QColor(theme.color(LEVEL_TOKENS.get(data.get("level", "info"), "info"))))
        self.events.insertItem(0, item)
        self.events_empty.setVisible(False)
        while self.events.count() > 200:
            self.events.takeItem(self.events.count() - 1)

    # ---------------------------------------------------------------- Aktualisieren
    def refresh(self) -> None:
        st = self.engine.state
        s = self.engine.settings
        running = st.running

        if running != self._was_running:
            self._was_running = running
            self.btn_start.setText(tr("Stoppen") if running else tr("Starten"))
            self.btn_start.setObjectName("danger" if running else "primary")
            self.btn_start.style().unpolish(self.btn_start)
            self.btn_start.style().polish(self.btn_start)
            self.btn_pause.setVisible(running)
        self.btn_pause.setText(tr("Fortsetzen") if st.paused else tr("Pause"))
        if running:
            w, h = st.frame_size
            self.subtitle.setText(f"{st.source_info} · {w} × {h}")
        else:
            self.subtitle.setText(tr("Gestoppt – Einstellungen prüfen und starten"))

        now = time.monotonic()
        if now - self._last_snap > 1.5:
            self._last_snap = now
            snap = self.engine.stats.snapshot()
            self.k_total.set_value(messages.fmt_k(snap.total_attempts))
            self.k_session.set_value(str(snap.session_attempts))
            self.k_waves.set_value(messages.fmt_k(snap.session_waves))
            self.k_avg.set_value(dec(f"{snap.avg_wave:.1f}") if snap.avg_wave else "–")
            self.k_rate.set_value(f"{snap.waves_per_hour:.0f}" if snap.waves_per_hour else "–")

        if st.wave_value is not None and st.wave_total:
            self.wave.setText(f"{st.wave_value}/{st.wave_total}")
            self.wave_bar.setValue(int(st.wave_value * 100 / st.wave_total))
            token = wave_token(st.wave_value, self._best)
        else:
            self.wave.setText("–")
            self.wave_bar.setValue(0)
            token = ""
        color = theme.color(token) if token else ""
        if color != self._wave_color:                   # nur bei Wechsel neu setzen (Stylesheet ist teuer)
            self._wave_color = color
            self.wave.setStyleSheet(f"color: {color};" if color else "")
            self.wave.setToolTip(tr("Bestwelle: {wave}", wave=self._best) if self._best else "")
        total = st.wave_total or max(s.allowed_totals_list() or [100])
        self.i_trigger.setText(tr("Auslöser: ab {wave}/{total}", wave=total - s.trigger_offset, total=total))
        self.i_read.setText(tr("Lesezeit: {ms} ms", ms=f"{st.read_ms:.0f}"))
        self.i_mode.setText(tr("Takt: schnell (kurz vor Ende)") if st.hot else tr("Takt: ruhig"))
        self.status_line.setText(tr(st.info))
        raid_text = tr("Raid: {name}", name=st.profile or "–")
        if st.profile and now >= self._next_wall:
            self._next_wall = now + 5.0
            self._wall = self.engine.stats.wall(st.profile)
        if now >= self._next_best:                      # Bestwelle des gewählten Raids (sonst gesamt), alle 5 s
            self._next_best = now + 5.0
            self._best = self.engine.stats.best_wave(st.profile or None)
        if st.profile and self._wall:
            raid_text += " · " + tr("Wand: Welle {wave} ({streak}× in Folge)", wave=self._wall.wave,
                                    streak=self._wall.streak)
        self.i_raid.setText(raid_text)
        if st.roblox_alive is None:
            self.i_proc.setText(tr("Roblox-Prozess: nicht gefunden"))
        elif st.roblox_alive is False:
            self.i_proc.setText(tr("Roblox-Prozess: beendet"))
        else:
            ram = dec(f"{st.roblox_ram_mb / 1024:.1f} GB RAM") if st.roblox_ram_mb else "–"
            cpu = f"{st.roblox_cpu:.0f} % CPU" if st.roblox_cpu is not None else "–"
            self.i_proc.setText(tr("Roblox-Prozess: läuft · {ram} · {cpu}", ram=ram, cpu=cpu))
        if self._self_proc is not None and now >= self._next_self:
            self._next_self = now + 3.0                 # eigene Auslastung (gleich gemessen wie bei Roblox)
            try:
                ram_mb = self._self_proc.memory_info().rss / 1048576
                cpu = self._self_proc.cpu_percent(None) / self._cpu_count
                self.i_self.setText(tr("Dieses Programm: {ram} MB RAM · {cpu} % CPU", ram=f"{ram_mb:.0f}",
                                       cpu=dec(f"{cpu:.1f}")))
            except Exception:
                self.i_self.setText("")

        if st.preview is not None and id(st.preview) != self._last_preview_id:
            self._last_preview_id = id(st.preview)
            self.preview.setPixmap(bgr_to_pixmap(st.preview, 360))
        self._update_quests(st.quests)

    def _update_quests(self, quests: list) -> None:
        self.quest_empty.setVisible(not quests)
        if len(self._quest_rows) != len(quests):
            for row in self._quest_rows:
                self.quest_box.removeWidget(row)
                row.deleteLater()
            self._quest_rows = [QuestRow() for _ in quests]
            for row in self._quest_rows:
                self.quest_box.addWidget(row)
        for row, quest in zip(self._quest_rows, quests):
            row.set_quest(quest)

    # Einstellungen werden auf dieser Seite nicht bearbeitet
    def load(self, settings) -> None:
        self.reload_raids()

    def apply(self, settings) -> None:
        pass
