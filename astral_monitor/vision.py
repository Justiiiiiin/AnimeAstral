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
X_WIDE_HIT = 0.78     # kleinere Fenster (X weiter links/unten, etwas kleiner): gemessen 0,80–0,89
X_WIDE = (0.45, 0.08, 0.92, 0.55)    # Suchbereich dafür im Roblox-Fenster
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
            return self._state_wide(frame, ocr, tpl)
        dx, dy = (rx + lx - ex) / fw, (ry + ly - ey) / fh
        x0, y0, x1, y1 = self.roi
        roi = [min(1.0, max(0.0, v)) for v in (x0 + dx, y0 + dy, x1 + dx, y1 + dy)]
        crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
        x_center = (self.x_at[0] + dx + self.x_size[0] / 2, self.x_at[1] + dy + self.x_size[1] / 2)
        return roi, read_title(crop, ocr) or read_title_loose(crop, ocr), x_center

    def _state_wide(self, frame: np.ndarray, ocr, tpl: np.ndarray):
        """Kleineres Fenster (Acc. Curses, Titan Passives, Equip Best …): X woanders und etwas kleiner. Lage des
        Fensters geschätzt: oben rechts am X, waagerecht mittig wie alle Menüs, Größe im Verhältnis."""
        fh, fw = frame.shape[:2]
        ax0, ay0 = int(X_WIDE[0] * fw), int(X_WIDE[1] * fh)
        area = frame[ay0:int(X_WIDE[3] * fh), ax0:int(X_WIDE[2] * fw)]
        best = (0.0, 1.0, (0, 0), tpl.shape[:2])
        for s in (0.8, 0.9, 1.0):
            t = _scaled(tpl, s)
            if area.shape[0] < t.shape[0] or area.shape[1] < t.shape[1]:
                continue
            _a, score, _b, loc = cv2.minMaxLoc(cv2.matchTemplate(area, t, cv2.TM_CCOEFF_NORMED))
            if score > best[0]:
                best = (score, s, loc, t.shape[:2])
        score, s, (lx, ly), (th, tw) = best
        if score < X_WIDE_HIT:
            return None
        cx, cy = (ax0 + lx + tw / 2) / fw, (ay0 + ly + th / 2) / fh
        x0, y0, x1, y1 = self.roi
        std_cx, std_cy = self.x_at[0] + self.x_size[0] / 2, self.x_at[1] + self.x_size[1] / 2
        mid = (x0 + x1) / 2
        right = cx + (x1 - std_cx) * s
        top = cy - (std_cy - y0) * s
        roi = [max(0.0, 2 * mid - right), max(0.0, top), min(1.0, right), min(1.0, top + (y1 - y0) * s)]
        crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
        return roi, read_title(crop, ocr) or read_title_loose(crop, ocr), (cx, cy)

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


def read_title_loose(window_img: np.ndarray, ocr) -> str:
    """Ersatz, wenn read_title nichts findet (Titel grau statt weiß, heller Banner): Banner leicht gedreht und mit
    zwei Schwellen lesen, längstes Ergebnis nehmen (gemessen: Commandments, Kagune Upgrade, Goddess Shrine …)."""
    if ocr is None:
        return ""
    h, w = window_img.shape[:2]
    band = window_img[0:int(BAND[2] * h), int(BAND[0] * w):int(BAND[1] * w)]
    if band.size == 0:
        return ""
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    best = ""
    for angle in (-4, 0, 4):
        m = cv2.getRotationMatrix2D((gray.shape[1] / 2, gray.shape[0] / 2), angle, 1)
        turned = cv2.warpAffine(gray, m, (gray.shape[1], gray.shape[0]), borderMode=cv2.BORDER_REPLICATE)
        for limit in (200, 160):
            binary = cv2.threshold(turned, limit, 255, cv2.THRESH_BINARY_INV)[1]
            try:
                words = ocr.words(binary, psm=11)
            except Exception:  # noqa: BLE001 – Lesefehler: anderer Versuch
                continue
            good = [wd for wd in sorted(words, key=lambda wd: wd.x)
                    if wd.conf >= 60 and len(re.sub(r"[^A-Za-z]", "", wd.text)) >= 3]
            text = " ".join(re.sub(r"[^A-Za-z0-9!? ]", " ", wd.text).strip() for wd in good)
            if len(text) > len(best):
                best = text
    return re.sub(r"\s+", " ", best).strip()


