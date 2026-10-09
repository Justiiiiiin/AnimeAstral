"""Suggest markings by itself (without Qt, owner's wish 08.10.2026: “I can't enter everything by hand”). From the
window image and the words read come boxes like in the marking tool (review.py):

- **Buttons** by shape and color: filled, single-colored, rounded areas with text (Roll, Auto Roll, MAX,
  Craft, Open, Claim All, Filters …). The text decides the kind: Leave/Delete … = “never press”, AUTO ON/OFF = switch.
- **Switches**: label with a colon (“AUTO CLAIM:”, “SYNC WITH EQUIP BEST:”, “Auto Rank Up:”) + area below.
- **Tabs**: left one below the other / bottom side by side (knowledge.side_tabs) or ≥ 3 equally sized buttons in a row.
- **Values/progress**: “64/700”, “6/7”, “Level 32/32”, “514δU / MAX”, “3/40 owned”.
- **Tiles** (Equip Best, inventory, pets): equally sized squares with a colored border; without a scrollable list =
  buttons, with a list = one “list” box around the grid.
- **Lists**: areas that really scrolled while exploring; **search fields** (“Search …”).
All boxes in fractions of the window image; every suggestion carries “auto”: True and is confirmed in the tool."""
from __future__ import annotations

import re
from typing import Optional

import cv2
import numpy as np

from . import knowledge

