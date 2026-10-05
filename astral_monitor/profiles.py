"""Raid-Erkennung: Referenzbilder je Raid-Profil + Merkmalsvergleich (ORB) mit RANSAC."""
from __future__ import annotations

import json
import logging
import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger("profiles")

WORK_WIDTH = 640           # Vergleichsbreite (klein = schnell)
RATIO = 0.75               # Lowe-Verhältnis für gute Treffer
MARGIN = 1.5               # bester Raid muss so viel besser sein als der zweitbeste
MIN_KEYPOINTS = 15
PROFILE_FORMAT = "astral-profile-1"
PROFILE_SUFFIX = ".astralprofile"
MAX_IMPORT_IMAGES = 30
MAX_IMPORT_IMAGE_BYTES = 4 * 1024 * 1024


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^\w \-]", "", name, flags=re.UNICODE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)[:40]
    if not cleaned:
        raise ValueError("Bitte einen Namen aus Buchstaben oder Ziffern eingeben.")
    return cleaned


def prepare(bgr: np.ndarray) -> np.ndarray:
    """Graubild in Arbeitsgröße mit lokalem Kontrastausgleich (robust gegen Helligkeit)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    if w != WORK_WIDTH:
        gray = cv2.resize(gray, (WORK_WIDTH, max(1, int(h * WORK_WIDTH / w))), interpolation=cv2.INTER_AREA)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


class ProfileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def names(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def images(self, name: str) -> list[Path]:
        return sorted((self.root / name).glob("ref_*.jpg"))

    def create(self, name: str) -> str:
        clean = sanitize_name(name)
        (self.root / clean).mkdir(exist_ok=True)
        return clean

    def delete(self, name: str) -> None:
        folder = self.root / sanitize_name(name)
        if folder.is_dir():
            shutil.rmtree(folder)

    def add_image(self, name: str, scene_bgr: np.ndarray) -> Path:
        folder = self.root / sanitize_name(name)
        folder.mkdir(exist_ok=True)
        existing = [int(m.group(1)) for p in folder.glob("ref_*.jpg")
                    if (m := re.match(r"ref_(\d+)", p.stem))]
        path = folder / f"ref_{(max(existing) + 1 if existing else 1):02d}.jpg"
        h, w = scene_bgr.shape[:2]
        if w > WORK_WIDTH * 2:                       # Referenzen klein halten
            scene_bgr = cv2.resize(scene_bgr, (WORK_WIDTH * 2, int(h * WORK_WIDTH * 2 / w)),
                                   interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(path), scene_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return path

    def remove_image(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    # ------------------------------------------------------- Einstellungen je Profil
    def settings(self, name: str) -> dict:
        try:
            data = json.loads((self.root / sanitize_name(name) / "profile.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self, name: str, data: dict) -> None:
        folder = self.root / sanitize_name(name)
        folder.mkdir(exist_ok=True)
        (folder / "profile.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------ Teilen (Export/Import)
    def export_zip(self, name: str, dest: Path) -> Path:
        """Packt Referenzbilder und Profil-Einstellungen in eine Datei zum Weitergeben."""
        clean = sanitize_name(name)
        images = self.images(clean)
        if not images:
            raise ValueError("Das Profil hat noch keine Referenzbilder.")
        meta = {"format": PROFILE_FORMAT, "name": clean, **{k: v for k, v in self.settings(clean).items()
                                                            if k in ("trigger_offset", "note")}}
        dest = dest.with_suffix(PROFILE_SUFFIX) if dest.suffix.lower() != PROFILE_SUFFIX else dest
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("profile.json", json.dumps(meta, indent=2, ensure_ascii=False))
            for path in images:
                zf.write(path, path.name)
        return dest

    def import_zip(self, src: Path) -> str:
        """Liest eine Profil-Datei (mit Prüfungen) und gibt den Namen des neuen Profils zurück."""
        try:
            zf = zipfile.ZipFile(src)
        except zipfile.BadZipFile as exc:
            raise ValueError("Das ist keine gültige Profil-Datei.") from exc
        with zf:
            names = {Path(n).name: n for n in zf.namelist() if not n.endswith("/")}
            try:
                meta = json.loads(zf.read(names["profile.json"]).decode("utf-8"))
            except (KeyError, ValueError) as exc:
                raise ValueError("Die Profil-Datei ist unvollständig (profile.json fehlt).") from exc
            if meta.get("format") != PROFILE_FORMAT:
                raise ValueError("Unbekanntes Dateiformat (nicht von diesem Programm erstellt).")
            images = sorted(n for n in names if re.fullmatch(r"ref_\d+\.jpg", n))
            if not images or len(images) > MAX_IMPORT_IMAGES:
                raise ValueError(f"Die Datei muss 1 bis {MAX_IMPORT_IMAGES} Referenzbilder enthalten.")
            base = sanitize_name(str(meta.get("name", "Importiert")))
            name, i = base, 2
            while (self.root / name).exists():
                name, i = f"{base} {i}", i + 1             # ohne Klammern: bleibt ein gültiger Profilname
            folder = self.root / name
            folder.mkdir()
            try:
                for img in images:
                    info = zf.getinfo(names[img])
                    if info.file_size > MAX_IMPORT_IMAGE_BYTES:
                        raise ValueError("Ein Bild in der Datei ist zu groß.")
                    data = zf.read(names[img])
                    if cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) is None:
                        raise ValueError("Ein Bild in der Datei ist beschädigt.")
                    (folder / img).write_bytes(data)
                settings = {k: meta[k] for k in ("trigger_offset", "note") if k in meta}
                if settings:
                    self.save_settings(name, settings)
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                raise
        return name


class RaidMatcher:
    def __init__(self, store: ProfileStore, min_inliers: int = 14) -> None:
        self.store = store
        self.min_inliers = min_inliers
        self._orb = cv2.ORB_create(nfeatures=1000, fastThreshold=10)
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._refs: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
        self.reload()

    def reload(self) -> None:
        new_refs: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
        for name in self.store.names():
            entries = []
            for path in self.store.images(name):
                img = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if img is None:
                    continue
                feat = self._features(prepare(img))
                if feat is not None:
                    entries.append(feat)
            if entries:
                new_refs[name] = entries
        self._refs = new_refs                      # atomar austauschen (Überwachung läuft parallel)

    @property
    def has_profiles(self) -> bool:
        return bool(self._refs)

    def _features(self, gray: np.ndarray):
        kps, desc = self._orb.detectAndCompute(gray, None)
        if desc is None or len(kps) < MIN_KEYPOINTS:
            return None
        return np.float32([k.pt for k in kps]), desc

    def _inliers(self, feat, ref) -> int:
        pts, desc = feat
        rpts, rdesc = ref
        pairs = self._bf.knnMatch(desc, rdesc, k=2)
        good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < RATIO * p[1].distance]
        if len(good) < 8:
            return len(good) // 2
        src = pts[[m.queryIdx for m in good]].reshape(-1, 1, 2)
        dst = rpts[[m.trainIdx for m in good]].reshape(-1, 1, 2)
        matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        return int(mask.sum()) if mask is not None else 0

    def score(self, scene_bgr: np.ndarray) -> dict[str, int]:
        """Beste Übereinstimmung (RANSAC-Treffer) je Profil."""
        feat = self._features(prepare(scene_bgr))
        if feat is None:
            return {}
        refs_by_name = self._refs
        return {name: max(self._inliers(feat, ref) for ref in refs) for name, refs in refs_by_name.items()}

    def decide(self, scores: dict[str, int]) -> Optional[str]:
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_name, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        if best >= self.min_inliers and best >= MARGIN * max(second, 1):
            return best_name
        return None