def read_name_below_banner(window_img: np.ndarray, ocr) -> str:
    """Großer roter/oranger Name unter dem Banner (Raids: „Holy Grail War“, Boss Rush: „Zaban Rush!“) – sonst leer.
    Die farbige Textzeile wird über die Zeilensummen gefunden, ausgeschnitten und als eine Zeile gelesen."""
    if ocr is None:
        return ""
    h, w = window_img.shape[:2]
    area = window_img[int(0.22 * h):int(0.40 * h), int(0.07 * w):int(0.58 * w)]
    if area.size == 0:
        return ""
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)               # Rot (Raid) oder Orange (Boss Rush)
    mask = (((hsv[..., 0] < 22) | (hsv[..., 0] > 165)) & (hsv[..., 1] > 120) & (hsv[..., 2] > 150)).astype(np.uint8)
    rows = mask.sum(axis=1)
    on = list(rows > max(3, 0.02 * mask.shape[1])) + [False]
    best, start = (0, 0, 0), None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if rows[start:i].sum() > best[0]:
                best = (int(rows[start:i].sum()), start, i)
            start = None
    _total, y0, y1 = best
    if y1 - y0 < 6:
        return ""
    cols = np.where(mask[y0:y1].any(axis=0))[0]
    x0, x1 = int(cols.min()), int(cols.max())
    crop = 255 - mask[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 5] * 255
    f = 48 / max(1, y1 - y0)
    crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    crop = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    try:
        text = ocr.line(crop, psm=7)
    except Exception:  # noqa: BLE001
        return ""
    text = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9!?)]+$", "", text).strip()
    if len(re.sub(r"[^A-Za-z]", "", text)) < 3:
        return ""
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
    """Symbol-Plätze einer Welt-Zeile (aus der Vorlage-Zeile der Karte): Abstand, Breite, Höhe. Belegt = scharfe
    Umrisse (Laplace-Varianz auf 40 × 40, gemessen 08.10.2026: Symbole ≥ 319, Hintergrund hinter dem letzten Symbol
    ≤ 295, meist < 120). Symbole stehen lückenlos ab Platz 1 – der erste leere Platz beendet die Zeile."""
    SHARP_MIN = 250.0

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
        self.end = end                                    # linker Rand des TELEPORT!-Knopfs
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
            # letzter Platz ragt in den TELEPORT!-Knopf: dessen Kante ist auch scharf (~400–550) -> strenger
            limit = self.SHARP_MIN * (3 if rel[2] > self.end else 1)
            if sharpness(crop) < limit:
                break                                     # Ende der Symbole (dahinter nur Hintergrund/Knopf)
            out.append((i, [round(v, 4) for v in rel]))
        return out

    def index_of(self, rel: list[float]) -> int | None:
        if rel[2] - rel[0] >= 0.09:
            return None
        i = round((rel[0] - self.x0) / self.pitch)
        return i if 0 <= i < self.count else None


def sharpness(crop: np.ndarray) -> float:
    gray = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (40, 40), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_32F).var())