VALUE_RE = re.compile(r"\d[\d.,]*\s*[A-Za-zδβ]*\s*/\s*(?:\d[\d.,]*|MAX)", re.I)


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def color_buttons(img: np.ndarray) -> list[list[float]]:
    """Filled, single-colored, rounded areas (buttons) – fractions [x0,y0,x1,y1]. Colored TEXT is dropped (too
    little filled), as are images (too colorful)."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sat = (hsv[..., 1] > 110) & (hsv[..., 2] > 110)
    mask = cv2.morphologyEx(sat.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if not (0.03 * h < bh < 0.14 * h and bw > 0.05 * w and 1.6 < bw / bh < 9) or y < 0.12 * h:
            continue
        raw = sat[y:y + bh, x:x + bw]
        if area / (bw * bh) < 0.55 or raw.mean() < 0.6:   # text instead of an area
            continue
        hue = hsv[y:y + bh, x:x + bw, 0][raw]
        if hue.size and np.std(hue) > 25:                 # multicolored = image, not a button
            continue
        out.append([x / w, y / h, (x + bw) / w, (y + bh) / h])
    return out


def tiles(img: np.ndarray) -> list[list[float]]:
    """Tiles: roughly square areas with a colored border (Equip Best, inventory, pets), similar size."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    edge = ((hsv[..., 1] > 90) & (hsv[..., 2] > 120)).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(edge, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        if 0.06 * w < bw < 0.22 * w and 0.75 < bw / max(1, bh) < 1.35 and y > 0.12 * h:
            fill = edge[y:y + bh, x:x + bw].mean() / 255
            if fill < 0.55:                                # border, image inside – no filled area
                boxes.append([x / w, y / h, (x + bw) / w, (y + bh) / h])
    boxes = _dedupe(boxes)
    if len(boxes) < 3:
        return []
    sizes = sorted(b[2] - b[0] for b in boxes)
    med = sizes[len(sizes) // 2]
    return [b for b in boxes if abs((b[2] - b[0]) - med) < 0.2 * med]


def _dedupe(boxes: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for b in sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
        if not any(_overlap(b, o) > 0.5 for o in out):
            out.append(b)
    return out


def _overlap(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1e-9
    return ix * iy / small


def _text_in(box: list[float], words: list[tuple[str, list[float]]]) -> str:
    inside = [(t, b) for t, b in words if _overlap(box, b) > 0.6]
    return " ".join(t for t, _b in sorted(inside, key=lambda c: (round(c[1][1], 2), c[1][0])))


def _kind_for(text: str) -> str:
    n = _norm(text)
    if knowledge.is_forbidden(text):
        return "never"
    if n.startswith("auto") and (n.endswith("on") or n.endswith("off")):
        return "toggle"
    return "button"


def suggest(img: np.ndarray, words: list[tuple[str, list[float]]],
            scroll_boxes: Optional[list[list[float]]] = None) -> list[dict]:
    """Suggestions for a window image. words: (text, position) in fractions of THIS image; scroll_boxes: areas that
    scrolled while exploring (fractions of the image)."""
    out: list[dict] = []

    def add(box, kind, text):
        if not any(_overlap(box, o["box"]) > 0.7 for o in out):
            out.append({"box": [round(max(0.0, min(1.0, v)), 4) for v in box], "kind": kind, "text": text,
                        "auto": True})

    full = [0.0, 0.0, 1.0, 1.0]
    for box in scroll_boxes or []:                         # 1. gemessene Listen
        add(box, "list", "Liste")
    for t, b in knowledge.side_tabs(words, full):          # 2. tabs left/bottom
        add(b, "tab", t)
    buttons = color_buttons(img)                           # 3. colored buttons (+ tab rows at the top)
    rows: dict[int, list] = {}
    for b in buttons:
        rows.setdefault(round(((b[1] + b[3]) / 2) / 0.03), []).append(b)
    tab_rows = [r for r in rows.values() if len(r) >= 3 and max(x[2] - x[0] for x in r) < 1.6 * min(x[2] - x[0] for x in r)]
    for r in tab_rows:
        for b in r:
            add(b, "tab", _text_in(b, words) or "Reiter")
    for b in buttons:
        text = _text_in(b, words)
        if text:
            add(b, _kind_for(text), text)
    for t, b in words:                                     # 4. switches: “AUTO CLAIM:” + area below
        if t.endswith(":") and len(_norm(t)) >= 3:
            hh = b[3] - b[1]
            label = " ".join(x for x, o in words if abs(o[1] - b[1]) < 0.6 * hh and o[2] <= b[2] + 0.01
                             and b[0] - o[2] < 0.15)
            add([b[0] - 0.01, b[1] - 0.01, b[2] + 0.01, b[3] + 3.0 * hh], "toggle", label.strip() or t)
    for t, b in words:                                     # 5. Werte/Fortschritt, Suchfelder
        if _norm(t).startswith("search"):
            add([b[0] - 0.01, b[1] - 0.01, min(1.0, b[2] + 0.3), b[3] + 0.01], "info", "Suchfeld")
    for line_words in _lines(words):
        text = " ".join(t for t, _b in line_words)
        for m in VALUE_RE.finditer(text):
            part = [b for t, b in line_words if t in m.group(0) or m.group(0).startswith(t)]
            if part:
                box = [min(p[0] for p in part), min(p[1] for p in part), max(p[2] for p in part),
                       max(p[3] for p in part)]
                add([box[0] - 0.01, box[1] - 0.01, box[2] + 0.01, box[3] + 0.01], "value", m.group(0))
    grid = tiles(img)                                      # 6. Kacheln
    if grid:
        in_list = [g for g in grid if any(_overlap(g, s) > 0.5 for s in scroll_boxes or [])]
        if len(in_list) >= 3 or len(grid) > 12:
            box = [min(g[0] for g in grid), min(g[1] for g in grid), max(g[2] for g in grid),
                   max(g[3] for g in grid)]
            add(box, "list", "Raster")
        else:
            for g in grid:
                add(g, "button", _text_in(g, words) or "Kachel")
    return out


def _lines(words: list[tuple[str, list[float]]]) -> list[list[tuple[str, list[float]]]]:
    rows: list[list] = []
    for t, b in sorted(words, key=lambda c: ((c[1][1] + c[1][3]) / 2, c[1][0])):
        cy, hh = (b[1] + b[3]) / 2, b[3] - b[1]
        if rows and abs(rows[-1][0] - cy) < 0.5 * hh:
            rows[-1][1].append((t, b))
        else:
            rows.append([cy, [(t, b)]])
    return [sorted(r[1], key=lambda c: c[1][0]) for r in rows]
