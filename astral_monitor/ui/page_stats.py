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
from .widgets import (BarChart, Card, ComboBox, SortItem, StatCard, label, make_table, restore_header,
                      save_header)

RANGES = [("session", N_("Diese Session"), N_("Session-Bericht")),
          ("12h", N_("Letzte 12 Stunden"), N_("12-Stunden-Bericht")),
          ("24h", N_("Letzte 24 Stunden"), N_("Tagesbericht")), ("7d", N_("Letzte 7 Tage"), N_("Wochenbericht")),
          ("all", N_("Alles"), N_("Gesamtbericht"))]
ALL_PROFILES = N_("Alle Raids (gesamt)")


def _num(value: Optional[float], digits: int = 1) -> str:
    return "–" if value is None else dec(f"{value:.{digits}f}")


def _dur(value: Optional[float]) -> str:
    return messages.fmt_duration(value)


class StatsPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.engine = main.engine
        self._dirty = True
        self._last = 0.0
        self._rows: list = []
        self._profile_names: list[str] = []

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
        menu.addAction(tr("Ausgewählten Eintrag löschen"), self._delete_selected)
        menu.addSeparator()
        menu.addAction(tr("CSV öffnen"), self._open_csv)
        menu.addAction(tr("Datenordner öffnen"),
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_paths.data_dir()))))
        more.setMenu(menu)
        for widget in (save_card, send_card, more):
            head.addWidget(widget)
        root.addLayout(head)

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
                                 "✓ = bis zum Ende geschafft, ~ = geschätzte Dauer."))
        theme.track_min_height(self.table, 320)
        restore_header(self.table, "stats_runs2")
        runs.body.addWidget(self.table, 1)
        mid.addWidget(runs, 3)

        chart_card = Card(tr("Auswertung"), " ")
        self.chart_info = chart_card.info
        tabs = QHBoxLayout()
        self.chart_group = QButtonGroup(self)
        self.chart_group.setExclusive(True)
        for i, text in enumerate((tr("Endwellen"), tr("Trend"), tr("Wellen pro Stunde"))):
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
        for chart in (self.chart_hist, self.chart_trend, self.chart_hour):
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
            return self.engine.stats.session_start
        return {"12h": now - 12 * 3600, "24h": now - 24 * 3600, "7d": now - 7 * 86400}.get(key)

    def _report_title(self) -> str:
        key = self.range.currentData()
        return tr(next((t for k, _n, t in RANGES if k == key), N_("Bericht")))

    def _chart_changed(self, index: int) -> None:
        self.charts.setCurrentIndex(index)
        self.chart_info.set_info(tr((N_("Wo enden die Versuche? Anzahl je Endwelle (Gruppen, wenn die Spanne groß ist)."),
                                    N_("Ø Endwelle je Stunde (bei langen Zeiträumen je Tag) – steigt sie, wirst du besser."),
                                    N_("Geschaffte Wellen der letzten 10 Stunden."))[index]))

    # ------------------------------------------------------------------ Aktionen
    def _save_card(self) -> None:
        from ..report_card import render_card
        path, _ = QFileDialog.getSaveFileName(self, tr("Statistik-Karte speichern"),
                                              str(Path.home() / "astral-statistik.png"), tr("Bild (*.png)"))
        if not path:
            return
        png = render_card(self.engine.stats, self._since(), self._raid(), self._report_title())
        try:
            Path(path).write_bytes(png)
        except OSError as exc:
            QMessageBox.critical(self, tr("Speichern"), tr("Konnte nicht speichern: {error}", error=exc))
            return
        self.main.show_toast(tr("Karte gespeichert ✓"))

    def _send_card(self) -> None:
        if not self.engine.send_report(self._since(), self._raid(), self._report_title()):
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
            self.engine.stats.delete_record(self._rows[int(index)])
            self.mark_dirty()
            self.refresh()

    def _open_csv(self) -> None:
        path = app_paths.history_file()
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------------ Anzeige
    def _sync_profiles(self) -> None:
        names = self.engine.stats.raid_names()
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
        stats = self.engine.stats
        self._sync_profiles()
        since, raid = self._since(), self._raid()
        s = stats.summary(since, raid)

        self.k_attempts.set_value(messages.fmt_int(s.attempts))
        self.k_waves.set_value(messages.fmt_int(s.waves_total))
        self.k_wph.set_value(_num(s.waves_per_hour, 0))
        self.k_avg_wave.set_value(_num(s.avg_wave_all))
        self.k_best_wave.set_value(str(stats.best_wave(raid) or "–"))
        self.details.setText(tr("Ø {dur} pro Versuch  ·  {spw} pro Welle  ·  {aph} Versuche/Std.  ·  {done}× bis zum "
                                "Ende  ·  {all} Versuche insgesamt",
                                dur=_dur(s.avg_duration_all),
                                spw="–" if s.sec_per_wave is None else dec(f"{s.sec_per_wave:.1f} s"),
                                aph=_num(s.attempts_per_hour), done=messages.fmt_int(s.ok),
                                all=messages.fmt_int(stats.snapshot().total_attempts)))
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
            done = "  ✓" if rec.result == "ok" else ""
            rows.append([
                first, SortItem(rec.raid or "–", (rec.raid or "~").lower()),
                SortItem(f"{rec.max_wave}/{rec.total_waves}{done}", rec.max_wave, right=True),
                SortItem(messages.fmt_duration_est(rec.duration_s, rec.estimated), rec.duration_s or -1, right=True)])
        self._fill(self.table, rows)

        self.chart_hist.set_data(stats.wave_histogram(since, raid))
        by_day = self.range.currentData() in ("7d", "all")
        self.chart_trend.set_data([(label_, int(round(avg))) for label_, avg, _n in stats.trend(since, raid, by_day)])
        self.chart_hour.set_data([(f"{h:02d}", c) for h, c in stats.hourly_waves(10, raid)])

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
