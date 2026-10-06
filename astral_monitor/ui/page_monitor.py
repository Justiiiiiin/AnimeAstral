"""Seite „Überwachung": Steuerung, Kennzahlen, Live-Erkennung, Quests, Ereignisse."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from .. import messages
from .widgets import Card, QuestRow, StatCard, bgr_to_pixmap, label, smooth

LEVEL_COLORS = {"ok": "#3DD6B5", "warn": "#F5A524", "error": "#FF9A9A", "info": "#E6EAF0"}


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
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # Kopfzeile
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("Überwachung", "h1"))
        self.subtitle = label("", "muted")
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.btn_status = QPushButton("Status neu senden")
        self.btn_status.setToolTip("Löscht die Statusnachricht in Discord und sendet sie ganz unten im Chat neu.")
        self.btn_status.clicked.connect(self.main.resend_status)
        head.addWidget(self.btn_status)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(self.main.toggle_pause)
        self.btn_start = QPushButton("Starten")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self.main.toggle_monitoring)
        head.addWidget(self.btn_pause)
        head.addWidget(self.btn_start)
        root.addLayout(head)

        # Kennzahlen
        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self.k_total = StatCard("Versuche gesamt")
        self.k_session = StatCard("Versuche (Session)")
        self.k_waves = StatCard("Wellen (Session)")
        self.k_avg = StatCard("Ø Endwelle")
        self.k_rate = StatCard("Wellen pro Stunde")
        for card in (self.k_total, self.k_session, self.k_waves, self.k_avg, self.k_rate):
            kpis.addWidget(card, 1)
        root.addLayout(kpis)

        # Mitte
        mid = QHBoxLayout()
        mid.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)

        live = Card("Live-Erkennung")
        self.preview = label("", "preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(70)
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
        try:
            import psutil
            self._self_proc = psutil.Process()
            self._self_proc.cpu_percent(None)          # Messung beginnen
            self._cpu_count = psutil.cpu_count() or 1
        except Exception:
            self._self_proc = None
        left.addWidget(live)

        quests = Card("Quests")
        self.quest_box = QVBoxLayout()
        self.quest_box.setSpacing(6)
        self.quest_empty = label("Noch keine Quests gelesen.", "muted")
        self.quest_box.addWidget(self.quest_empty)
        quests.body.addLayout(self.quest_box)
        left.addWidget(quests)
        left.addStretch(1)
        mid.addLayout(left, 3)

        events = Card("Ereignisse")
        self.events = QListWidget()
        smooth(self.events)
        events.body.addWidget(self.events, 1)
        mid.addWidget(events, 2)
        root.addLayout(mid, 1)

    # ---------------------------------------------------------------- Ereignisse
    def add_event(self, data: dict) -> None:
        stamp = time.strftime("%H:%M:%S", time.localtime(data.get("ts", time.time())))
        item = QListWidgetItem(f"{stamp}   {data['text']}")
        item.setForeground(QColor(LEVEL_COLORS.get(data.get("level", "info"), "#E6EAF0")))
        self.events.insertItem(0, item)
        while self.events.count() > 200:
            self.events.takeItem(self.events.count() - 1)

    # ---------------------------------------------------------------- Aktualisieren
    def refresh(self) -> None:
        st = self.engine.state
        s = self.engine.settings
        running = st.running

        if running != self._was_running:
            self._was_running = running
            self.btn_start.setText("Stoppen" if running else "Starten")
            self.btn_start.setObjectName("danger" if running else "primary")
            self.btn_start.style().unpolish(self.btn_start)
            self.btn_start.style().polish(self.btn_start)
            self.btn_pause.setVisible(running)
        self.btn_pause.setText("Fortsetzen" if st.paused else "Pause")
        if running:
            w, h = st.frame_size
            self.subtitle.setText(f"{st.source_info} · {w} × {h}")
        else:
            self.subtitle.setText("Gestoppt – Einstellungen prüfen und starten")

        now = time.monotonic()
        if now - self._last_snap > 1.5:
            self._last_snap = now
            snap = self.engine.stats.snapshot()
            self.k_total.set_value(messages.fmt_int(snap.total_attempts))
            self.k_session.set_value(str(snap.session_attempts))
            self.k_waves.set_value(messages.fmt_int(snap.session_waves))
            self.k_avg.set_value(f"{snap.avg_wave:.1f}".replace(".", ",") if snap.avg_wave else "–")
            self.k_rate.set_value(f"{snap.waves_per_hour:.0f}" if snap.waves_per_hour else "–")

        if st.wave_value is not None and st.wave_total:
            self.wave.setText(f"{st.wave_value}/{st.wave_total}")
            self.wave_bar.setValue(int(st.wave_value * 100 / st.wave_total))
        else:
            self.wave.setText("–")
            self.wave_bar.setValue(0)
        total = st.wave_total or max(s.allowed_totals_list() or [100])
        self.i_trigger.setText(f"Auslöser: ab {total - s.trigger_offset}/{total}")
        self.i_read.setText(f"Lesezeit: {st.read_ms:.0f} ms")
        self.i_mode.setText("Takt: schnell (kurz vor Ende)" if st.hot else "Takt: ruhig")
        self.status_line.setText(st.info)
        self.i_raid.setText(f"Raid: {st.profile}" if st.profile else "Raid: –")
        if st.roblox_alive is None:
            self.i_proc.setText("Roblox-Prozess: nicht gefunden")
        elif st.roblox_alive is False:
            self.i_proc.setText("Roblox-Prozess: beendet")
        else:
            ram = f"{st.roblox_ram_mb / 1024:.1f} GB RAM".replace(".", ",") if st.roblox_ram_mb else "–"
            cpu = f"{st.roblox_cpu:.0f} % CPU" if st.roblox_cpu is not None else "–"
            self.i_proc.setText(f"Roblox-Prozess: läuft · {ram} · {cpu}")
        if self._self_proc is not None and now >= self._next_self:
            self._next_self = now + 3.0                 # eigene Auslastung (gleich gemessen wie bei Roblox)
            try:
                ram_mb = self._self_proc.memory_info().rss / 1048576
                cpu = self._self_proc.cpu_percent(None) / self._cpu_count
                self.i_self.setText(f"Dieses Programm: {ram_mb:.0f} MB RAM · "
                                    + f"{cpu:.1f} % CPU".replace(".", ","))
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
        pass

    def apply(self, settings) -> None:
        pass
