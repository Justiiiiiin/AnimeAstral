"""Bilderkennung für die Automatik (ohne Qt): Welt-Zeilen im Teleporter finden und ihren Namen lesen, offenes
Menü erkennen (rosa X oben rechts + Titel im Banner), Sonder-Menüs nach Vorlage (Pets-Roll) erkennen.
Verfahren und Schwellen stammen aus dem Entwickler-Werkzeug und sind an echten Aufnahmen gemessen (07.10.2026)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .uimap import UiMap

ROW_HIT = 0.85        # Herz-Merkmal links oben in jeder Zeile: echte Zeilen 0,98–1,0, anderes ≤ 0,6
BOTTOM_HIT = 0.60     # unterer Zeilenrand vorhanden (sonst am Listenrand abgeschnitten)
X_HIT = 0.85          # inneres X eines Menüs: andere Menüs 0,96, Teleporter 1,0
MARKER_HIT = 0.80     # Erkennungsmerkmal eines Sonder-Menüs
BAND = (0.03, 0.55, 0.22)   # Titel-Banner im Menürahmen: x von, x bis, y bis


def _scaled(img: np.ndarray, f: float) -> np.ndarray:
    return img if abs(f - 1) < 0.01 else cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)


@dataclass
class Row:
    roi: list[float]                      # Lage im Roblox-Fenster
    image: np.ndarray


class RowFinder:
    """Welt-Zeilen einer Liste am immer gleichen Herz oben links finden (Größe aus der Vorlage-Zeile)."""

    def __init__(self, row: dict, image: np.ndarray) -> None:
        h, w = image.shape[:2]
        self.size = (w, h)
        self.window_w = (row.get("window") or [w])[0]
        self.marker_off = (0.01, 0.05)
        self.marker = image[int(0.05 * h):int(0.45 * h), int(0.01 * w):int(0.07 * w)]
        self.bottom = image[int(0.86 * h):, :int(0.10 * w)]

    def find(self, frame: np.ndarray, area: list[float]) -> list[Row]:
        fh, fw = frame.shape[:2]
        f = fw / self.window_w
        marker = _scaled(self.marker, f)
        rw, rh = int(self.size[0] * f), int(self.size[1] * f)
        ax0, ay0, ax1, ay1 = int(area[0] * fw), int(area[1] * fh), int(area[2] * fw), int(area[3] * fh)
        region = frame[ay0:ay1, ax0:ax1]
        if region.shape[0] < marker.shape[0] or region.shape[1] < marker.shape[1]:
            return []
        res = cv2.matchTemplate(region, marker, cv2.TM_CCOEFF_NORMED)
        out: list[Row] = []
        while True:
            _mn, score, _ml, (mx, my) = cv2.minMaxLoc(res)
            if score < ROW_HIT:
                break
            res[max(0, my - rh // 2):my + rh // 2, :] = -1
            x = ax0 + mx - int(self.marker_off[0] * rw)
            y = ay0 + my - int(self.marker_off[1] * rh)
            if y < 0 or y + rh > fh or x < 0 or x + rw > fw:
                continue
            image = frame[y:y + rh, x:x + rw]
            bottom = image[int(0.86 * rh):, :int(0.10 * rw)]
            ref = cv2.resize(self.bottom, (bottom.shape[1], bottom.shape[0]), interpolation=cv2.INTER_AREA)
            if bottom.size == 0 or float(cv2.matchTemplate(bottom, ref, cv2.TM_CCOEFF_NORMED)[0, 0]) < BOTTOM_HIT:
                continue                                  # unten abgeschnitten
            out.append(Row([x / fw, y / fh, (x + rw) / fw, (y + rh) / fh], image))
        return sorted(out, key=lambda r: r.roi[1])


def read_row_name(row_img: np.ndarray, ocr) -> str:
    """Weltname (weiße Schrift oben links neben dem Globus)."""
    h, w = row_img.shape[:2]
    gray = cv2.cvtColor(row_img[int(0.08 * h):int(0.45 * h), int(0.11 * w):int(0.62 * w)], cv2.COLOR_BGR2GRAY)
    _t, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    return re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9!?')]+$", "", ocr.line(binary, psm=7)).strip()


class MenuFrame:
    """Menüs liegen im selben Rahmen wie der Teleporter: offen = rosa X oben rechts gefunden; Titel im Banner."""

    def __init__(self, window: dict, image: np.ndarray, ocr=None) -> None:
        h, w = image.shape[:2]
        cx, cy, r = int(0.9427 * w), int(0.118 * h), int(0.030 * w)
        self.x_tpl = image[cy - r:cy + r, cx - r:cx + r]
        self.roi = window["roi"]
        self.window_w = (window.get("window") or [w])[0]
        x0, y0, x1, y1 = self.roi
        self.x_at = (x0 + (cx - r) / w * (x1 - x0), y0 + (cy - r) / h * (y1 - y0))
        self.x_size = (2 * r / w * (x1 - x0), 2 * r / h * (y1 - y0))
        self.base_title = read_title(image, ocr) if ocr is not None else ""

    def state(self, frame: np.ndarray, ocr) -> Optional[tuple[list[float], str, tuple[float, float]]]:
        """(Lage des Menüs, Titel, Mitte des X) – oder None, wenn kein Menü im Standard-Rahmen offen ist."""
        fh, fw = frame.shape[:2]
        tpl = _scaled(self.x_tpl, fw / self.window_w)
        ex, ey = int(self.x_at[0] * fw), int(self.x_at[1] * fh)
        mx, my = int(0.05 * fw), int(0.06 * fh)
        rx, ry = max(0, ex - mx), max(0, ey - my)
        region = frame[ry:ey + my + tpl.shape[0], rx:ex + mx + tpl.shape[1]]
        if region.shape[0] < tpl.shape[0] or region.shape[1] < tpl.shape[1]:
            return None
        _a, score, _b, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED))
        if score < X_HIT:
            return None
        dx, dy = (rx + lx - ex) / fw, (ry + ly - ey) / fh
        x0, y0, x1, y1 = self.roi
        roi = [min(1.0, max(0.0, v)) for v in (x0 + dx, y0 + dy, x1 + dx, y1 + dy)]
        crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
        x_center = (self.x_at[0] + dx + self.x_size[0] / 2, self.x_at[1] + dy + self.x_size[1] / 2)
        return roi, read_title(crop, ocr), x_center

    def is_base(self, title: str) -> bool:
        return bool(title) and same_title(title, self.base_title)


def read_title(window_img: np.ndarray, ocr) -> str:
    """Titel im schrägen Banner oben links („Teleport“, „Trial Shop“). Weiße Streifen im Banner werden über die
    Buchstabengröße aussortiert, Buchstaben von links nach rechts zur (schrägen) Zeile verkettet."""
    if ocr is None:
        return ""
    h, w = window_img.shape[:2]
    band = window_img[0:int(BAND[2] * h), int(BAND[0] * w):int(BAND[1] * w)]
    if band.size == 0:
        return ""
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    sat = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)[..., 1]
    mask = ((gray > 225) & (sat < 40)).astype(np.uint8) * 255
    n, lab, st, _c = cv2.connectedComponentsWithStats(mask, 8)
    comps = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > 40]
    if not comps:
        return ""
    hmax = max(st[i, cv2.CC_STAT_HEIGHT] for i in comps)
    keep = [i for i in comps if st[i, cv2.CC_STAT_HEIGHT] >= 0.35 * hmax
            and st[i, cv2.CC_STAT_WIDTH] < 2.5 * st[i, cv2.CC_STAT_HEIGHT]]
    mid = {i: st[i, cv2.CC_STAT_TOP] + st[i, cv2.CC_STAT_HEIGHT] / 2 for i in keep}
    chains: list[list[int]] = []
    for i in sorted(keep, key=lambda i: st[i, cv2.CC_STAT_LEFT]):
        left = st[i, cv2.CC_STAT_LEFT]
        fits = [c for c in chains if abs(mid[c[-1]] - mid[i]) < 0.45 * hmax
                and left - (st[c[-1], cv2.CC_STAT_LEFT] + st[c[-1], cv2.CC_STAT_WIDTH]) < 1.6 * hmax]
        if fits:
            max(fits, key=len).append(i)
        else:
            chains.append([i])
    best = max(chains, key=lambda c: sum(st[i, cv2.CC_STAT_AREA] for i in c), default=[])
    if not best:
        return ""
    x0 = min(st[i, cv2.CC_STAT_LEFT] for i in best)
    x1 = max(st[i, cv2.CC_STAT_LEFT] + st[i, cv2.CC_STAT_WIDTH] for i in best)
    y0 = min(st[i, cv2.CC_STAT_TOP] for i in best)
    y1 = max(st[i, cv2.CC_STAT_TOP] + st[i, cv2.CC_STAT_HEIGHT] for i in best)
    crop = 255 - (np.isin(lab, best).astype(np.uint8) * 255)[max(0, y0 - 10):y1 + 10, max(0, x0 - 10):x1 + 10]
    f = 48 / max(1, y1 - y0)
    crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    crop = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    text = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9!?)]+$", "", ocr.line(crop, psm=7)).strip()
    return text[:1].upper() + text[1:]


def same_title(a: str, b: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", a.lower()) == re.sub(r"[^a-z0-9]", "", b.lower())


def similar_title(read: str, name: str) -> bool:
    """Passt ein gelesener Titel („Crafting“) zum Fensternamen („W3 Crafting“)? Großzügig: Lesefehler, Weltnummer."""
    import difflib
    a = re.sub(r"[^a-z0-9]", "", read.lower())
    b = re.sub(r"[^a-z0-9]", "", re.sub(r"^W\d+\s+", "", name).lower())
    return bool(a) and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.75)


class TemplateMenu:
    """Sonder-Menü mit festem Aufbau (Pets-Roll), erkannt am Erkennungsmerkmal an fester Stelle."""

    def __init__(self, window: dict, marker: dict, image: np.ndarray) -> None:
        self.window, self.marker, self.img = window, marker, image
        self.window_w = (marker.get("window") or [image.shape[1]])[0]

    def seen(self, frame: np.ndarray) -> bool:
        fh, fw = frame.shape[:2]
        tpl = _scaled(self.img, fw / self.window_w)
        x0, y0, x1, y1 = self.marker["roi"]
        mx, my = 0.03 * fw, 0.03 * fh
        region = frame[max(0, int(y0 * fh - my)):int(y1 * fh + my), max(0, int(x0 * fw - mx)):int(x1 * fw + mx)]
        if region.shape[0] < tpl.shape[0] or region.shape[1] < tpl.shape[1]:
            return False
        return float(cv2.minMaxLoc(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED))[1]) >= MARKER_HIT


def template_menus(m: UiMap) -> list[TemplateMenu]:
    out = []
    for window, marker in m.templates():
        img = m.image(marker)
        if img is not None:
            out.append(TemplateMenu(window, marker, img))
    return out


def words_in(frame: np.ndarray, roi: list[float], ocr) -> list[tuple[str, list[float]]]:
    """Alle Wörter in einem Bereich mit Lage im Roblox-Fenster (Anteile). Zwei Durchgänge: helle Schrift mit
    Umriss (Knöpfe, Titel) und allgemein (Otsu) – doppelte Funde werden zusammengelegt."""
    if ocr is None:
        return []
    fh, fw = frame.shape[:2]
    x0, y0 = int(roi[0] * fw), int(roi[1] * fh)
    crop = frame[y0:int(roi[3] * fh), x0:int(roi[2] * fw)]
    if crop.size == 0:
        return []
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scale = 1.0 if crop.shape[0] >= 600 else 1.5
    found: list[tuple[str, list[float]]] = []
    for binary in (cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)[1],
                   cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]):
        img = binary if scale == 1.0 else cv2.resize(binary, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        try:
            words = ocr.words(img, psm=11)
        except Exception:  # noqa: BLE001 – Lesefehler: dann eben weniger Wörter
            continue
        for wd in words:
            text = re.sub(r"^[^A-Za-z0-9%]+|[^A-Za-z0-9%!?]+$", "", wd.text)
            if len(text) < 2 or wd.conf < 40:
                continue
            box = [(x0 + wd.x / scale) / fw, (y0 + wd.y / scale) / fh,
                   (x0 + (wd.x + wd.w) / scale) / fw, (y0 + (wd.y + wd.h) / scale) / fh]
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            if any(t.lower() == text.lower() and abs((b[0] + b[2]) / 2 - cx) < 0.01 and abs((b[1] + b[3]) / 2 - cy)
                   < 0.01 for t, b in found):
                continue
            found.append((text, box))
    return found


def find_word(frame: np.ndarray, roi: list[float], ocr, *wanted: str) -> list[float] | None:
    """Lage des ersten Worts aus wanted (ohne Groß-/Kleinschreibung) im Bereich, sonst None."""
    want = {w.lower() for w in wanted}
    for text, box in words_in(frame, roi, ocr):
        if text.lower() in want:
            return box
    return None


class SlotLayout:
    """Symbol-Plätze einer Welt-Zeile (aus der Vorlage-Zeile der Karte): Abstand, Breite, Höhe; leere Plätze
    werden am ruhigen Rand erkannt (gemessen: belegt ≥ 31, leer ≤ 21)."""
    EMPTY_STD = 25.0

    def __init__(self, uimap: UiMap, list_window: dict) -> None:
        icons, wide = [], []
        for row in uimap.rows(list_window):
            kids = [e for e in uimap.children(row) if e.get("rel") and e.get("kind") in ("Knopf", "Symbol")]
            small = sorted((e["rel"] for e in kids if e["rel"][2] - e["rel"][0] < 0.09), key=lambda r: r[0])
            if len(small) >= 3:
                icons = small
                wide = [e["rel"] for e in kids if e["rel"][2] - e["rel"][0] >= 0.09 and e["rel"][0] > 0.6]
                break
        if len(icons) < 3:
            raise ValueError("keine Vorlage-Zeile mit Symbolen")
        diffs = sorted(b[0] - a[0] for a, b in zip(icons, icons[1:]))
        self.pitch = diffs[len(diffs) // 2]
        self.x0 = icons[0][0]
        widths = sorted(r[2] - r[0] for r in icons)
        self.w = widths[len(widths) // 2]
        tops, bottoms = sorted(r[1] for r in icons), sorted(r[3] for r in icons)
        self.y = (tops[len(tops) // 2], bottoms[len(bottoms) // 2])
        end = min((r[0] for r in wide), default=0.78)
        self.count = int((end - self.x0) / self.pitch) + 1

    def slots(self, row_img: np.ndarray) -> list[tuple[int, list[float]]]:
        """Belegte Plätze: (Platz, Lage in der Zeile)."""
        h, w = row_img.shape[:2]
        out = []
        for i in range(self.count):
            x0 = self.x0 + i * self.pitch
            rel = [x0, self.y[0], x0 + self.w, self.y[1]]
            crop = row_img[int(rel[1] * h):int(rel[3] * h), int(rel[0] * w):int(rel[2] * w)]
            if crop.size == 0:
                continue
            g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)[:, :max(8, int(crop.shape[1] * 0.6))]
            ring = np.concatenate([g[2:5, 4:].ravel(), g[-5:-2, 4:].ravel(), g[4:-4, 2:5].ravel()])
            if float(ring.std()) >= self.EMPTY_STD:
                out.append((i, [round(v, 4) for v in rel]))
        return out

    def index_of(self, rel: list[float]) -> int | None:
        if rel[2] - rel[0] >= 0.09:
            return None
        i = round((rel[0] - self.x0) / self.pitch)
        return i if 0 <= i < self.count else None


def read_text(frame: np.ndarray, roi: list[float], ocr) -> str:
    """Text in einem Bereich lesen (z. B. „Kosten (Yen)“ im Pets-Roll-Menü)."""
    fh, fw = frame.shape[:2]
    crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
    if crop.size == 0 or ocr is None:
        return ""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _t, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    binary = cv2.resize(binary, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return ocr.line(binary, psm=7).strip()
