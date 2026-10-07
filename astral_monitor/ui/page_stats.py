"""Seite „Statistik": alle Versuche zusammen (jede Welle gibt Belohnungen), je Raid oder gesamt."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QHBoxLayout, QMenu, QMessageBox, QPushButton,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import app_paths, messages
from ..i18n import N_, dec, tr
from . import theme
from .widgets import (PARAGRAPH, BarChart, Card, ComboBox, SortItem, StatCard, label, make_table, restore_header,
                      save_header)

RANGES = [("session", N_("Diese Session"), N_("Session-Bericht")),
          ("12h", N_("Letzte 12 Stunden"), N_("12-Stunden-Bericht")),
          ("24h", N_("Letzte 24 Stunden"), N_("Tagesbericht")), ("7d", N_("Letzte 7 Tage"), N_("Wochenbericht")),
          ("all", N_("Alles"), N_("Gesamtbericht"))]
ALL_PROFILES = N_("Alle Raids (gesamt)")
WEEKDAYS = (N_("Mo"), N_("Di"), N_("Mi"), N_("Do"), N_("Fr"), N_("Sa"), N_("So"))


def fmt_hours(seconds: float) -> str:
    """Farmzeit kurz: „45 min“, „2,5 h“, „12 h“."""
    if seconds < 3600:
        return tr("{minutes} min", minutes=round(seconds / 60))
    hours = seconds / 3600
    return tr("{hours} h", hours=dec(f"{hours:.1f}") if hours < 10 else f"{hours:.0f}")


def _num(value: Optional[float], digits: int = 1) -> str:
    return "–" if value is None else dec(f"{value:.{digits}f}")


def _dur(value: Optional[float]) -> str:
    return messages.fmt_duration(value)



def _archive_name(path) -> str:
    """„raid_history_2026-10-07_101500.csv“ -> „07.10.2026 10:15“."""
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

        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 14)

        # Titel und Bedienleiste in eigenen Zeilen, sonst wird die Seite bei kleinem Fenster zu breit
        root.addWidget(label(tr("Statistik"), "h1"))
        root.addWidget(label(tr("Jeder Versuch zählt – jede Welle gibt Belohnungen."), "muted", wrap=True))
        head = QHBoxLayout()
        theme.track_spacing(head, 8)
        self.profile = ComboBox()
        theme.track_min_width(self.profile, 170)
        self.profile.addItem(tr(ALL_PROFILES), None)
        self.profile.currentIndexChanged.connect(lambda _i: self.mark_dirty())
        self.range = ComboBox()
        for key, text, _title in RANGES:
            self.range.addItem(tr(text), key)
        self.range.currentIndexChanged.connect(lambda _i: self.mark_dirty())
        head.addWidget(self.profile)
        head.addWidget(self.range)
        head.addStretch(1)
        save_card = QPushButton(tr("Karte speichern"))
        save_card.setToolTip(tr("Statistik als Bild (PNG) speichern – zum Teilen mit Freunden"))
        save_card.clicked.connect(self._save_card)
        send_card = QPushButton(tr("Karte an Discord"))
        send_card.clicked.connect(self._send_card)
        more = QToolButton()
        more.setText("⋯")
        more.setToolTip(tr("Weitere Aktionen"))
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction(tr("Monatsrückblick speichern …"), self._save_month)
        menu.addAction(tr("Monatsrückblick an Discord"), self._send_month)
        menu.addSeparator()
        self.delete_action = menu.addAction(tr("Ausgewählten Eintrag löschen"), self._delete_selected)
        menu.addSeparator()
        self.archive_menu = menu.addMenu(tr("Archiv ansehen"))
        self.archive_menu.aboutToShow.connect(self._fill_archive_menu)
        self.archive_action = menu.addAction(tr("Archivieren und neu beginnen …"), self._archive_now)
        menu.addSeparator()
        menu.addAction(tr("CSV öffnen"), self._open_csv)
        menu.addAction(tr("Datenordner öffnen"),
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_paths.data_dir()))))
        more.setMenu(menu)
        for widget in (save_card, send_card, more):
            head.addWidget(widget)
        root.addLayout(head)
        self.archive_bar = QHBoxLayout()                 # sichtbar, solange ein Archiv angezeigt wird
        self.archive_label = label("", "warn")
        self.archive_back = QPushButton(tr("Zur aktuellen Statistik"))
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

        self.k_attempts = StatCard(tr("Versuche"))
        self.k_waves = StatCard(tr("Wellen gesamt"))
        self.k_wph = StatCard(tr("Wellen pro Stunde"))
        self.k_avg_wave = StatCard(tr("Ø Endwelle"))
        self.k_best_wave = StatCard(tr("Bestwelle (Rekord)"))
        root.addLayout(kpi_row(self.k_attempts, self.k_waves, self.k_wph, self.k_avg_wave, self.k_best_wave))
        # Nebenwerte als eine ruhige Zeile statt fünf weiterer Kacheln
        self.details = label("", "muted", wrap=True)
        self.details.setToolTip(tr("Dauer-Werte nutzen nur gemessene Zeiten; geschätzte (mit ~) fließen nicht ein."))
        root.addWidget(self.details)
        self.wall_label = label("", "warn", wrap=True)          # „Wand“ des gewählten Raids
        self.wall_label.setVisible(False)
        root.addWidget(self.wall_label)

        mid = QHBoxLayout()
        theme.track_spacing(mid, 16)
        runs = Card(tr("Letzte Versuche"))
        self.table = make_table([tr("Beendet um"), tr("Raid"), tr("Endwelle"), tr("Dauer")],
                                rights=(2, 3), widths=(140, 150, 90, 80), selectable=True)
        self.table.setToolTip(tr("Überschrift anklicken sortiert, Spaltenränder ziehen ändert die Breite. "
                                 "~ = geschätzte Dauer."))
        theme.track_min_height(self.table, 320)
        restore_header(self.table, "stats_runs2")
        runs.body.addWidget(self.table, 1)
        mid.addWidget(runs, 3)

        chart_card = Card(tr("Auswertung"), " ")
        self.chart_info = chart_card.info
        tabs = QHBoxLayout()
        self.chart_group = QButtonGroup(self)
        self.chart_group.setExclusive(True)
        for i, text in enumerate((tr("Endwellen"), tr("Trend"), tr("Wellen pro Stunde"), tr("Woche"))):
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
        root.addLayout(mid)
        self._chart_changed(0)

        per_card = Card(tr("Alle Raids im Vergleich"))
        self.per_table = make_table([tr("Raid"), tr("Versuche"), tr("Wellen gesamt"), tr("Ø Endwelle"), tr("Bestwelle"), tr("Ø Dauer"),
                                     tr("Wellen/Std")], rights=(1, 2, 3, 4, 5, 6),
                                    widths=(220, 100, 130, 110, 100, 100, 110))
        theme.track_min_height(self.per_table, 170)
        restore_header(self.per_table, "stats_raids")
        per_card.body.addWidget(self.per_table, 1)
        root.addWidget(per_card)

    # ------------------------------------------------------------------ Archiv
    @property
    def store(self):
        """Angezeigte Statistik: die aktuelle oder ein geöffnetes Archiv (nur ansehen)."""
        return self._archive or self.engine.stats

    def _fill_archive_menu(self) -> None:
        from ..stats import StatsStore
        self.archive_menu.clear()
        files = StatsStore.archives(app_paths.archive_dir())
        if self._archive is not None:
            self.archive_menu.addAction(tr("Aktuelle Statistik"), lambda: self._show_archive(None))
            self.archive_menu.addSeparator()
        for path in files:
            self.archive_menu.addAction(_archive_name(path), lambda p=path: self._show_archive(p))
        if not files:
            act = self.archive_menu.addAction(tr("Noch kein Archiv"))
            act.setEnabled(False)

    def _show_archive(self, path) -> None:
        from ..stats import StatsStore
        self._archive = StatsStore(path) if path else None
        self._archive_path = path
        viewing = self._archive is not None
        self.archive_label.setText(tr("Archiv {name} – nur ansehen", name=_archive_name(path)) if viewing else "")
        self.archive_label.setVisible(viewing)
        self.archive_back.setVisible(viewing)
        self.delete_action.setEnabled(not viewing)
        self.archive_action.setEnabled(not viewing)
        if viewing and self.range.currentData() == "session":
            self.range.setCurrentIndex(self.range.findData("all"))     # im Archiv gibt es keine laufende Session
        self._profile_names = []
        self.mark_dirty()
        self.refresh()

    def _archive_now(self) -> None:
        if QMessageBox.question(self, tr("Archivieren und neu beginnen"), tr(
                "Die Statistik wird ins Archiv verschoben und beginnt bei null (auch die Raid-Nummer). Das Archiv "
                "bleibt unter ⋯ → Archiv ansehen erhalten.")) != QMessageBox.StandardButton.Yes:
            return
        if self.engine.archive_stats() is None:
            self.main.show_toast(tr("Noch nichts zu archivieren"))
            return
        self.main.show_toast(tr("Archiviert ✓ – die Statistik beginnt neu"))
        self._profile_names = []
        self.mark_dirty()
        self.refresh()

    # ------------------------------------------------------------------ Hilfen
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
        return tr(next((t for k, _n, t in RANGES if k == key), N_("Bericht")))

    def _chart_changed(self, index: int) -> None:
        self.charts.setCurrentIndex(index)
        self.chart_info.set_info(tr((N_("Wo enden die Versuche? Anzahl je Endwelle (Gruppen, wenn die Spanne groß ist)."),
                                    N_("Ø Endwelle je Stunde (bei langen Zeiträumen je Tag) – steigt sie, wirst du besser."),
                                    N_("Geschaffte Wellen der letzten 10 Stunden."),
                                    N_("Farmzeit je Tag der letzten 7 Tage – Pausen über 15 Minuten zählen nicht."))
                                   [index]) + (self._week_text if index == 3 else ""))

    # ------------------------------------------------------------------ Aktionen
    def _save_card(self) -> None:
        from ..report_card import render_card
        path, _ = QFileDialog.getSaveFileName(self, tr("Statistik-Karte speichern"),
                                              str(Path.home() / "astral-statistik.png"), tr("Bild (*.png)"))
        if not path:
            return
        png = render_card(self.store, self._since(), self._raid(), self._report_title())
        try:
            Path(path).write_bytes(png)
        except OSError as exc:
            QMessageBox.critical(self, tr("Speichern"), tr("Konnte nicht speichern: {error}", error=exc))
            return
        self.main.show_toast(tr("Karte gespeichert ✓"))

    @staticmethod
    def _month() -> tuple[int, int]:
        """Laufender Monat – in den ersten 3 Tagen der Vormonat (dann ist der Rückblick „fertig“)."""
        now = datetime.now()
        if now.day <= 3:
            return (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
        return now.year, now.month

    def _save_month(self) -> None:
        from ..report_card import render_month_card
        year, month = self._month()
        path, _ = QFileDialog.getSaveFileName(self, tr("Monatsrückblick speichern"),
                                              str(Path.home() / f"astral-{year}-{month:02d}.png"), tr("Bild (*.png)"))
        if not path:
            return
        try:
            Path(path).write_bytes(render_month_card(self.store, year, month))
        except OSError as exc:
            QMessageBox.critical(self, tr("Speichern"), tr("Konnte nicht speichern: {error}", error=exc))
            return
        self.main.show_toast(tr("Karte gespeichert ✓"))

    def _send_month(self) -> None:
        if not self.engine.send_month(*self._month(), stats=self.store):
            QMessageBox.information(self, tr("Discord"), tr("Bitte zuerst einen Webhook eintragen und „Bericht / Statistik-Karte“ "
                                                     "unter „Meldungen“ aktiviert lassen."))
            return
        self.main.show_toast(tr("Karte wird gesendet …"))

    def _send_card(self) -> None:
        if not self.engine.send_report(self._since(), self._raid(), self._report_title(), stats=self.store):
            QMessageBox.information(self, tr("Discord"), tr("Bitte zuerst einen Webhook eintragen und „Bericht / Statistik-Karte“ "
                                                     "unter „Meldungen“ aktiviert lassen."))
            return
        self.main.show_toast(tr("Karte wird gesendet …"))

    def _delete_selected(self) -> None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        index = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if index is None or not (0 <= int(index) < len(self._rows)):
            QMessageBox.information(self, tr("Eintrag löschen"), tr("Bitte zuerst einen Eintrag in der Tabelle auswählen."))
            return
        if QMessageBox.question(self, tr("Eintrag löschen"), tr("Diesen Eintrag dauerhaft löschen?")) \
                == QMessageBox.StandardButton.Yes:
            self.store.delete_record(self._rows[int(index)])
            self.mark_dirty()
            self.refresh()

    def _open_csv(self) -> None:
        path = app_paths.history_file()
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------------ Anzeige
    def _sync_profiles(self) -> None:
        names = self.store.raid_names()
        if names == self._profile_names:
            return
        current = self._raid()
        self._profile_names = names
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItem(tr(ALL_PROFILES), None)
        for name in names:
            self.profile.addItem(name, name)
        index = self.profile.findData(current)
        self.profile.setCurrentIndex(index if index >= 0 else 0)
        self.profile.blockSignals(False)

    def _fill(self, table, rows: list[list[SortItem]]) -> None:
        """Füllt eine Tabelle, ohne Sortierung/Spalten zu verlieren."""
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
        now = time.monotonic()
        if not self._dirty and now - self._last < 10:
            return
        self._dirty, self._last = False, now
        stats = self.store
        self._sync_profiles()
        since, raid = self._since(), self._raid()
        s = stats.summary(since, raid)

        self.k_attempts.set_value(messages.fmt_k(s.attempts))
        self.k_waves.set_value(messages.fmt_int(s.waves_total))
        self.k_wph.set_value(messages.fmt_int(round(s.waves_per_hour)) if s.waves_per_hour else "–")
        self.k_avg_wave.set_value(_num(s.avg_wave_all))
        self.k_best_wave.set_value(str(stats.best_wave(raid) or "–"))
        self.details.setText(tr("Ø {dur} pro Versuch  ·  {spw} pro Welle  ·  {aph} Versuche/Std.  ·  {all} Versuche "
                                "insgesamt",
                                dur=_dur(s.avg_duration_all),
                                spw="–" if s.sec_per_wave is None else dec(f"{s.sec_per_wave:.1f} s"),
                                aph=_num(s.attempts_per_hour),
                                all=messages.fmt_k(stats.snapshot().total_attempts)))
        wall = stats.wall(raid)
        self.wall_label.setVisible(wall is not None)
        if wall:
            self.wall_label.setText(tr(
                "Wand bei Welle {wave}: {streak} Versuche in Folge sind nicht weitergekommen ({share} % der letzten "
                "Versuche enden genau dort). Vermutlich eine Boss-Welle – sobald du sie schaffst, kommt eine Meldung.",
                wave=wall.wave, streak=wall.streak, share=f"{wall.share * 100:.0f}"))

        self._rows = stats.last_runs(200, since, raid)
        rows = []
        for i, rec in enumerate(self._rows):
            first = SortItem(datetime.fromtimestamp(rec.ts_end).strftime("%d.%m. %H:%M:%S"), rec.ts_end)
            first.setData(Qt.ItemDataRole.UserRole, i)                      # Verweis auf den Datensatz (für „Löschen“)
            rows.append([
                first, SortItem(rec.raid or "–", (rec.raid or "~").lower()),
                SortItem(f"{rec.max_wave}/{rec.total_waves}", rec.max_wave, right=True),
                SortItem(messages.fmt_duration_est(rec.duration_s, rec.estimated), rec.duration_s or -1, right=True)])
        self._fill(self.table, rows)

        self.chart_hist.set_data(stats.wave_histogram(since, raid))
        by_day = self.range.currentData() in ("7d", "all")
        self.chart_trend.set_data([(label_, int(round(avg))) for label_, avg, _n in stats.trend(since, raid, by_day)])
        self.chart_hour.set_data([(f"{h:02d}", c) for h, c in stats.hourly_waves(10, raid)])
        week = stats.daily(7, raid)
        self.chart_week.set_data([(tr(WEEKDAYS[d["day"].weekday()]), round(d["farm_s"] / 60)) for d in week],
                                 fmt=lambda minutes: fmt_hours(minutes * 60))
        self._week_text = PARAGRAPH + tr("Diese Woche: {time} · {attempts} Versuche · {waves} Wellen",
                                         time=fmt_hours(sum(d["farm_s"] for d in week)),
                                         attempts=sum(d["attempts"] for d in week),
                                         waves=messages.fmt_int(sum(d["waves"] for d in week)))
        if self.charts.currentIndex() == 3:
            self._chart_changed(3)

        per_rows = []
        for item in stats.per_raid(since):
            per_rows.append([
                SortItem(item["raid"], item["raid"].lower()),
                SortItem(str(item["attempts"]), item["attempts"], right=True),
                SortItem(messages.fmt_int(item["waves_total"]), item["waves_total"], right=True),
                SortItem(_num(item["avg_wave"]), item["avg_wave"], right=True),
                SortItem(str(item["best_wave"]), item["best_wave"], right=True),
                SortItem(_dur(item["avg_duration_all"]), item["avg_duration_all"] or -1, right=True),
                SortItem(_num(item["waves_per_hour"], 0), item["waves_per_hour"] or -1, right=True)])
        self._fill(self.per_table, per_rows)

    def load(self, settings) -> None:
        pass

    def apply(self, settings) -> None:
        pass
