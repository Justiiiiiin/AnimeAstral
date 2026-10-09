"""Start page: metrics, left the farm routine (+ macro log if wanted), right live recognition, quests
and “Auto collect”.
Start/stop, pause and “Resend status” sit in the header of the main window (MainWindow._mount_controls);
the events are a debug card in the settings (ui/events_card.py)."""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .. import messages
from ..i18n import dec, tr
from . import theme
from .widgets import Card, ComboBox, EmptyState, QuestRow, StatCard, discord_icon, label, media_icon


def wave_token(wave: int, best: int) -> str:
    """Color of the wave number by closeness to the best wave: new record (gold), just below (teal), good (violet)."""
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
        self._quest_rows: list[QuestRow] = []
        self._last_snap = 0.0
        self._was_running = None

        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 16)

        # controls: in the header of the main window (only created here, refresh() keeps the state)
        self.btn_status = QPushButton()                     # icon only (the header is narrow)
        self.btn_status.setIcon(discord_icon())
        theme.track(self.btn_status, lambda o, f: o.setIconSize(QSize(round(20 * f), round(20 * f))))
        self.btn_status.setToolTip(tr("Resend status: the status message in Discord is deleted and sent again at "
                                      "the bottom."))
        self.btn_status.clicked.connect(self.main.resend_status)
        self.btn_pause = QPushButton()
        self.btn_pause.setToolTip(tr("Pause"))
        self.btn_pause.clicked.connect(self.main.toggle_pause)
        self.btn_start = QPushButton()
        self.btn_start.setToolTip(tr("Start"))
        for btn in (self.btn_start, self.btn_pause, self.btn_status):
            theme.track_fixed_width(btn, 40)                # icons only: ▶/■, ❚❚, Discord
            theme.track(btn, lambda o, f: o.setIconSize(QSize(round(18 * f), round(18 * f))))
        self.btn_start.clicked.connect(self.main.toggle_monitoring)

        # metrics
        kpis = QHBoxLayout()
        theme.track_spacing(kpis, 12)
        self.k_total = StatCard(tr("Attempts total"))
        self.k_session = StatCard(tr("Attempts (session)"))
        self.k_waves = StatCard(tr("Waves (session)"))
        self.k_avg = StatCard(tr("Raids today"))
        self.k_rate = StatCard(tr("Waves per hour"))
        for card in (self.k_total, self.k_session, self.k_waves, self.k_avg, self.k_rate):
            kpis.addWidget(card, 1)
        root.addLayout(kpis)

        # middle (owner's wish 08.10.2026): left the farm routine (+ macro log if wanted under
        # Settings → Macro), right live recognition, quests and at the very bottom “Auto collect” –
        # the quests have room above it without the collect card jumping
        mid = QHBoxLayout()
        theme.track_spacing(mid, 16)
        left = QVBoxLayout()
        theme.track_spacing(left, 16)
        right = QVBoxLayout()
        theme.track_spacing(right, 16)

        from .extras_card import ExtrasCard
        from .macro_log import MacroLogCard
        from .macro_queue_card import MacroQueueCard
        self.queue = MacroQueueCard(main)
        left.addWidget(self.queue, 3)
        self.log_card = MacroLogCard(main.macro)
        left.addWidget(self.log_card, 2)
        self.log_card.setVisible(bool(main.engine.settings.macro_log_home))
        self.extras = ExtrasCard(main)

        live = Card(tr("Live detection"))                 # without a preview image: number, bar, short info
        self.wave = label("–", "wave")
        self.wave.setAlignment(Qt.AlignmentFlag.AlignCenter)
        live.body.addWidget(self.wave)
        self.wave_bar = QProgressBar()
        self.wave_bar.setRange(0, 100)
        live.body.addWidget(self.wave_bar)
        info = QHBoxLayout()
        self.i_read = label("", "small", wrap=True)
        self.i_mode = label("", "small", wrap=True)
        for lbl in (self.i_read, self.i_mode):
            info.addWidget(lbl, 1)
        live.body.addLayout(info)
        self.status_line = label("", "muted", wrap=True)
        live.body.addWidget(self.status_line)
        raid_row = QHBoxLayout()                          # raid to choose yourself (when playing yourself);
        theme.track_spacing(raid_row, 6)                  # macro raids set it themselves
        raid_row.addWidget(label(tr("Raid:"), "small"))
        self.raid_pick = ComboBox()
        self.raid_pick.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.raid_pick.setMinimumContentsLength(8)
        self.raid_pick.setToolTip(tr("Attempts count towards this raid. If the macro starts a raid, it sets it "
                                     "itself – if you play yourself, pick it here."))
        self.raid_pick.activated.connect(lambda _i: self.main.select_raid(self.raid_pick.currentData() or ""))
        raid_row.addWidget(self.raid_pick, 1)
        self.i_raid = label("", "small", wrap=True)       # wall of the chosen raid
        self.i_proc = label("", "small", wrap=True)
        self.i_self = label("", "small", wrap=True)
        live.body.addLayout(raid_row)
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
            self._self_proc.cpu_percent(None)          # start measuring
            self._cpu_count = psutil.cpu_count() or 1
        except Exception:
            self._self_proc = None
        right.addWidget(live)

        quests = Card(tr("Quests"))
        self.quest_box = QVBoxLayout()
        theme.track_spacing(self.quest_box, 6)
        self.quest_empty = EmptyState("quests", tr("No quests read yet."))
        self.quest_box.addWidget(self.quest_empty)
        quests.body.addLayout(self.quest_box)
        right.addWidget(quests)
        right.addStretch(1)
        right.addWidget(self.extras)

        mid.addLayout(left, 3)
        mid.addLayout(right, 2)
        root.addLayout(mid, 1)
        self.reload_raids()

    def set_log_visible(self, on: bool) -> None:
        self.log_card.setVisible(on)

    def recolor(self) -> None:
        """After a design/color change: wave number and start icon in the new colors."""
        self.log_card.view.reload()
        self._wave_color = None
        self._was_running = None
        self._paused = None
        self.btn_status.setIcon(discord_icon())

    def reload_raids(self) -> None:
        """Fill the raid selection (live card) with the raids from Settings → Roblox, show the current raid."""
        current = self.engine.settings.current_raid or None
        names = self.engine.profile_store.names()
        self.raid_pick.blockSignals(True)
        self.raid_pick.clear()
        self.raid_pick.addItem("–", None)
        for name in names:
            self.raid_pick.addItem(name, name)
        if current and current not in names:
            self.raid_pick.addItem(current, current)
        self.raid_pick.setCurrentIndex(max(0, self.raid_pick.findData(current)) if current else 0)
        self.raid_pick.blockSignals(False)

    # ---------------------------------------------------------------- Refresh
    def refresh_controls(self) -> None:
        """Start/stop and pause in the header – runs on every page (MainWindow._tick), not only here."""
        st = self.engine.state
        running = st.running
        if running != self._was_running:
            self._was_running = running
            # normal button frame (the “primary” style doesn't apply in the header), icon drawn + colored
            self.btn_start.setIcon(media_icon("stop", "danger") if running else media_icon("play", "accent"))
            self.btn_start.setToolTip(tr("Stop monitoring") if running else tr("Start"))
            self._paused = None
            self.btn_pause.setVisible(running)
        if st.paused != getattr(self, "_paused", None):
            self._paused = st.paused
            self.btn_pause.setIcon(media_icon("play" if st.paused else "pause", "accent" if st.paused else "text"))
            self.btn_pause.setToolTip(tr("Resume") if st.paused else tr("Pause"))

    def refresh(self) -> None:
        st = self.engine.state
        s = self.engine.settings

        now = time.monotonic()
        if now - self._last_snap > 1.5:
            self._last_snap = now
            snap = self.engine.stats.snapshot()
            self.k_total.set_value(messages.fmt_k(snap.total_attempts))
            self.k_session.set_value(str(snap.session_attempts))
            self.k_waves.set_value(messages.fmt_int(snap.session_waves))
            self.k_avg.set_value(messages.fmt_k(snap.today_attempts))
            self.k_rate.set_value(messages.fmt_int(round(snap.waves_per_hour)) if snap.waves_per_hour else "–")

        if st.wave_value is not None:
            self.wave.setText(messages.fmt_wave(st.wave_value, st.wave_total))
            self.wave_bar.setValue(int(st.wave_value * 100 / st.wave_total) if st.wave_total else 0)
            self.wave_bar.setVisible(bool(st.wave_total))      # without a total there is no progress
            token = wave_token(st.wave_value, self._best)
        else:
            self.wave.setText("–")
            self.wave_bar.setValue(0)
            self.wave_bar.setVisible(True)
            token = ""
        color = theme.color(token) if token else ""
        if color != self._wave_color:                   # only set on change (stylesheets are expensive)
            self._wave_color = color
            self.wave.setStyleSheet(f"color: {color};" if color else "")
            self.wave.setToolTip(tr("Best wave: {wave}", wave=self._best) if self._best else "")
        self.i_read.setText(tr("Read time: {ms} ms", ms=f"{st.read_ms:.0f}"))
        self.i_mode.setText(tr("Checks every {interval} s", interval=dec(f"{s.preset()['interval']:g}")))
        self.status_line.setText(tr(st.info))
        raid_text = ""
        if self.raid_pick.currentData() != (st.profile or None) and not self.raid_pick.view().isVisible():
            self.reload_raids()
        if st.profile and now >= self._next_wall:
            self._next_wall = now + 5.0
            self._wall = self.engine.stats.wall(st.profile)
        if now >= self._next_best:                      # best wave of the chosen raid (otherwise overall), every 5 s
            self._next_best = now + 5.0
            self._best = self.engine.stats.best_wave(st.profile or None)
        if st.profile and self._wall:
            raid_text = tr("Wall: wave {wave} ({streak}× in a row)", wave=self._wall.wave, streak=self._wall.streak)
        self.i_raid.setText(raid_text)
        self.i_raid.setVisible(bool(raid_text))
        if st.roblox_alive is None:
            self.i_proc.setText(tr("Roblox: not running"))
        elif st.roblox_alive is False:
            self.i_proc.setText(tr("Roblox: closed"))
        else:
            ram = dec(f"{st.roblox_ram_mb / 1024:.1f} GB RAM") if st.roblox_ram_mb else "–"
            cpu = f"{st.roblox_cpu:.0f} % CPU" if st.roblox_cpu is not None else "–"
            self.i_proc.setText(tr("Roblox: running · {ram} · {cpu}", ram=ram, cpu=cpu))
        if self._self_proc is not None and now >= self._next_self:
            self._next_self = now + 3.0                 # own load (measured the same way as for Roblox)
            try:
                ram_mb = self._self_proc.memory_info().rss / 1048576
                cpu = self._self_proc.cpu_percent(None) / self._cpu_count
                self.i_self.setText(tr("This program: {ram} MB RAM · {cpu} % CPU", ram=f"{ram_mb:.0f}",
                                       cpu=dec(f"{cpu:.1f}")))
            except Exception:
                self.i_self.setText("")

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

    # settings are not edited on this page
    def load(self, settings) -> None:
        self.reload_raids()

    def apply(self, settings) -> None:
        pass
