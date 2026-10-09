"""Image recognition for the automation (without Qt): find world rows in the teleporter and read their names,
detect an open menu (pink X at the top right + title in the banner), detect special menus by template (Pets-Roll).
Methods and thresholds come from the developer tool and were measured on real screenshots (07.10.2026)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .uimap import UiMap

ROW_HIT = 0.85        # heart marker at the top left of every row: real rows 0.98–1.0, anything else ≤ 0.6
BOTTOM_HIT = 0.60     # bottom edge of the row present (otherwise cut off at the edge of the list)
X_HIT = 0.85          # inner X of a menu: other menus 0.96, teleporter 1.0
X_WIDE_HIT = 0.78     # smaller windows (X further left/down, a bit smaller): measured 0.80–0.89
X_WIDE_SOFT = 0.7       # just below that only with a readable title (the background behind the X interferes)
X_WIDE = (0.45, 0.05, 0.97, 0.55)    # search area for it in the Roblox window (guild: X far right)
MARKER_HIT = 0.80     # marker of a special menu
BAND = (0.03, 0.55, 0.22)   # title banner in the menu frame: x from, x to, y to
X_BAND = 0.04         # this far left/right of the usual row start the heart is searched


def _scaled(img: np.ndarray, f: float) -> np.ndarray:
    return img if abs(f - 1) < 0.01 else cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)

WIDE_SCALES = (0.8, 0.85, 0.9, 0.95, 1.0, 1.1, 1.2, 1.3)   # smaller menus (Mana Contract) … guild (1.2×)


def _wide_x_search(area: np.ndarray, tpl: np.ndarray) -> tuple[float, float, tuple[int, int], tuple[int, int]]:
    """Best X in the wide area: (score, scale, position, template size). Coarse first – grey and half size over all
    scales – then the exact color comparison at full size only around the best coarse hits (the scale and its
    neighbors). Same result as searching everything in full color, but ~10× faster (owner 09.10.2026: CPU spikes
    while the macro collects; before ~240 ms per search at 2560 px)."""
    small = cv2.cvtColor(cv2.resize(area, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    coarse = []
    for s in WIDE_SCALES:
        t = cv2.resize(gray, None, fx=0.5 * s, fy=0.5 * s, interpolation=cv2.INTER_AREA)
        if t.shape[0] < 6 or small.shape[0] < t.shape[0] or small.shape[1] < t.shape[1]:
            continue
        _a, score, _b, loc = cv2.minMaxLoc(cv2.matchTemplate(small, t, cv2.TM_CCOEFF_NORMED))
        coarse.append((score, s, loc))
    best = (0.0, 1.0, (0, 0), tpl.shape[:2])
    if not coarse:
        return best
    coarse.sort(reverse=True)
    checked = set()
    for _score, s0, (cx, cy) in coarse[:2]:              # the two best coarse candidates
        i = WIDE_SCALES.index(s0)
        for s in WIDE_SCALES[max(0, i - 1):i + 2]:
            if (s, cx, cy) in checked:
                continue
            checked.add((s, cx, cy))
            t = _scaled(tpl, s)
            m = 6 + int(0.15 * t.shape[1])               # search margin around the coarse hit (full pixels)
            x0, y0 = max(0, 2 * cx - m), max(0, 2 * cy - m)
            win = area[y0:min(area.shape[0], 2 * cy + t.shape[0] + m), x0:min(area.shape[1], 2 * cx + t.shape[1] + m)]
            if win.shape[0] < t.shape[0] or win.shape[1] < t.shape[1]:
                continue
            _a, score, _b, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED))
            if score > best[0]:
                best = (score, s, (x0 + lx, y0 + ly), t.shape[:2])
    return best



@dataclass
class Row:
    roi: list[float]                      # position in the Roblox window
    image: np.ndarray


class RowFinder:
    """Find the world rows of a list by the always identical heart at the top left (size from the template row)."""

    def __init__(self, row: dict, image: np.ndarray) -> None:
        h, w = image.shape[:2]
        self.size = (w, h)
        self.window_w = (row.get("window") or [w])[0]
        self.marker_off = (0.01, 0.05)
        self.marker = image[int(0.05 * h):int(0.45 * h), int(0.01 * w):int(0.07 * w)]
        self.bottom = image[int(0.86 * h):, :int(0.10 * w)]
        # rows always start at the same place: only a narrow strip around the left edge is searched
        # (measured: ~6× faster than the whole list, same hits)
        roi = row.get("roi")
        self.x_band = (roi[0] - X_BAND, roi[0] + 0.07 * (roi[2] - roi[0]) + X_BAND) if roi else None

    def find(self, frame: np.ndarray, area: list[float]) -> list[Row]:
        fh, fw = frame.shape[:2]
        f = fw / self.window_w
        marker = _scaled(self.marker, f)
        rw, rh = int(self.size[0] * f), int(self.size[1] * f)
        ax0, ay0, ax1, ay1 = int(area[0] * fw), int(area[1] * fh), int(area[2] * fw), int(area[3] * fh)
        if self.x_band is not None:
            ax0 = max(ax0, int(self.x_band[0] * fw))
            ax1 = min(ax1, int(self.x_band[1] * fw) + marker.shape[1])
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
                continue                                  # cut off at the bottom
            out.append(Row([x / fw, y / fh, (x + rw) / fw, (y + rh) / fh], image))
        return sorted(out, key=lambda r: r.roi[1])


def read_row_name(row_img: np.ndarray, ocr) -> str:
    """World name (white text at the top left next to the globe)."""
    h, w = row_img.shape[:2]
    gray = cv2.cvtColor(row_img[int(0.08 * h):int(0.45 * h), int(0.11 * w):int(0.62 * w)], cv2.COLOR_BGR2GRAY)
    _t, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    return re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9!?')]+$", "", ocr.line(binary, psm=7)).strip()


class MenuFrame:
    """Menus sit in the same frame as the teleporter: open = pink X found at the top right; title in the banner."""

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

    def state(self, frame: np.ndarray, ocr, wide: bool = True) -> Optional[tuple[list[float], str, tuple[float, float]]]:
        """(position of the menu, title, center of the X) – or None if no menu is open in the standard frame.
        wide=False: only the standard frame (raid windows) – the search for smaller windows at 8 sizes costs ~240 ms
        at 2560 px and is skipped (background check in the lobby every 3 s, owner 09.10.2026: CPU spikes)."""
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
            return self._state_wide(frame, ocr, tpl) if wide else None
        dx, dy = (rx + lx - ex) / fw, (ry + ly - ey) / fh
        x0, y0, x1, y1 = self.roi
        roi = [min(1.0, max(0.0, v)) for v in (x0 + dx, y0 + dy, x1 + dx, y1 + dy)]
        crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
        x_center = (self.x_at[0] + dx + self.x_size[0] / 2, self.x_at[1] + dy + self.x_size[1] / 2)
        return roi, read_title(crop, ocr) or read_title_loose(crop, ocr), x_center

    def _state_wide(self, frame: np.ndarray, ocr, tpl: np.ndarray):
        """Smaller window (Acc. Curses, Titan Passives, Equip Best …): X elsewhere and a bit smaller. Position of the
        window estimated: top right at the X, horizontally centered like all menus, size in proportion."""
        fh, fw = frame.shape[:2]
        ax0, ay0 = int(X_WIDE[0] * fw), int(X_WIDE[1] * fh)
        area = frame[ay0:int(X_WIDE[3] * fh), ax0:int(X_WIDE[2] * fw)]
        score, s, (lx, ly), (th, tw) = _wide_x_search(area, tpl)
        if score < X_WIDE_SOFT:
            return None                                   # just below (bright background behind the X, e.g.
        weak = score < X_WIDE_HIT                         # Mana Contract in a raid): only valid with a readable title
        cx, cy = (ax0 + lx + tw / 2) / fw, (ay0 + ly + th / 2) / fh
        x0, y0, x1, y1 = self.roi
        std_cx, std_cy = self.x_at[0] + self.x_size[0] / 2, self.x_at[1] + self.x_size[1] / 2
        mid = (x0 + x1) / 2
        right = cx + (x1 - std_cx) * s
        top = cy - (std_cy - y0) * s
        roi = [max(0.0, 2 * mid - right), max(0.0, top), min(1.0, right), min(1.0, top + (y1 - y0) * s)]
        crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
        title = read_title(crop, ocr) or read_title_loose(crop, ocr)
        if weak and len(re.sub(r"[^A-Za-z]", "", title)) < 4:
            return None
        return roi, title, (cx, cy)

    def is_base(self, title: str) -> bool:
        return bool(title) and same_title(title, self.base_title)


TITLE_CONF = 55          # below this a banner reading counts as uncertain (junk like “Emtt dala Cowerl”) -> second way


def read_title(window_img: np.ndarray, ocr) -> str:
    """Title in the slanted banner at the top left (“Teleport”, “Trial Shop”). First the white text in the banner
    (_read_banner); if that reading is uncertain or empty (grey banners like “Otsutsuki Shrine”, full-screen windows),
    the largest text line in the banner area via the normal word search. Better no title than a wrong one."""
    if ocr is None:
        return ""
    text, conf = _read_banner(window_img, ocr)
    if text and conf >= TITLE_CONF:
        return text
    other, conf2 = _read_band_words(window_img, ocr)
    letters = re.sub(r"[^a-z]", "", other.lower())
    if letters and letters in re.sub(r"[^a-z]", "", text.lower()):
        return text                                       # the banner has more of the same title (“SixFold Spirit Contract”)
    if other and conf2 >= TITLE_CONF and (not text or conf2 > conf):
        return other
    return text if conf >= 35 else ""


def _line_conf(ocr, img: np.ndarray) -> tuple[str, float]:
    """Read one line (psm 7) with the mean confidence of the words."""
    try:
        words = ocr.words(img, psm=7)
    except Exception:  # noqa: BLE001 – read error: empty
        return "", 0.0
    words = [w for w in words if w.text.strip()]
    if not words:
        return "", 0.0
    return " ".join(w.text for w in words), float(np.mean([w.conf for w in words]))


def _clean_title(text: str) -> str:
    text = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9!?)]+$", "", text).strip()
    text = re.sub(r"\s+", " ", re.sub(r"[^\w !?'&.()/-]", " ", text)).strip()    # remove leftover special characters
    return text[:1].upper() + text[1:]


def _read_band_words(window_img: np.ndarray, ocr) -> tuple[str, float]:
    """Second way: words in the banner area (general search), the largest line from left to right."""
    h, w = window_img.shape[:2]
    band = window_img[0:int(BAND[2] * h), 0:int(BAND[1] * w)]
    if band.size == 0:
        return "", 0.0
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    f = 2.0 if band.shape[0] < 200 else 1.0
    best: tuple[str, float] = ("", 0.0)
    for binary in (cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)[1],
                   cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]):
        img = binary if f == 1.0 else cv2.resize(binary, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        try:
            words = [wd for wd in ocr.words(img, psm=11) if len(re.sub(r"[^A-Za-z]", "", wd.text)) >= 2
                     and wd.conf >= 40]
        except Exception:  # noqa: BLE001
            continue
        if not words:
            continue
        top = max(words, key=lambda wd: wd.h)
        line = sorted((wd for wd in words if wd.h >= 0.7 * top.h and abs((wd.y + wd.h / 2) - (top.y + top.h / 2))
                       < 0.6 * top.h), key=lambda wd: wd.x)
        parts = [line[0].text]
        for prev, wd in zip(line, line[1:]):              # psm 11 likes to split in the middle of a word (“Kag une”)
            parts.append(("" if wd.x - (prev.x + prev.w) < 0.2 * top.h else " ") + wd.text)
        text = _clean_title("".join(parts))
        if re.match(r"(?i)wave\b", text) or re.search(r"\d+\s*/\s*\d+", text):
            continue                                      # wave counter at the top (full-screen window), not a title
        conf = float(np.mean([wd.conf for wd in line]))
        if len(re.sub(r"[^A-Za-z]", "", text)) >= 3 and conf > best[1]:
            best = (text, conf)
    return best


def _read_banner(window_img: np.ndarray, ocr) -> tuple[str, float]:
    """White text in the banner: stripes sorted out by letter size, letters chained left to right into the
    (slanted) line, straightened. Returns (text, confidence 0–100)."""
    h, w = window_img.shape[:2]
    band = window_img[0:int(BAND[2] * h), int(BAND[0] * w):int(BAND[1] * w)]
    if band.size == 0:
        return "", 0.0
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    sat = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)[..., 1]
    mask = ((gray > 225) & (sat < 40)).astype(np.uint8) * 255
    n, lab, st, _c = cv2.connectedComponentsWithStats(mask, 8)
    comps = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > 40]
    if not comps:
        return "", 0.0
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
        return "", 0.0
    best = _join_words(best, chains, st, mid, hmax)
    x0 = min(st[i, cv2.CC_STAT_LEFT] for i in best)
    x1 = max(st[i, cv2.CC_STAT_LEFT] + st[i, cv2.CC_STAT_WIDTH] for i in best)
    y0 = min(st[i, cv2.CC_STAT_TOP] for i in best)
    y1 = max(st[i, cv2.CC_STAT_TOP] + st[i, cv2.CC_STAT_HEIGHT] for i in best)
    ink = np.isin(lab, best).astype(np.uint8) * 255
    text, conf = "", 0.0
    if len(best) >= 3:                                    # straighten the slanted line (otherwise Tesseract often reads nothing)
        xs = [st[i, cv2.CC_STAT_LEFT] + st[i, cv2.CC_STAT_WIDTH] / 2 for i in best]
        slope = float(np.polyfit(xs, [mid[i] for i in best], 1)[0])
        letter_h = float(np.median([st[i, cv2.CC_STAT_HEIGHT] for i in best]))
        part = ink[max(0, y0 - 10):y1 + 10, max(0, x0 - 10):x1 + 10]
        part = cv2.copyMakeBorder(part, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=0)
        m = cv2.getRotationMatrix2D((part.shape[1] / 2, part.shape[0] / 2), np.degrees(np.arctan(slope)), 1.0)
        part = cv2.warpAffine(part, m, (part.shape[1], part.shape[0]), flags=cv2.INTER_LINEAR)
        ys, xs2 = np.nonzero(part > 127)
        if ys.size:
            part = 255 - part[ys.min():ys.max() + 1, xs2.min():xs2.max() + 1]
            f = 40 / max(1.0, letter_h)
            part = cv2.resize(part, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
            part = cv2.copyMakeBorder(part, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            text, conf = _line_conf(ocr, part)
            text = _clean_title(text)
    if not text:                                          # previous way (not rotated)
        crop = 255 - ink[max(0, y0 - 10):y1 + 10, max(0, x0 - 10):x1 + 10]
        f = 48 / max(1, y1 - y0)
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        crop = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        text, conf = _line_conf(ocr, crop)
        text = _clean_title(text)
    return text, conf


def _join_words(best: list[int], chains: list[list[int]], st, mid: dict, hmax: float) -> list[int]:
    """Append more words of the same (slanted) title line: “AINCRAD” + “SPOILS”, “RELICS OF THE” + “OTHERWORLD”.
    Condition: similar letter height, gap < 3.5 letter heights, line center matches at the nearest letter."""
    def height(c):
        return float(np.median([st[i, cv2.CC_STAT_HEIGHT] for i in c]))

    def left(c):
        return min(st[i, cv2.CC_STAT_LEFT] for i in c)

    def right(c):
        return max(st[i, cv2.CC_STAT_LEFT] + st[i, cv2.CC_STAT_WIDTH] for i in c)

    best = list(best)
    rest = [c for c in chains if c is not best and set(c).isdisjoint(best) and len(c) >= 2]
    changed = True
    while changed:
        changed = False
        hb = height(best)
        for c in list(rest):
            if abs(height(c) - hb) > 0.3 * hb:
                continue
            if left(c) >= right(best):                     # to the right
                gap = left(c) - right(best)
                a = max(best, key=lambda i: st[i, cv2.CC_STAT_LEFT])
                b = min(c, key=lambda i: st[i, cv2.CC_STAT_LEFT])
            elif right(c) <= left(best):                   # to the left
                gap = left(best) - right(c)
                a = min(best, key=lambda i: st[i, cv2.CC_STAT_LEFT])
                b = max(c, key=lambda i: st[i, cv2.CC_STAT_LEFT])
            else:
                continue
            if gap < 3.5 * hb and abs(mid[a] - mid[b]) < 0.6 * hb:
                best += c
                rest.remove(c)
                changed = True
    return best


def read_title_loose(window_img: np.ndarray, ocr) -> str:
    """Fallback if read_title finds nothing (grey instead of white title, bright banner): read the banner slightly
    rotated with two thresholds, take the longest result (measured: Commandments, Kagune Upgrade, Goddess Shrine …)."""
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
            except Exception:  # noqa: BLE001 – read error: another try
                continue
            good = [wd for wd in sorted(words, key=lambda wd: wd.x)
                    if wd.conf >= 60 and len(re.sub(r"[^A-Za-z]", "", wd.text)) >= 3]
            text = " ".join(re.sub(r"[^A-Za-z0-9!? ]", " ", wd.text).strip() for wd in good)
            if len(text) > len(best):
                best = text
    return re.sub(r"\s+", " ", best).strip()


def read_name_below_banner(window_img: np.ndarray, ocr) -> str:
    """Large red/orange name below the banner (raids: “Holy Grail War”, boss rush: “Zaban Rush!”) – otherwise empty.
    The colored text line is found via row sums, cut out and read as one line."""
    if ocr is None:
        return ""
    h, w = window_img.shape[:2]
    area = window_img[int(0.22 * h):int(0.40 * h), int(0.07 * w):int(0.58 * w)]
    if area.size == 0:
        return ""
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)               # red (raid) or orange (boss rush)
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
    """Does a read title (“Crafting”) match the window name (“W3 Crafting”)? Generous: misreads, world number."""
    import difflib
    a = re.sub(r"[^a-z0-9]", "", read.lower())
    b = re.sub(r"[^a-z0-9]", "", re.sub(r"^W\d+\s+", "", name).lower())
    return bool(a) and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.75)


class TemplateMenu:
    """Special menu with a fixed layout (Pets-Roll), detected by the marker at a fixed place."""

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
    """All words in an area with their position in the Roblox window (fractions). Two passes: bright text with an
    outline (buttons, titles) and general (Otsu) – duplicate hits are merged."""
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
        except Exception:  # noqa: BLE001 – read error: fewer words then
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
    """Position of the first word from wanted (case-insensitive) in the area, otherwise None."""
    want = {w.lower() for w in wanted}
    for text, box in words_in(frame, roi, ocr):
        if text.lower() in want:
            return box
    return None


class SlotLayout:
    """Icon slots of a world row (from the map's template row): spacing, width, height. Occupied = sharp outlines
    (Laplace variance on 40 × 40, measured 08.10.2026: icons ≥ 319, background behind the last icon ≤ 295, mostly
    < 120). Icons are contiguous from slot 1 – the first empty slot ends the row."""
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
            raise ValueError("no template row with icons")
        diffs = sorted(b[0] - a[0] for a, b in zip(icons, icons[1:]))
        self.pitch = diffs[len(diffs) // 2]
        self.x0 = icons[0][0]
        widths = sorted(r[2] - r[0] for r in icons)
        self.w = widths[len(widths) // 2]
        tops, bottoms = sorted(r[1] for r in icons), sorted(r[3] for r in icons)
        self.y = (tops[len(tops) // 2], bottoms[len(bottoms) // 2])
        end = min((r[0] for r in wide), default=0.78)
        self.end = end                                    # left edge of the TELEPORT! button
        self.count = int((end - self.x0) / self.pitch) + 1

    def slots(self, row_img: np.ndarray) -> list[tuple[int, list[float]]]:
        """Occupied slots: (slot, position in the row)."""
        h, w = row_img.shape[:2]
        out = []
        for i in range(self.count):
            x0 = self.x0 + i * self.pitch
            rel = [x0, self.y[0], x0 + self.w, self.y[1]]
            crop = row_img[int(rel[1] * h):int(rel[3] * h), int(rel[0] * w):int(rel[2] * w)]
            if crop.size == 0:
                continue
            # the last slot reaches into the TELEPORT! button: its edge is sharp too (~400–550) -> stricter
            limit = self.SHARP_MIN * (3 if rel[2] > self.end else 1)
            if sharpness(crop) < limit:
                break                                     # end of the icons (only background/button behind)
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
    """Search an image in an area at several sizes (template from a screenshot of unknown size).
    Returns (similarity, position in the Roblox window)."""
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
    """Switch to the right of a label (raid gear: “Auto Retry”, “Auto Leave”): green = on, pink/red = off,
    None = not recognizable (covered)."""
    fh, fw = frame.shape[:2]
    h = label[3] - label[1]
    cy = (label[1] + label[3]) / 2
    # only the strip where the switch sits (measured: 0.035–0.06 right of the label at 2560 px) –
    # messages like “Wave cleared!” (green) often lie above it and must not count
    x0, x1 = label[2] + 0.02, min(1.0, label[2] + 0.08)
    y0, y1 = max(0.0, cy - 0.7 * h), min(1.0, cy + 0.7 * h)
    crop = frame[int(y0 * fh):int(y1 * fh), int(x0 * fw):int(x1 * fw)].astype(np.int16)
    if crop.size == 0:
        return None
    g, r = crop[..., 1], crop[..., 2]

    def blob(mask: np.ndarray) -> int:
        """Largest connected blob: the round knob of the switch – not the thin green line of a “Wave cleared!”
        message that can run across the row."""
        n, _lab, st, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        return max((int(st[i, cv2.CC_STAT_AREA]) for i in range(1, n)
                    if st[i, cv2.CC_STAT_HEIGHT] >= 0.35 * mask.shape[0]), default=0)

    green = blob((g > 150) & (r < 140) & (g - r > 60))
    pink = blob((r > 150) & (g < 110) & (r - g > 80))
    if max(green, pink) < 15 or min(green, pink) > 0.5 * max(green, pink):
        return None                                   # nothing or both clearly (covered): try again later
    return green > pink


def same_icon(a: np.ndarray, b: np.ndarray) -> float:
    """Similarity of two icon images: the core (without border and without the top right corner with the
    player-dependent check mark) of one searched in the other, both directions. Same icons ~0.99, similar others up to ~0.9."""
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
    """Read text in an area (e.g. “cost (yen)” in the pets roll menu)."""
    fh, fw = frame.shape[:2]
    crop = frame[int(roi[1] * fh):int(roi[3] * fh), int(roi[0] * fw):int(roi[2] * fw)]
    if crop.size == 0 or ocr is None:
        return ""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _t, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    binary = cv2.resize(binary, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return ocr.line(binary, psm=7).strip()
