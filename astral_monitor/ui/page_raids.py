"""Seite „Raids": Profile mit Referenzbildern für die Raid-Erkennung."""
from __future__ import annotations

import cv2
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from pathlib import Path

from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..engine import EngineError
from ..i18n import tr
from . import theme
from ..profiles import PACK_SUFFIX, PROFILE_SUFFIX
from ..settings import DEFAULT_SCENE_ROI, Roi
from .region_dialog import RegionDialog
from .widgets import SpinBox, Card, bgr_to_pixmap, label, smooth


class RaidsPage(QWidget):
    SAVES = True                                   # Speichern-Leiste unten (main_window)

    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.engine = main.engine
        self.store = main.engine.profile_store
        self.scene_roi = Roi(**vars(DEFAULT_SCENE_ROI))

        root = QVBoxLayout(self)
        theme.track_margins(root, 28, 24, 28, 24)
        theme.track_spacing(root, 14)
        root.addWidget(label(tr("Raids"), "h1"))
        root.addWidget(label(tr("Das Programm erkennt beim Raid-Start anhand von Referenzbildern, welcher Raid läuft. "
                             "Name und Statistik erscheinen dann in Verlauf und Discord."), "muted", wrap=True))

        body = QHBoxLayout()
        theme.track_spacing(body, 14)

        left = Card(tr("Meine Raids"))
        self.profiles = QListWidget()
        smooth(self.profiles)
        self.profiles.currentRowChanged.connect(lambda _row: self._refresh_images())
        left.body.addWidget(self.profiles)          # höchstens 8 Zeilen hoch (siehe _fit_list), Knöpfe direkt darunter
        theme.track(self.profiles, lambda _o, _f: self._fit_list())
        row = QHBoxLayout()
        add = QPushButton(tr("Neu …"))
        add.clicked.connect(self._new_profile)
        delete = QPushButton(tr("Löschen"))
        delete.clicked.connect(self._delete_profile)
        row.addWidget(add)
        row.addWidget(delete)
        left.body.addLayout(row)
        share = QHBoxLayout()
        export = QPushButton(tr("Exportieren …"))
        export.setToolTip(tr("Profil mit Referenzbildern als Datei speichern, um es mit Freunden zu teilen"))
        export.clicked.connect(self._export)
        imp = QPushButton(tr("Importieren …"))
        imp.clicked.connect(self._import)
        share.addWidget(export)
        share.addWidget(imp)
        left.body.addLayout(share)
        export_all = QPushButton(tr("Alle exportieren …"))
        export_all.setToolTip(tr("Alle Raids mit Referenzbildern als eine Datei (.astralpack) – für Freunde"))
        export_all.clicked.connect(self._export_all)
        left.body.addWidget(export_all)
        left.body.addWidget(label(tr("Ein Paket (.astralpack) enthält alle Raids – Freunde importieren es einmal. "
                                  "Raids, die schon vorhanden sind, werden dabei übersprungen."), "small", wrap=True))
        body.addWidget(left, 2, Qt.AlignmentFlag.AlignTop)   # nicht auf die Höhe der rechten Spalte strecken

        right_col = QVBoxLayout()
        theme.track_spacing(right_col, 14)
        refs = Card(tr("Referenzbilder"))
        refs.body.addWidget(label(tr("Starte den Raid, warte bis „Wave“ sichtbar ist und nimm 3 bis 5 Bilder auf "
                                  "(am besten zu verschiedenen Zeitpunkten). Verglichen wird nur die Umgebung – die "
                                  "eigene Armee in der Bildmitte und alles, was in jedem Raid gleich aussieht, wird "
                                  "ignoriert. Pro Raid nur ein Profil anlegen."), "small", wrap=True))
        self.images = QListWidget()
        self.images.setViewMode(QListWidget.ViewMode.IconMode)
        theme.track(self.images, lambda o, f: (o.setIconSize(QSize(round(160 * f), round(90 * f))),
                                               o.setGridSize(QSize(round(172 * f), round(124 * f)))))
        self.images.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.images.setMovement(QListWidget.Movement.Static)
        self.images.setWrapping(True)
        theme.track_spacing(self.images, 8)
        self.images.setUniformItemSizes(True)
        self.images.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        theme.track_min_height(self.images, 280)            # zwei Bildreihen ohne Scrollen
        smooth(self.images)
        refs.body.addWidget(self.images, 1)
        row2 = QHBoxLayout()
        capture = QPushButton(tr("Referenzbild aufnehmen"))
        capture.setObjectName("primary")
        capture.clicked.connect(self._capture)
        remove = QPushButton(tr("Bild löschen"))
        remove.clicked.connect(self._remove_image)
        row2.addWidget(capture)
        row2.addWidget(remove)
        row2.addStretch(1)
        refs.body.addLayout(row2)
        right_col.addWidget(refs, 0)

        prof = Card(tr("Profil-Einstellungen"))
        prow = QHBoxLayout()
        prow.addWidget(label(tr("Auslöser: Gesamt minus")))
        self.p_trigger = SpinBox()
        self.p_trigger.setRange(-1, 5)
        self.p_trigger.setSpecialValueText(tr("wie global"))
        prow.addWidget(self.p_trigger)
        prow.addStretch(1)
        prof.body.addLayout(prow)
        nrow = QHBoxLayout()                       # eigene Zeile, sonst wird die Seite bei kleinem Fenster zu breit
        nrow.addWidget(label(tr("Notiz")))
        self.p_note = QLineEdit()
        self.p_note.setPlaceholderText(tr("z. B. „Boss bei Welle 27“"))
        nrow.addWidget(self.p_note, 1)
        save_p = QPushButton(tr("Übernehmen"))
        save_p.clicked.connect(self._save_profile_settings)
        nrow.addWidget(save_p)
        prof.body.addLayout(nrow)
        prof.body.addWidget(label(tr("Gilt nur für dieses Profil. Die Statistik wird automatisch je Profil geführt."),
                                  "small", wrap=True))
        right_col.addWidget(prof, 0)

        test = Card(tr("Erkennung testen"))
        trow = QHBoxLayout()
        run = QPushButton(tr("Jetzt testen"))
        run.clicked.connect(self._test)
        trow.addWidget(run)
        trow.addStretch(1)
        test.body.addLayout(trow)
        self.result = label(tr("Prüft das aktuelle Roblox-Bild und zeigt, welcher Raid erkannt wird."), "small",
                            wrap=True)
        test.body.addWidget(self.result)
        self.preview = label("", "preview")
        self.preview.setVisible(False)
        test.body.addWidget(self.preview)
        right_col.addWidget(test, 0)
        right_col.addStretch(1)

        area = Card(tr("Bildbereich für den Vergleich"))
        arow = QHBoxLayout()
        self.lbl_roi = label("", wrap=True)        # umbrechen, sonst wird die Seite bei kleinem Fenster zu breit
        arow.addWidget(self.lbl_roi, 1)
        pick = QPushButton(tr("Bereich ändern …"))
        pick.clicked.connect(self._pick_roi)
        reset = QPushButton(tr("Standard"))
        reset.clicked.connect(self._reset_roi)
        arow.addWidget(pick)
        arow.addWidget(reset)
        area.body.addLayout(arow)
        area.body.addWidget(label(tr("Standard: die Mitte ohne Menüs, Leisten und Quest-Liste. Nach Änderung die "
                                  "Referenzbilder neu aufnehmen."), "small", wrap=True))
        irow = QHBoxLayout()
        irow.addWidget(label(tr("Mindest-Übereinstimmung")))
        self.min_inliers = SpinBox()
        self.min_inliers.setRange(1, 200)
        self.min_inliers.setToolTip(tr("Wie viele Bildmerkmale mindestens passen müssen. Höher = strenger, "
                                       "niedriger = erkennt auch bei kleinen Änderungen."))
        irow.addWidget(self.min_inliers)
        irow.addStretch(1)
        area.body.addLayout(irow)
        right_col.addWidget(area, 0)
        body.addLayout(right_col, 5)
        root.addLayout(body, 1)
        self._refresh_profiles()

    # ------------------------------------------------------------------ Einstellungen
    def load(self, s) -> None:
        self.scene_roi = s.scene_roi
        self.min_inliers.setValue(s.profile_min_inliers)
        self._refresh_roi_label()

    def apply(self, s) -> None:
        s.scene_roi = self.scene_roi
        s.profile_min_inliers = self.min_inliers.value()

    def refresh(self) -> None:
        pass

    def _refresh_roi_label(self) -> None:
        r = self.scene_roi
        self.lbl_roi.setText(tr("x {x0}–{x1}, y {y0}–{y1} des Fensters", x0=f"{r.x0:.0%}", x1=f"{r.x1:.0%}", y0=f"{r.y0:.0%}", y1=f"{r.y1:.0%}"))

    # ------------------------------------------------------------------ Profile
    def _current(self) -> str:
        item = self.profiles.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    VISIBLE_RAIDS = 8                              # so viele Raids ohne Scrollen, darüber scrollt die Liste

    def _fit_list(self) -> None:
        """Liste so hoch wie ihre Einträge, höchstens VISIBLE_RAIDS Zeilen."""
        rows = max(1, min(self.profiles.count(), self.VISIBLE_RAIDS))
        frame = self.profiles.frameWidth() * 2 + theme.px(4)
        span = 0
        if self.profiles.count():                  # echter Abstand erste bis letzte sichtbare Zeile (inkl. Trennlinien)
            first = self.profiles.visualItemRect(self.profiles.item(0))
            last = self.profiles.visualItemRect(self.profiles.item(rows - 1))
            span = last.bottom() - first.top() + 1 if last.height() > 0 else 0
        if span <= 0:                              # noch nicht gezeichnet: geschätzt
            span = rows * (self.profiles.sizeHintForRow(0) + 1 if self.profiles.count() else theme.px(44))
        self.profiles.setFixedHeight(max(theme.px(120), span + frame))   # fest: sonst gilt die Standardhöhe

    def _refresh_profiles(self, select: str = "") -> None:
        keep = select or self._current()
        self.profiles.blockSignals(True)
        self.profiles.clear()
        for name in self.store.names():
            item = QListWidgetItem(tr("{name}   ({count} Bilder)", name=name, count=len(self.store.images(name))))
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.profiles.addItem(item)
            if name == keep:
                self.profiles.setCurrentItem(item)
        if self.profiles.currentItem() is None and self.profiles.count():
            self.profiles.setCurrentRow(0)
        self.profiles.blockSignals(False)
        self._fit_list()
        QTimer.singleShot(0, self._fit_list)        # nach dem Zeichnen mit der echten Zeilenhöhe nachmessen

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_list)
        self._refresh_images()

    def _refresh_images(self) -> None:
        self.images.clear()
        name = self._current()
        self._load_profile_settings(name)
        if not name:
            return
        for path in self.store.images(name):
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                continue
            item = QListWidgetItem(QIcon(bgr_to_pixmap(img, 160)), tr("Bild {n}", n=path.stem.replace("ref_", "")))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.images.addItem(item)

    def _load_profile_settings(self, name: str) -> None:
        data = self.store.settings(name) if name else {}
        trigger = data.get("trigger_offset")
        self.p_trigger.setValue(trigger if isinstance(trigger, int) else -1)
        self.p_note.setText(str(data.get("note", "")))

    def _save_profile_settings(self) -> None:
        name = self._current()
        if not name:
            return
        data = {"note": self.p_note.text().strip()}
        if self.p_trigger.value() >= 0:
            data["trigger_offset"] = self.p_trigger.value()
        self.store.save_settings(name, data)
        self.main.show_toast(tr("Profil-Einstellungen gespeichert ✓"))

    def _export(self) -> None:
        name = self._current()
        if not name:
            QMessageBox.information(self, tr("Exportieren"), tr("Bitte zuerst ein Profil auswählen."))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Profil exportieren"), str(Path.home() / f"{name}{PROFILE_SUFFIX}"),
                                              tr("Astral-Profil") + f" (*{PROFILE_SUFFIX})")
        if not path:
            return
        try:
            target = self.store.export_zip(name, Path(path))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr("Exportieren"), str(exc))
            return
        self.main.show_toast(tr("Exportiert: {name} ✓", name=target.name))

    def _export_all(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("Alle Raids exportieren"),
                                              str(Path.home() / f"Anime-Astral-Raids{PACK_SUFFIX}"),
                                              tr("Astral-Paket") + f" (*{PACK_SUFFIX})")
        if not path:
            return
        try:
            target, count = self.store.export_pack(Path(path))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr("Exportieren"), str(exc))
            return
        self.main.show_toast(tr("{count} Raids exportiert: {name} ✓", count=count, name=target.name))

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Profil oder Paket importieren"), str(Path.home()),
            tr("Astral-Profil oder -Paket") + f" (*{PROFILE_SUFFIX} *{PACK_SUFFIX});;" + tr("Alle Dateien") + " (*)")
        if not path:
            return
        try:
            if Path(path).suffix.lower() == PACK_SUFFIX:
                imported, skipped = self.store.import_pack(Path(path))
            else:
                imported, skipped = [self.store.import_zip(Path(path))], []
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr("Importieren"), str(exc))
            return
        self.engine.reload_profiles()
        self._refresh_profiles(select=imported[0] if imported else None)
        text = (tr("Importiert: {names}.", names=", ".join(imported)) if imported else tr("Nichts Neues importiert."))
        if skipped:
            text += "\n\n" + tr("Übersprungen (schon vorhanden oder fehlerhaft): {names}.", names=", ".join(skipped))
        QMessageBox.information(self, tr("Importieren"), text + "\n\n" + tr("Mit „Jetzt testen“ prüfst du, ob dein Raid erkannt wird."))

    def _new_profile(self) -> None:
        text, ok = QInputDialog.getText(self, tr("Neues Profil"), tr("Name des Raids (z. B. MaxTac Call):"))
        if not ok:
            return
        try:
            name = self.store.create(text)
        except ValueError as exc:
            QMessageBox.warning(self, tr("Profil"), str(exc))
            return
        self._refresh_profiles(select=name)

    def _delete_profile(self) -> None:
        name = self._current()
        if not name:
            return
        if QMessageBox.question(self, tr("Profil löschen"), tr("Profil „{name}“ samt Referenzbildern löschen?", name=name)) \
                == QMessageBox.StandardButton.Yes:
            self.store.delete(name)
            self.engine.reload_profiles()
            self._refresh_profiles()

    # ------------------------------------------------------------------ Bilder
    def _capture(self) -> None:
        name = self._current()
        if not name:
            QMessageBox.information(self, tr("Referenzbild"), tr("Lege zuerst ein Profil an („Neu …“)."))
            return
        self.main.apply_form()
        try:
            path = self.engine.capture_reference(name)
        except EngineError as exc:
            QMessageBox.warning(self, tr("Aufnahme"), str(exc))
            return
        if path is None:
            QMessageBox.warning(self, tr("Aufnahme"), tr("Kein Bild vom Roblox-Fenster erhalten."))
            return
        self.engine.reload_profiles()
        self._refresh_profiles(select=name)
        self.main.show_toast(tr("Referenzbild gespeichert ✓"))

    def _remove_image(self) -> None:
        item = self.images.currentItem()
        if item is None:
            return
        self.store.remove_image(Path(item.data(Qt.ItemDataRole.UserRole)))
        self.engine.reload_profiles()
        self._refresh_profiles()

    def _test(self) -> None:
        self.main.apply_form()
        try:
            result = self.engine.test_scene()
        except EngineError as exc:
            QMessageBox.warning(self, tr("Test"), str(exc))
            return
        if not result["ok"]:
            self.result.setText(result["error"])
            return
        ranked = sorted(result["scores"].items(), key=lambda kv: kv[1], reverse=True)
        lines = [f"{'✅' if name == result['decision'] else '•'} {name}: {score}" for name, score in ranked]
        verdict = (tr("Erkannt: {name}", name=result["decision"]) if result["decision"]
                   else tr("Kein eindeutiger Treffer (zu wenig oder zu ähnliche Übereinstimmung)"))
        if result.get("warnings"):
            lines.append(tr("⚠️ Fast gleich wie ein anderes Profil (derselbe Raid doppelt angelegt?): {names} – "
                            "doppeltes Profil löschen.", names=", ".join(result["warnings"])))
        self.result.setText(f"{verdict}  ({result['ms']:.0f} ms)\n" + "\n".join(lines))
        self.preview.setPixmap(bgr_to_pixmap(result["crop"], 420))
        self.preview.setVisible(True)

    # ------------------------------------------------------------------ Bereich
    def _pick_roi(self) -> None:
        self.main.apply_form()
        try:
            res = self.engine.grab_for_ui(full=True)
        except EngineError as exc:
            QMessageBox.warning(self, tr("Aufnahme"), str(exc))
            return
        if res is None or res.full is None:
            QMessageBox.warning(self, tr("Aufnahme"), tr("Kein Bild vom Roblox-Fenster erhalten."))
            return
        dialog = RegionDialog(self, res.full, tr("Bildbereich auswählen"),
                              tr("Wähle die Kulisse (Gebäude, Boden), aber ohne Menüs, Leisten und Quest-Liste."),
                              self.scene_roi)
        if dialog.exec() and dialog.roi():
            self.scene_roi = dialog.roi()
            self._refresh_roi_label()

    def _reset_roi(self) -> None:
        self.scene_roi = Roi(**vars(DEFAULT_SCENE_ROI))
        self._refresh_roi_label()
