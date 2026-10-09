"""Page “Statistics”: all attempts together (every wave gives rewards), per raid or in total."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QGridLayout, QHBoxLayout, QMenu, QMessageBox,
                               QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import app_paths, messages
from .. import stats as stats_mod
from ..i18n import N_, dec, tr
from . import theme
from .widgets import (PARAGRAPH, BarChart, Card, ComboBox, SortItem, StatCard, label, make_table, page_header,
                      restore_header, save_header)

RANGES = [("session", N_("This session"), N_("Session report")),
          ("12h", N_("Last 12 hours"), N_("12-hour report")),
          ("24h", N_("Last 24 hours"), N_("Daily report")), ("7d", N_("Last 7 days"), N_("Weekly report")),
          ("all", N_("Everything"), N_("Overall report"))]
ALL_PROFILES = N_("All raids (total)")
WEEKDAYS = (N_("Mon"), N_("Tue"), N_("Wed"), N_("Thu"), N_("Fri"), N_("Sat"), N_("Sun"))


def fmt_hours(seconds: float) -> str:
    """Farming time, short: “45 min”, “2.5 h”, “12 h”."""
    if seconds < 3600:
        return tr("{minutes} min", minutes=round(seconds / 60))
    hours = seconds / 3600
    return tr("{hours} h", hours=dec(f"{hours:.1f}") if hours < 10 else f"{hours:.0f}")


def _num(value: Optional[float], digits: int = 1) -> str:
    return "–" if value is None else dec(f"{value:.{digits}f}")


def _dur(value: Optional[float]) -> str:
    return messages.fmt_duration(value)



def _archive_name(path) -> str:
    """“raid_history_2026-10-07_101500.csv” -> “07.10.2026 10:15”."""
    try:
        stamp = datetime.strptime(Path(path).stem[len("raid_history_"):], "%Y-%m-%d_%H%M%S")
        return stamp.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return Path(path).stem

class StatsPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.engine = main.engine
        self._dirty = True
        self._last = 0.0
        self._rows: list = []
        self._profile_names: list[str] = []
        self._week_text = ""
        self._archive = None
        self._archive_path = None
        self._computing = False
        self._generation = 0

        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 14)

        # title, selection and actions in one row (page fits without scrolling)
        head = page_header(tr("Statistics"), tr("Every attempt counts – every wave gives rewards."))
        theme.track_spacing(head, 8)
        self.profile = ComboBox()
        theme.track_min_width(self.profile, 170)
        self.profile.addItem(tr(ALL_PROFILES), None)
        self.profile.currentIndexChanged.connect(lambda _i: self.mark_dirty())
        self.range = ComboBox()
        for key, text, _title in RANGES:
            self.range.addItem(tr(text), key)
        self.range.currentIndexChanged.connect(lambda _i: self.mark_dirty())
        head.addSpacing(theme.px(8))
        head.addWidget(self.profile)
        head.addWidget(self.range)
        head.addStretch(1)
        save_card = QPushButton(tr("Save card"))
        save_card.setToolTip(tr("Save the stats as an image (PNG) – to share with friends"))
        save_card.clicked.connect(self._save_card)
        send_card = QPushButton(tr("Card to Discord"))
        send_card.clicked.connect(self._send_card)
        more = QToolButton()
        more.setText("⋯")
        more.setToolTip(tr("More actions"))
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction(tr("Save monthly recap …"), self._save_month)
        menu.addAction(tr("Monthly recap to Discord"), self._send_month)
        menu.addSeparator()
        self.delete_action = menu.addAction(tr("Delete selected entry"), self._delete_selected)
        menu.addSeparator()
        self.archive_menu = menu.addMenu(tr("View archive"))
        self.archive_menu.aboutToShow.connect(self._fill_archive_menu)
        self.archive_action = menu.addAction(tr("Archive and start over …"), self._archive_now)
        menu.addSeparator()
        menu.addAction(tr("Open CSV"), self._open_csv)
        menu.addAction(tr("Open data folder"),
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_paths.data_dir()))))
        more.setMenu(menu)
        for widget in (save_card, send_card, more):
            head.addWidget(widget)
        root.addLayout(head)
        self.archive_bar = QHBoxLayout()                 # visible while an archive is shown
        self.archive_label = label("", "warn")
        self.archive_back = QPushButton(tr("Back to current statistics"))
        self.archive_back.setObjectName("slim")
        self.archive_back.clicked.connect(lambda: self._show_archive(None))
        self.archive_bar.addWidget(self.archive_label)
        self.archive_bar.addWidget(self.archive_back)
        self.archive_bar.addStretch(1)
        root.addLayout(self.archive_bar)
        self.archive_label.setVisible(False)
        self.archive_back.setVisible(False)

        def kpi_row(*cards) -> QHBoxLayout:
            row = QHBoxLayout()
            theme.track_spacing(row, 12)
            for card in cards:
                row.addWidget(card, 1)
            return row

        self.k_attempts = StatCard(tr("Attempts"))
        self.k_waves = StatCard(tr("Waves total"))
        self.k_wph = StatCard(tr("Waves per hour"))
        self.k_avg_wave = StatCard(tr("Avg. time per raid"))
        self.k_best_wave = StatCard(tr("Best wave (record)"))
        root.addLayout(kpi_row(self.k_attempts, self.k_waves, self.k_wph, self.k_avg_wave, self.k_best_wave))
        # secondary values as one calm line instead of five more tiles
        self.details = label("", "muted", wrap=True)
        self.details.setToolTip(tr("Durations only use measured times; estimates (marked ~) are not included."))
        root.addWidget(self.details)
        self.wall_label = label("", "warn", wrap=True)          # “wall” of the chosen raid
        self.wall_label.setVisible(False)
        root.addWidget(self.wall_label)

        mid = QHBoxLayout()
        theme.track_spacing(mid, 16)
        runs = Card()                                    # tabs: last attempts | raids compared | records
        list_tabs = QHBoxLayout()
        self.list_group = QButtonGroup(self)
        self.list_group.setExclusive(True)
        for i, text in enumerate((tr("Recent attempts"), tr("All raids compared"), tr("Personal records"))):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setObjectName("tab")
            self.list_group.addButton(btn, i)
            list_tabs.addWidget(btn)
        self.list_group.button(0).setChecked(True)
        list_tabs.addStretch(1)
        runs.body.addLayout(list_tabs)
        self.lists = QStackedWidget()
        self.table = make_table([tr("Ended at"), tr("Raid"), tr("Final wave"), tr("Duration")],
                                rights=(2, 3), widths=(140, 150, 90, 80), selectable=True)
        self.table.setToolTip(tr("Click a header to sort, drag column borders to change the width. ~ = estimated "
                                 "duration."))
        theme.track_min_height(self.table, 200)
        restore_header(self.table, "stats_runs2")
        self.lists.addWidget(self.table)
        runs.body.addWidget(self.lists, 1)
        mid.addWidget(runs, 3)

        chart_card = Card(tr("Analysis"), " ")
        self.chart_info = chart_card.info
        tabs = QHBoxLayout()
        self.chart_group = QButtonGroup(self)
        self.chart_group.setExclusive(True)
        for i, text in enumerate((tr("Raids per day"), tr("Trend"), tr("Waves per hour"), tr("Week"))):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setObjectName("tab")
            self.chart_group.addButton(btn, i)
            tabs.addWidget(btn)
        self.chart_group.button(0).setChecked(True)
        tabs.addStretch(1)
        chart_card.body.addLayout(tabs)
        self.charts = QStackedWidget()
        self.chart_hist, self.chart_trend, self.chart_hour = BarChart(), BarChart(), BarChart()
        self.chart_week = BarChart()
        for chart in (self.chart_hist, self.chart_trend, self.chart_hour, self.chart_week):
            self.charts.addWidget(chart)
        chart_card.body.addWidget(self.charts, 1)
        self.chart_group.idClicked.connect(self._chart_changed)
        mid.addWidget(chart_card, 2)
        root.addLayout(mid, 1)
        self._chart_changed(0)

        self.per_table = make_table([tr("Raid"), tr("Attempts"), tr("Waves total"), tr("Best wave"),
                                     tr("Avg. duration"), tr("Waves/h")], rights=(1, 2, 3, 4, 5),
                                    widths=(190, 90, 120, 95, 100, 100))
        restore_header(self.per_table, "stats_raids")
        self.lists.addWidget(self.per_table)

        rec_page = QWidget()                              # records over the whole history, 2 × 2 tiles
        rec_grid = QGridLayout(rec_page)
        rec_grid.setContentsMargins(0, 0, 0, 0)
        theme.track_spacing(rec_grid, 12)
        self.records = {}
        for i, (key, title) in enumerate((("best_wave", tr("Best wave")), ("best_day", tr("Strongest day")),
                                          ("best_hour", tr("Best hour")), ("longest", tr("Longest session")))):
            card = StatCard(title)
            card.sub = label("", "small")
            card.body.addWidget(card.sub)
            self.records[key] = card
            rec_grid.addWidget(card, i // 2, i % 2)
        rec_grid.setRowStretch(2, 1)
        self.lists.addWidget(rec_page)
        self.list_group.idClicked.connect(self.lists.setCurrentIndex)

    def _fill_records(self, rec: dict) -> None:
        """Best values over the whole history (independent of the raid and period selection)."""
        def show(key, value, sub):
            self.records[key].set_value(value)
            self.records[key].sub.setText(sub)
        if rec["best_wave"]:
            wave, ts, raid = rec["best_wave"]
            show("best_wave", str(wave), datetime.fromtimestamp(ts).strftime("%d.%m.%Y") + (f" · {raid}" if raid else ""))
        else:
            show("best_wave", "–", "")
        if rec["best_day"]:
            day, n, waves = rec["best_day"]
            show("best_day", tr("{count} raids", count=messages.fmt_k(n)),
                 day.strftime("%d.%m.%Y") + " · " + tr("{waves} waves", waves=messages.fmt_int(waves)))
        else:
            show("best_day", "–", "")
        if rec["best_hour"]:
            hour, waves = rec["best_hour"]
            show("best_hour", tr("{waves} waves", waves=messages.fmt_int(waves)),
                 hour.strftime("%d.%m.%Y · %H:00"))
        else:
            show("best_hour", "–", "")
        if rec["longest"]:
            seconds, start, n = rec["longest"]
            show("longest", fmt_hours(seconds),
                 datetime.fromtimestamp(start).strftime("%d.%m.%Y") + " · " + tr("{count} raids", count=n))
        else:
            show("longest", "–", "")

    # ------------------------------------------------------------------ Archive
    @property
    def store(self):
        """Statistics shown: the current one or an opened archive (view only)."""
        return self._archive or self.engine.stats

    def _fill_archive_menu(self) -> None:
        from ..stats import StatsStore
        self.archive_menu.clear()
        files = StatsStore.archives(app_paths.archive_dir())
        if self._archive is not None:
            self.archive_menu.addAction(tr("Current statistics"), lambda: self._show_archive(None))
            self.archive_menu.addSeparator()
        for path in files:
            self.archive_menu.addAction(_archive_name(path), lambda p=path: self._show_archive(p))
        if not files:
            act = self.archive_menu.addAction(tr("No archive yet"))
            act.setEnabled(False)

    def _show_archive(self, path) -> None:
        from ..stats import StatsStore
        self._archive = StatsStore(path) if path else None
        self._archive_path = path
        viewing = self._archive is not None
        self.archive_label.setText(tr("Archive {name} – view only", name=_archive_name(path)) if viewing else "")
        self.archive_label.setVisible(viewing)
        self.archive_back.setVisible(viewing)
        self.delete_action.setEnabled(not viewing)
        self.archive_action.setEnabled(not viewing)
        if viewing and self.range.currentData() == "session":
            self.range.setCurrentIndex(self.range.findData("all"))     # an archive has no running session
        self._profile_names = []
        self.mark_dirty()
        self.refresh()

    def _archive_now(self) -> None:
        if QMessageBox.question(self, tr("Archive and start over"), tr(
                "The statistics are moved to the archive and start from zero (including the raid number). The "
                "archive stays available under ⋯ → View archive.")) != QMessageBox.StandardButton.Yes:
            return
        if self.engine.archive_stats() is None:
            self.main.show_toast(tr("Nothing to archive yet"))
            return
        self.main.show_toast(tr("Archived ✓ – statistics start over"))
        self._profile_names = []
        self.mark_dirty()
        self.refresh()

    # ------------------------------------------------------------------ Helpers
    def mark_dirty(self) -> None:
        self._dirty = True

    def save_ui(self) -> None:
        save_header(self.table, "stats_runs2")
        save_header(self.per_table, "stats_raids")

    def _raid(self) -> Optional[str]:
        return self.profile.currentData()

    def _since(self) -> Optional[float]:
        key = self.range.currentData()
        now = time.time()
        if key == "session":
            return self.store.session_start
        return {"12h": now - 12 * 3600, "24h": now - 24 * 3600, "7d": now - 7 * 86400}.get(key)

    def _report_title(self) -> str:
        key = self.range.currentData()
        return tr(next((t for k, _n, t in RANGES if k == key), N_("Report")))

    def _chart_changed(self, index: int) -> None:
        self.charts.setCurrentIndex(index)
        # how far a raid gets doesn't matter (owner): raids per day instead of the final-wave distribution
        self.chart_info.set_info(tr((N_("Raids per day over the last 14 days."),
                                    N_("Raids per hour (per day for long periods) in the chosen period."),
                                    N_("Waves cleared in the last 10 hours."),
                                    N_("Farming time per day over the last 7 days – breaks longer than 15 minutes "
                                       "don't count."))
                                   [index]) + (self._week_text if index == 3 else ""))

    # ------------------------------------------------------------------ Actions
    def _save_card(self) -> None:
        from ..report_card import render_card
        path, _ = QFileDialog.getSaveFileName(self, tr("Save stats card"),
                                              str(Path.home() / "astral-statistik.png"), tr("Image (*.png)"))
        if not path:
            return
        store, since, raid, title = self.store, self._since(), self._raid(), self._report_title()
        self._save_in_background(path, lambda: render_card(store, since, raid, title))

    @staticmethod
    def _month() -> tuple[int, int]:
        """Current month – in the first 3 days the previous month (then the recap is “complete”)."""
        now = datetime.now()
        if now.day <= 3:
            return (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
        return now.year, now.month

    def _save_month(self) -> None:
        from ..report_card import render_month_card
        year, month = self._month()
        path, _ = QFileDialog.getSaveFileName(self, tr("Save monthly recap"),
                                              str(Path.home() / f"astral-{year}-{month:02d}.png"), tr("Image (*.png)"))
        if not path:
            return
        store = self.store
        self._save_in_background(path, lambda: render_month_card(store, year, month))

    def _save_in_background(self, path: str, render) -> None:
        """Draw and save the card in the background (~0.2 s) – the UI stays usable."""
        self.main.show_toast(tr("Creating card …"))

        def work() -> None:
            try:
                Path(path).write_bytes(render())
                self.main.post(lambda: self.main.show_toast(tr("Card saved ✓")))
            except OSError as exc:
                self.main.post(lambda e=exc: QMessageBox.critical(self, tr("Save"),
                                                                  tr("Could not save: {error}", error=e)))

        threading.Thread(target=work, name="card", daemon=True).start()

    def _send_month(self) -> None:
        if not self.engine.send_month(*self._month(), stats=self.store):
            QMessageBox.information(self, tr("Discord"), tr("Please enter a webhook first and keep “Report / stats "
                                                            "card” enabled under “Alerts”."))
            return
        self.main.show_toast(tr("Sending card …"))

    def _send_card(self) -> None:
        if not self.engine.send_report(self._since(), self._raid(), self._report_title(), stats=self.store):
            QMessageBox.information(self, tr("Discord"), tr("Please enter a webhook first and keep “Report / stats "
                                                            "card” enabled under “Alerts”."))
            return
        self.main.show_toast(tr("Sending card …"))

    def _delete_selected(self) -> None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        index = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if index is None or not (0 <= int(index) < len(self._rows)):
            QMessageBox.information(self, tr("Delete entry"), tr("Please select an entry in the table first."))
            return
        if QMessageBox.question(self, tr("Delete entry"), tr("Delete this entry permanently?")) \
                == QMessageBox.StandardButton.Yes:
            self.store.delete_record(self._rows[int(index)])
            self.mark_dirty()
            self.refresh()

    def _open_csv(self) -> None:
        path = app_paths.history_file()
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------------ Display
    def _sync_profiles(self, names: list) -> None:
        if names == self._profile_names:
            return
        current = self._raid()
        self._profile_names = names
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItem(tr(ALL_PROFILES), None)
        for name in names:
            self.profile.addItem(stats_mod.raid_label(name), name)
        index = self.profile.findData(current)
        self.profile.setCurrentIndex(index if index >= 0 else 0)
        self.profile.blockSignals(False)

    def _fill(self, table, rows: list[list[SortItem]]) -> None:
        """Fills a table without losing sorting/columns."""
        header = table.horizontalHeader()
        column, order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for r, cells in enumerate(rows):
            for c, cell in enumerate(cells):
                table.setItem(r, c, cell)
        table.setSortingEnabled(True)
        table.sortByColumn(column if column >= 0 else 0, order)

    def refresh(self) -> None:
        """Evaluate in the background, show in the GUI thread – the page stays usable right away even with a long
        history (one year ≈ 100 000 raids: ~0.1–0.2 s of computing after each new raid)."""
        now = time.monotonic()
        if not self._dirty and now - self._last < 10:
            return
        if self._computing:
            return                                       # already running; again afterwards if something changed meanwhile
        self._dirty, self._last = False, now
        self._computing = True
        self._generation += 1
        job = (self._generation, self.store, self._since(), self._raid(), self.range.currentData() in ("7d", "all"))

        def work() -> None:
            try:
                data = self._compute(*job[1:])
            except Exception:
                data = None
            self.main.post(lambda: self._show(job[0], data))

        threading.Thread(target=work, name="stats", daemon=True).start()

    @staticmethod
    def _compute(stats, since, raid, by_day) -> dict:
        """All metrics of the page (without Qt – may run in its own thread)."""
        return {
            "names": stats.raid_names(), "summary": stats.summary(since, raid), "best": stats.best_wave(raid),
            "total": stats.snapshot().total_attempts, "wall": stats.wall(raid),
            "rows": stats.last_runs(200, since, raid), "days": stats.daily(14, raid),
            "trend": stats.trend(since, raid, by_day), "hours": stats.hourly_waves(10, raid),
            "week": stats.daily(7, raid), "records": stats.personal_records(), "per_raid": stats.per_raid(since),
        }

    def _show(self, generation: int, data: Optional[dict]) -> None:
        self._computing = False
        if data is None or generation != self._generation:
            return
        self._sync_profiles(data["names"])
        s = data["summary"]
        self.k_attempts.set_value(messages.fmt_k(s.attempts))
        self.k_waves.set_value(messages.fmt_int(s.waves_total))
        self.k_wph.set_value(messages.fmt_int(round(s.waves_per_hour)) if s.waves_per_hour else "–")
        self.k_avg_wave.set_value(_dur(s.avg_duration_all))
        self.k_best_wave.set_value(str(data["best"] or "–"))
        self.details.setText(tr("Avg. {dur} per attempt  ·  {spw} per wave  ·  {aph} attempts/h  ·  {all} attempts "
                                "in total",
                                dur=_dur(s.avg_duration_all),
                                spw="–" if s.sec_per_wave is None else dec(f"{s.sec_per_wave:.1f} s"),
                                aph=_num(s.attempts_per_hour),
                                all=messages.fmt_k(data["total"])))
        wall = data["wall"]
        self.wall_label.setVisible(wall is not None)
        if wall:
            self.wall_label.setText(tr(
                "Wall at wave {wave}: {streak} attempts in a row did not get further ({share} % of the recent "
                "attempts end exactly there). Probably a boss wave – you will get a message as soon as you beat it.",
                wave=wall.wave, streak=wall.streak, share=f"{wall.share * 100:.0f}"))

        self._rows = data["rows"]
        rows = []
        for i, rec in enumerate(self._rows):
            first = SortItem(datetime.fromtimestamp(rec.ts_end).strftime("%d.%m. %H:%M:%S"), rec.ts_end)
            first.setData(Qt.ItemDataRole.UserRole, i)                      # reference to the record (for “Delete”)
            rows.append([
                first, SortItem(rec.raid or "–", (rec.raid or "~").lower()),
                SortItem(messages.fmt_wave(rec.max_wave, rec.total_waves), rec.max_wave, right=True),
                SortItem(messages.fmt_duration_est(rec.duration_s, rec.estimated), rec.duration_s or -1, right=True)])
        self._fill(self.table, rows)

        self.chart_hist.set_data([(f"{d['day'].day}.", d["attempts"]) for d in data["days"]])
        self.chart_trend.set_data([(label_, n) for label_, _avg, n in data["trend"]])
        self.chart_hour.set_data([(f"{h:02d}", c) for h, c in data["hours"]])
        week = data["week"]
        self.chart_week.set_data([(tr(WEEKDAYS[d["day"].weekday()]), round(d["farm_s"] / 60)) for d in week],
                                 fmt=lambda minutes: fmt_hours(minutes * 60))
        self._week_text = PARAGRAPH + tr("This week: {time} · {attempts} attempts · {waves} waves",
                                         time=fmt_hours(sum(d["farm_s"] for d in week)),
                                         attempts=sum(d["attempts"] for d in week),
                                         waves=messages.fmt_int(sum(d["waves"] for d in week)))
        if self.charts.currentIndex() == 3:
            self._chart_changed(3)

        self._fill_records(data["records"])
        per_rows = []
        for item in data["per_raid"]:
            per_rows.append([
                SortItem(stats_mod.raid_label(item["raid"]), item["raid"].lower()),
                SortItem(str(item["attempts"]), item["attempts"], right=True),
                SortItem(messages.fmt_int(item["waves_total"]), item["waves_total"], right=True),
                SortItem(str(item["best_wave"]), item["best_wave"], right=True),
                SortItem(_dur(item["avg_duration_all"]), item["avg_duration_all"] or -1, right=True),
                SortItem(_num(item["waves_per_hour"], 0), item["waves_per_hour"] or -1, right=True)])
        self._fill(self.per_table, per_rows)
        if self._dirty:                                   # changed while computing: once more right away
            self.refresh()

    def load(self, settings) -> None:
        pass

    def apply(self, settings) -> None:
        pass
