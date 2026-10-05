"""Seite „Statistik": Kennzahlen je Profil und Zeitraum – Erfolge und Fehlversuche, Verteilung, Trend, Karte zum Teilen."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QFileDialog, QHBoxLayout, QMenu, QMessageBox,
                               QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

from .. import app_paths, messages
from .widgets import BarChart, Card, ComboBox, StatCard, label, smooth

RANGES = [("session", "Diese Session", "Session-Bericht"), ("12h", "Letzte 12 Stunden", "12-Stunden-Bericht"),
          ("24h", "Letzte 24 Stunden", "Tagesbericht"), ("7d", "Letzte 7 Tage", "Wochenbericht"),
          ("all", "Alles", "Gesamtbericht")]
ALL_PROFILES = "Alle Raids (gesamt)"


def _pct(value: Optional[float]) -> str:
    return "–" if value is None else f"{value * 100:.0f} %"


def _num(value: Optional[float], digits: int = 1) -> str:
    return "–" if value is None else f"{value:.{digits}f}".replace(".", ",")


def _table(headers: list[str], selectable: bool = False) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    if selectable:
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    else:
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.setShowGrid(False)
    smooth(table)
    return table


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
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("Statistik", "h1"))
        titles.addWidget(label("Wähle einen Raid für seine eigene Statistik oder „Alle Raids“ für die Gesamtübersicht.", "muted"))
        head.addLayout(titles, 1)
        self.profile = ComboBox()
        self.profile.setMinimumWidth(190)
        self.profile.addItem(ALL_PROFILES, None)
        self.profile.currentIndexChanged.connect(lambda _i: self.mark_dirty())
        self.range = ComboBox()
        for key, text, _title in RANGES:
            self.range.addItem(text, key)
        self.range.currentIndexChanged.connect(lambda _i: self.mark_dirty())
        head.addWidget(self.profile)
        head.addWidget(self.range)
        save_card = QPushButton("Karte speichern")
        save_card.setToolTip("Statistik als Bild (PNG) speichern – zum Teilen mit Freunden")
        save_card.clicked.connect(self._save_card)
        send_card = QPushButton("Karte an Discord")
        send_card.clicked.connect(self._send_card)
        more = QToolButton()
        more.setText("⋯")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Ausgewählten Eintrag löschen", self._delete_selected)
        self.act_purge = menu.addAction("Alle Fehlversuche löschen …", self._purge)
        menu.addSeparator()
        menu.addAction("CSV öffnen", self._open_csv)
        menu.addAction("Datenordner öffnen",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_paths.data_dir()))))
        more.setMenu(menu)
        for widget in (save_card, send_card, more):
            head.addWidget(widget)
        root.addLayout(head)

        def kpi_row(*cards) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setSpacing(12)
            for card in cards:
                row.addWidget(card, 1)
            return row

        self.k_ok = StatCard("Raids erfolgreich")
        self.k_avg = StatCard("Ø Dauer (erfolgreich)")
        self.k_best = StatCard("Bestzeit")
        self.k_rate_h = StatCard("Raids pro Stunde")
        self.k_cycle = StatCard("Ø Zeit pro Erfolg")
        root.addLayout(kpi_row(self.k_ok, self.k_avg, self.k_best, self.k_rate_h, self.k_cycle))
        self.k_fail = StatCard("Fehlversuche / Neustarts")
        self.k_fail_dur = StatCard("Ø Dauer (Fehlversuch)")
        self.k_fail_wave = StatCard("Ø Endwelle")
        self.k_success = StatCard("Erfolgsquote")
        self.k_record = StatCard("Bestwelle (Rekord)")
        root.addLayout(kpi_row(self.k_fail, self.k_fail_dur, self.k_fail_wave, self.k_success, self.k_record))
        root.addWidget(label("Ø-Werte nutzen nur gemessene Dauern; geschätzte (mit ~ markiert, wenn der Start nicht zu sehen war) "
                             "fließen nicht ein. „Ø Zeit pro Erfolg“ umfasst alle Fehlversuche dazwischen.",
                             "small", wrap=True))

        mid = QHBoxLayout()
        mid.setSpacing(16)
        runs = Card("Letzte Versuche")
        self.table = _table(["Beendet um", "Raid", "Ergebnis", "Dauer", "Zykluszeit", "Welle"], selectable=True)
        self.table.setMinimumHeight(300)
        runs.body.addWidget(self.table, 1)
        mid.addWidget(runs, 3)

        chart_card = Card("Auswertung")
        tabs = QHBoxLayout()
        self.chart_group = QButtonGroup(self)
        self.chart_group.setExclusive(True)
        for i, text in enumerate(("Endwellen", "Trend", "Pro Stunde")):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setObjectName("nav")
            self.chart_group.addButton(btn, i)
            tabs.addWidget(btn)
        self.chart_group.button(0).setChecked(True)
        tabs.addStretch(1)
        chart_card.body.addLayout(tabs)
        self.chart_caption = label("", "small", wrap=True)
        chart_card.body.addWidget(self.chart_caption)
        self.charts = QStackedWidget()
        self.chart_hist, self.chart_trend, self.chart_hour = BarChart(), BarChart(), BarChart()
        for chart in (self.chart_hist, self.chart_trend, self.chart_hour):
            self.charts.addWidget(chart)
        chart_card.body.addWidget(self.charts, 1)
        self.chart_group.idClicked.connect(self._chart_changed)
        mid.addWidget(chart_card, 2)
        root.addLayout(mid)
        self._chart_changed(0)

        per_card = Card("Alle Raids im Vergleich")
        self.per_table = _table(["Raid", "Erfolgreich", "Fehlversuche", "Ø Dauer", "Ø Fehlversuch", "Bestzeit",
                                 "Bestwelle", "Ø Welle"])
        self.per_table.setMinimumHeight(150)
        per_card.body.addWidget(self.per_table, 1)
        root.addWidget(per_card)

    # ------------------------------------------------------------------ Hilfen
    def mark_dirty(self) -> None:
        self._dirty = True

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
        return next((t for k, _n, t in RANGES if k == key), "Bericht")

    def _chart_changed(self, index: int) -> None:
        self.charts.setCurrentIndex(index)
        self.chart_caption.setText(("Wo enden die Fehlversuche? Anzahl je Endwelle (Gruppen, wenn die Spanne groß ist).",
                                    "Ø erreichte Welle je Stunde (bei langen Zeiträumen je Tag) – steigt sie, wirst du besser.",
                                    "Erfolgreiche Raids der letzten 10 Stunden.")[index])

    # ------------------------------------------------------------------ Aktionen
    def _save_card(self) -> None:
        from ..report_card import render_card
        path, _ = QFileDialog.getSaveFileName(self, "Statistik-Karte speichern",
                                              str(Path.home() / "astral-statistik.png"), "Bild (*.png)")
        if not path:
            return
        png = render_card(self.engine.stats, self._since(), self._raid(), self._report_title())
        try:
            Path(path).write_bytes(png)
        except OSError as exc:
            QMessageBox.critical(self, "Speichern", f"Konnte nicht speichern: {exc}")
            return
        self.main.show_toast("Karte gespeichert ✓")

    def _send_card(self) -> None:
        if not self.engine.send_report(self._since(), self._raid(), self._report_title()):
            QMessageBox.information(self, "Discord", "Bitte zuerst einen Webhook eintragen und „Bericht / Statistik-Karte“ "
                                                     "unter „Meldungen“ aktiviert lassen.")
            return
        self.main.show_toast("Karte wird gesendet …")

    def _delete_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            QMessageBox.information(self, "Eintrag löschen", "Bitte zuerst einen Eintrag in der Tabelle auswählen.")
            return
        rec = self._rows[row]
        if QMessageBox.question(self, "Eintrag löschen", "Diesen Eintrag dauerhaft löschen?") \
                == QMessageBox.StandardButton.Yes:
            self.engine.stats.delete_record(rec)
            self.mark_dirty()
            self.refresh()

    def _purge(self) -> None:
        count = self.engine.stats.failed_count()
        if not count:
            return
        if QMessageBox.question(self, "Fehlversuche löschen",
                                f"{count} Fehlversuche/Neustarts dauerhaft aus dem Verlauf löschen?\n"
                                "Erfolgreiche Raids bleiben erhalten.") == QMessageBox.StandardButton.Yes:
            self.engine.stats.purge_failed()
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
        self.profile.addItem(ALL_PROFILES, None)
        for name in names:
            self.profile.addItem(name, name)
        index = self.profile.findData(current)
        self.profile.setCurrentIndex(index if index >= 0 else 0)
        self.profile.blockSignals(False)

    def refresh(self) -> None:
        now = time.monotonic()
        if not self._dirty and now - self._last < 10:
            return
        self._dirty, self._last = False, now
        stats = self.engine.stats
        self._sync_profiles()
        since, raid = self._since(), self._raid()
        summary = stats.summary(since, raid)

        self.k_ok.set_value(messages.fmt_int(summary.ok))
        self.k_avg.set_value(messages.fmt_duration(summary.avg_duration))
        self.k_best.set_value(messages.fmt_duration(summary.best_duration))
        self.k_rate_h.set_value(_num(summary.per_hour))
        self.k_cycle.set_value(messages.fmt_duration(summary.avg_cycle))
        self.k_fail.set_value(messages.fmt_int(summary.failed))
        self.k_fail_dur.set_value(messages.fmt_duration(summary.avg_fail_duration))
        self.k_fail_wave.set_value(_num(summary.avg_fail_wave))
        self.k_success.set_value(_pct(summary.success_rate))
        self.k_record.set_value(str(stats.best_wave(raid) or "–"))
        self.act_purge.setEnabled(stats.failed_count() > 0)

        self._rows = stats.last_runs(100, since, raid)
        self.table.setRowCount(len(self._rows))
        for row, rec in enumerate(self._rows):
            values = [datetime.fromtimestamp(rec.ts_end).strftime("%d.%m. %H:%M:%S"), rec.raid or "–",
                      "✓ erfolgreich" if rec.result == "ok" else "✗ Fehlversuch",
                      messages.fmt_duration_est(rec.duration_s, rec.estimated), messages.fmt_duration(rec.cycle_s),
                      f"{rec.max_wave}/{rec.total_waves}"]
            for col, text in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(text))

        self.chart_hist.set_data(stats.wave_histogram(since, raid))
        by_day = self.range.currentData() in ("7d", "all")
        self.chart_trend.set_data([(label_, int(round(avg))) for label_, avg, _n in stats.trend(since, raid, by_day)])
        self.chart_hour.set_data([(f"{h:02d}", c) for h, c in stats.hourly(10, raid)])

        per = stats.per_raid(since)
        self.per_table.setRowCount(len(per))
        for row, item in enumerate(per):
            values = [item["raid"], str(item["ok"]), str(item["failed"]), messages.fmt_duration(item["avg"]),
                      messages.fmt_duration(item["avg_fail"]), messages.fmt_duration(item["best"]),
                      str(item["best_wave"]), _num(item["avg_wave"])]
            for col, text in enumerate(values):
                self.per_table.setItem(row, col, QTableWidgetItem(text))

    def load(self, settings) -> None:
        pass

    def apply(self, settings) -> None:
        pass
