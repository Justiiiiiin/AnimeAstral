"""Seite „Raids": Profile mit Referenzbildern für die Raid-Erkennung."""
from __future__ import annotations

import cv2
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from pathlib import Path

from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..engine import EngineError
from ..profiles import PROFILE_SUFFIX
from ..settings import DEFAULT_SCENE_ROI, Roi
from .region_dialog import RegionDialog
from .widgets import SpinBox, Card, bgr_to_pixmap, label, smooth


class RaidsPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.engine = main.engine
        self.store = main.engine.profile_store
        self.scene_roi = Roi(**vars(DEFAULT_SCENE_ROI))

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(label("Raids", "h1"))
        root.addWidget(label("Das Programm erkennt beim Raid-Start anhand von Referenzbildern, welcher Raid läuft. "
                             "Name und Statistik erscheinen dann in Verlauf und Discord.", "muted", wrap=True))

        body = QHBoxLayout()
        body.setSpacing(14)

        left = Card("Meine Raids")
        self.profiles = QListWidget()
        self.profiles.setMinimumHeight(170)
        smooth(self.profiles)
        self.profiles.currentRowChanged.connect(lambda _row: self._refresh_images())
        left.body.addWidget(self.profiles, 1)
        row = QHBoxLayout()
        add = QPushButton("Neu …")
        add.clicked.connect(self._new_profile)
        delete = QPushButton("Löschen")
        delete.clicked.connect(self._delete_profile)
        row.addWidget(add)
        row.addWidget(delete)
        left.body.addLayout(row)
        share = QHBoxLayout()
        export = QPushButton("Exportieren …")
        export.setToolTip("Profil mit Referenzbildern als Datei speichern, um es mit Freunden zu teilen")
        export.clicked.connect(self._export)
        imp = QPushButton("Importieren …")
        imp.clicked.connect(self._import)
        share.addWidget(export)
        share.addWidget(imp)
        left.body.addLayout(share)
        left.body.addWidget(label("Profil-Dateien (.astralprofile) kannst du mit Freunden teilen.", "small", wrap=True))
        body.addWidget(left, 2)

        right_col = QVBoxLayout()
        right_col.setSpacing(14)
        refs = Card("Referenzbilder")
        refs.body.addWidget(label("Starte den Raid, warte bis „Wave“ sichtbar ist und nimm 3 bis 5 Bilder auf "
                                  "(am besten zu verschiedenen Zeitpunkten). Verglichen wird nur die Umgebung – die "
                                  "eigene Armee in der Bildmitte und alles, was in jedem Raid gleich aussieht, wird "
                                  "ignoriert. Pro Raid nur ein Profil anlegen.", "small", wrap=True))
        self.images = QListWidget()
        self.images.setViewMode(QListWidget.ViewMode.IconMode)
        self.images.setIconSize(QSize(176, 100))
        self.images.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.images.setMovement(QListWidget.Movement.Static)
        self.images.setWrapping(True)
        self.images.setSpacing(8)
        self.images.setUniformItemSizes(True)
        self.images.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.images.setMinimumHeight(190)
        smooth(self.images)
        refs.body.addWidget(self.images, 1)
        row2 = QHBoxLayout()
        capture = QPushButton("Referenzbild aufnehmen")
        capture.setObjectName("primary")
        capture.clicked.connect(self._capture)
        remove = QPushButton("Bild löschen")
        remove.clicked.connect(self._remove_image)
        row2.addWidget(capture)
        row2.addWidget(remove)
        row2.addStretch(1)
        refs.body.addLayout(row2)
        right_col.addWidget(refs, 0)

        prof = Card("Profil-Einstellungen")
        prow = QHBoxLayout()
        prow.addWidget(label("Auslöser: Gesamt minus"))
        self.p_trigger = SpinBox()
        self.p_trigger.setRange(-1, 5)
        self.p_trigger.setSpecialValueText("wie global")
        prow.addWidget(self.p_trigger)
        prow.addStretch(1)
        prof.body.addLayout(prow)
        nrow = QHBoxLayout()                       # eigene Zeile, sonst wird die Seite bei kleinem Fenster zu breit
        nrow.addWidget(label("Notiz"))
        self.p_note = QLineEdit()
        self.p_note.setPlaceholderText("z. B. „Boss bei Welle 27“")
        nrow.addWidget(self.p_note, 1)
        save_p = QPushButton("Übernehmen")
        save_p.clicked.connect(self._save_profile_settings)
        nrow.addWidget(save_p)
        prof.body.addLayout(nrow)
        prof.body.addWidget(label("Gilt nur für dieses Profil. Die Statistik wird automatisch je Profil geführt.",
                                  "small", wrap=True))
        right_col.addWidget(prof, 0)

        test = Card("Erkennung testen")
        trow = QHBoxLayout()
        run = QPushButton("Jetzt testen")
        run.clicked.connect(self._test)
        trow.addWidget(run)
        trow.addStretch(1)
        test.body.addLayout(trow)
        self.result = label("", "muted", wrap=True)
        test.body.addWidget(self.result)
        self.preview = label("", "preview")
        self.preview.setVisible(False)
        test.body.addWidget(self.preview)
        right_col.addWidget(test, 0)
        right_col.addStretch(1)

        area = Card("Bildbereich für den Vergleich")
        arow = QHBoxLayout()
        self.lbl_roi = label("", wrap=True)        # umbrechen, sonst wird die Seite bei kleinem Fenster zu breit
        arow.addWidget(self.lbl_roi, 1)
        pick = QPushButton("Bereich ändern …")
        pick.clicked.connect(self._pick_roi)
        reset = QPushButton("Standard")
        reset.clicked.connect(self._reset_roi)
        arow.addWidget(pick)
        arow.addWidget(reset)
        area.body.addLayout(arow)
        area.body.addWidget(label("Standard: die Mitte ohne Menüs, Leisten und Quest-Liste. Nach Änderung die "
                                  "Referenzbilder neu aufnehmen.", "small", wrap=True))
        irow = QHBoxLayout()
        irow.addWidget(label("Mindest-Übereinstimmung"))
        self.min_inliers = SpinBox()
        self.min_inliers.setRange(1, 200)
        irow.addWidget(self.min_inliers)
        irow.addStretch(1)
        area.body.addLayout(irow)
        right_col.addWidget(area, 0)
        body.addLayout(right_col, 5)
        root.addLayout(body, 1)

        save = QPushButton("Speichern")
        save.setObjectName("primary")
        save.clicked.connect(lambda: self.main.save_settings())
        srow = QHBoxLayout()
        srow.addStretch(1)
        srow.addWidget(save)
        root.addLayout(srow)
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
        self.lbl_roi.setText(f"x {r.x0:.0%}–{r.x1:.0%}, y {r.y0:.0%}–{r.y1:.0%} des Fensters")

    # ------------------------------------------------------------------ Profile
    def _current(self) -> str:
        item = self.profiles.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def _refresh_profiles(self, select: str = "") -> None:
        keep = select or self._current()
        self.profiles.blockSignals(True)
        self.profiles.clear()
        for name in self.store.names():
            item = QListWidgetItem(f"{name}   ({len(self.store.images(name))} Bilder)")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.profiles.addItem(item)
            if name == keep:
                self.profiles.setCurrentItem(item)
        if self.profiles.currentItem() is None and self.profiles.count():
            self.profiles.setCurrentRow(0)
        self.profiles.blockSignals(False)
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
            item = QListWidgetItem(QIcon(bgr_to_pixmap(img, 176)), path.stem.replace("ref_", "Bild "))
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
        self.main.show_toast("Profil-Einstellungen gespeichert ✓")

    def _export(self) -> None:
        name = self._current()
        if not name:
            QMessageBox.information(self, "Exportieren", "Bitte zuerst ein Profil auswählen.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Profil exportieren", str(Path.home() / f"{name}{PROFILE_SUFFIX}"),
                                              f"Astral-Profil (*{PROFILE_SUFFIX})")
        if not path:
            return
        try:
            target = self.store.export_zip(name, Path(path))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Exportieren", str(exc))
            return
        self.main.show_toast(f"Exportiert: {target.name} ✓")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Profil importieren", str(Path.home()),
                                              f"Astral-Profil (*{PROFILE_SUFFIX});;Alle Dateien (*)")
        if not path:
            return
        try:
            name = self.store.import_zip(Path(path))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Importieren", str(exc))
            return
        self.engine.reload_profiles()
        self._refresh_profiles(select=name)
        QMessageBox.information(self, "Importieren", f"Profil „{name}“ importiert. Mit „Jetzt testen“ prüfst du, ob es in "
                                                     "deinem Spiel erkannt wird.")

    def _new_profile(self) -> None:
        text, ok = QInputDialog.getText(self, "Neues Profil", "Name des Raids (z. B. MaxTac Call):")
        if not ok:
            return
        try:
            name = self.store.create(text)
        except ValueError as exc:
            QMessageBox.warning(self, "Profil", str(exc))
            return
        self._refresh_profiles(select=name)

    def _delete_profile(self) -> None:
        name = self._current()
        if not name:
            return
        if QMessageBox.question(self, "Profil löschen", f"Profil „{name}“ samt Referenzbildern löschen?") \
                == QMessageBox.StandardButton.Yes:
            self.store.delete(name)
            self.engine.reload_profiles()
            self._refresh_profiles()

    # ------------------------------------------------------------------ Bilder
    def _capture(self) -> None:
        name = self._current()
        if not name:
            QMessageBox.information(self, "Referenzbild", "Lege zuerst ein Profil an („Neu …“).")
            return
        self.main.apply_form()
        try:
            path = self.engine.capture_reference(name)
        except EngineError as exc:
            QMessageBox.warning(self, "Aufnahme", str(exc))
            return
        if path is None:
            QMessageBox.warning(self, "Aufnahme", "Kein Bild vom Roblox-Fenster erhalten.")
            return
        self.engine.reload_profiles()
        self._refresh_profiles(select=name)
        self.main.show_toast("Referenzbild gespeichert ✓")

    def _remove_image(self) -> None:
        item = self.images.currentItem()
        if item is None:
            return
        from pathlib import Path
        self.store.remove_image(Path(item.data(Qt.ItemDataRole.UserRole)))
        self.engine.reload_profiles()
        self._refresh_profiles()

    def _test(self) -> None:
        self.main.apply_form()
        try:
            result = self.engine.test_scene()
        except EngineError as exc:
            QMessageBox.warning(self, "Test", str(exc))
            return
        if not result["ok"]:
            self.result.setText(result["error"])
            return
        ranked = sorted(result["scores"].items(), key=lambda kv: kv[1], reverse=True)
        lines = [f"{'✅' if name == result['decision'] else '•'} {name}: {score}" for name, score in ranked]
        verdict = (f"Erkannt: {result['decision']}" if result["decision"]
                   else "Kein eindeutiger Treffer (zu wenig oder zu ähnliche Übereinstimmung)")
        if result.get("warnings"):
            lines.append("⚠️ Fast gleich wie ein anderes Profil (derselbe Raid doppelt angelegt?): "
                         + ", ".join(result["warnings"]) + " – doppeltes Profil löschen.")
        self.result.setText(f"{verdict}  ({result['ms']:.0f} ms)\n" + "\n".join(lines))
        self.preview.setPixmap(bgr_to_pixmap(result["crop"], 420))
        self.preview.setVisible(True)

    # ------------------------------------------------------------------ Bereich
    def _pick_roi(self) -> None:
        self.main.apply_form()
        try:
            res = self.engine.grab_for_ui(full=True)
        except EngineError as exc:
            QMessageBox.warning(self, "Aufnahme", str(exc))
            return
        if res is None or res.full is None:
            QMessageBox.warning(self, "Aufnahme", "Kein Bild vom Roblox-Fenster erhalten.")
            return
        dialog = RegionDialog(self, res.full, "Bildbereich auswählen",
                              "Wähle die Kulisse (Gebäude, Boden), aber ohne Menüs, Leisten und Quest-Liste.",
                              self.scene_roi)
        if dialog.exec() and dialog.roi():
            self.scene_roi = dialog.roi()
            self._refresh_roi_label()

    def _reset_roi(self) -> None:
        self.scene_roi = Roi(**vars(DEFAULT_SCENE_ROI))
        self._refresh_roi_label()