def find_multiscale(frame: np.ndarray, tpl: np.ndarray, region: list[float],
                    scales=(0.6, 0.75, 0.9, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0)) -> tuple[float, Optional[list[float]]]:
    """Bild in einem Bereich in mehreren Größen suchen (Vorlage aus einem Bildschirmfoto unbekannter Größe).
    Rückgabe (Ähnlichkeit, Lage im Roblox-Fenster)."""
    fh, fw = frame.shape[:2]
    x0, y0 = int(region[0] * fw), int(region[1] * fh)
    area = cv2.cvtColor(frame[y0:int(region[3] * fh), x0:int(region[2] * fw)], cv2.COLOR_BGR2GRAY)
    gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    best, box = -1.0, None
    for s in scales:
        t = cv2.resize(gray, None, fx=s * fw / 2560, fy=s * fw / 2560, interpolation=cv2.INTER_AREA)
        if t.shape[0] < 8 or t.shape[0] > area.shape[0] or t.shape[1] > area.shape[1]:
            continue
        _a, score, _b, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(area, t, cv2.TM_CCOEFF_NORMED))
        if score > best:
            best = score
            box = [(x0 + lx) / fw, (y0 + ly) / fh, (x0 + lx + t.shape[1]) / fw, (y0 + ly + t.shape[0]) / fh]
    return best, box


def toggle_state(frame: np.ndarray, label: list[float]) -> Optional[bool]:
    """Schalter rechts neben einer Beschriftung (Raid-Zahnrad: „Auto Retry“, „Auto Leave“): grün = an, rosa/rot =
    aus, None = nicht erkennbar (verdeckt)."""
    fh, fw = frame.shape[:2]
    h = label[3] - label[1]
    cy = (label[1] + label[3]) / 2
    # nur der Streifen, in dem der Schalter sitzt (gemessen: 0,035–0,06 rechts der Beschriftung bei 2560 px) –
    # Meldungen wie „Wave cleared!“ (grün) liegen oft darüber und dürfen nicht mitzählen
    x0, x1 = label[2] + 0.02, min(1.0, label[2] + 0.08)
    y0, y1 = max(0.0, cy - 0.7 * h), min(1.0, cy + 0.7 * h)
    crop = frame[int(y0 * fh):int(y1 * fh), int(x0 * fw):int(x1 * fw)].astype(np.int16)
    if crop.size == 0:
        return None
    g, r = crop[..., 1], crop[..., 2]

    def blob(mask: np.ndarray) -> int:
        """Größter zusammenhängender Fleck: der runde Knopf des Schalters – nicht die dünne grüne Linie einer
        „Wave cleared!“-Meldung, die quer durch die Zeile laufen kann."""
        n, _lab, st, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        return max((int(st[i, cv2.CC_STAT_AREA]) for i in range(1, n)
                    if st[i, cv2.CC_STAT_HEIGHT] >= 0.35 * mask.shape[0]), default=0)

    green = blob((g > 150) & (r < 140) & (g - r > 60))
    pink = blob((r > 150) & (g < 110) & (r - g > 80))
    if max(green, pink) < 15 or min(green, pink) > 0.5 * max(green, pink):
        return None                                   # nichts oder beides deutlich (verdeckt): später nochmal
    return green > pink


def same_icon(a: np.ndarray, b: np.ndarray) -> float:
    """Ähnlichkeit zweier Symbol-Bilder: Kern (ohne Rand und ohne die rechte obere Ecke mit dem spielerabhängigen
    Häkchen) des einen im anderen gesucht, beide Richtungen. Gleiche Symbole ~0,99, ähnliche andere bis ~0,9."""
    if a is None or b is None or a.size == 0 or b.size == 0:
        return -1.0
    if abs(a.shape[0] - b.shape[0]) > 0.25 * max(a.shape[0], b.shape[0]):
        b = cv2.resize(b, (int(b.shape[1] * a.shape[0] / b.shape[0]), a.shape[0]), interpolation=cv2.INTER_AREA)
    best = -1.0
    for x, y in ((a, b), (b, a)):
        h, w = y.shape[:2]
        core = y[int(0.30 * h):int(0.88 * h), int(0.14 * w):int(0.64 * w)]
        if core.size == 0 or core.shape[0] > x.shape[0] or core.shape[1] > x.shape[1]:
            continue
        best = max(best, float(cv2.minMaxLoc(cv2.matchTemplate(x, core, cv2.TM_CCOEFF_NORMED))[1]))
    return best


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
