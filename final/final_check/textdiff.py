"""Line-level text comparison with positions.

- Raw text is compared exactly (spaces, units, decimals, symbols kept).
- Whitespace-normalized equality is reported separately as an auxiliary result.
- Extraction-order changes are not content changes.
- A global offset (canvas shift) is estimated from identical lines, and both the
  raw-coordinate movement and the movement after removing that offset are kept,
  so a real element move is not erased by registration.
"""
from __future__ import annotations

import difflib
import re
import statistics
from collections import Counter
from typing import Any

from .common import nfc

NUM_RE = re.compile(
    r"(?<![\w.])[-+]?\d+(?:[.,]\d+)*(?:\s?(?:fl\.?\s?oz|ml|mL|ML|ℓ|kg|mg|g|G|L|l|oz|%|매|개입|개|ea|EA|cm|mm|호|원|매입))?"
)
FIELD_HINTS = [
    ("EXPIRY_OR_DATE", re.compile(r"사용기한|유통기한|개봉\s*후|EXP|Exp|exp|까지|\d{4}[./-]\d{1,2}[./-]\d{1,2}")),
    ("VOLUME_OR_WEIGHT", re.compile(r"용량|내용량|중량|\d\s?(?:ml|mL|g|kg|L|oz)\b")),
    ("LOT_OR_BATCH", re.compile(r"제조번호|LOT|Lot|lot|배치")),
    ("BARCODE_LIKE_NUMBER", re.compile(r"(?<!\d)\d{8}(?!\d)|(?<!\d)\d{12,14}(?!\d)")),
    ("PERCENT", re.compile(r"%")),
    ("PRICE", re.compile(r"₩|\d\s?원|가격")),
]


def ws_norm(text: str) -> str:
    return re.sub(r"\s+", " ", nfc(text)).strip()


def tokens(text: str) -> list[str]:
    return re.findall(r"\S+", nfc(text))


def numbers(text: str) -> list[str]:
    return [m.group(0) for m in NUM_RE.finditer(nfc(text))]


def field_hints(*texts: str) -> list[str]:
    joined = " ".join(texts)
    return [name for name, rx in FIELD_HINTS if rx.search(joined)]


def _center(b: list[float]) -> tuple[float, float]:
    return (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def estimate_shift(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> tuple[float, float, int]:
    count_b = Counter(nfc(l["text"]) for l in before)
    count_a = Counter(nfc(l["text"]) for l in after)
    by_text_a = {nfc(l["text"]): l for l in after}
    dx, dy = [], []
    for l in before:
        t = nfc(l["text"])
        if count_b[t] == 1 and count_a.get(t) == 1:
            cb, ca = _center(l["bbox"]), _center(by_text_a[t]["bbox"])
            dx.append(ca[0] - cb[0])
            dy.append(ca[1] - cb[1])
    if not dx:
        return 0.0, 0.0, 0
    return float(statistics.median(dx)), float(statistics.median(dy)), len(dx)


def _token_ops(a: str, b: str) -> list[dict[str, str]]:
    ta, tb = tokens(a), tokens(b)
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ta, b=tb, autojunk=False).get_opcodes():
        if tag != "equal":
            ops.append({"op": tag, "before": " ".join(ta[i1:i2]), "after": " ".join(tb[j1:j2])})
    if not ops and a != b:
        # Same tokens, different raw characters (e.g. spacing) – show raw.
        ops.append({"op": "replace_raw", "before": a, "after": b})
    return ops


def _lis_length(seq: list[int]) -> int:
    import bisect

    tails: list[int] = []
    for x in seq:
        i = bisect.bisect_left(tails, x)
        if i == len(tails):
            tails.append(x)
        else:
            tails[i] = x
    return len(tails)


def compare_lines(before: list[dict[str, Any]], after: list[dict[str, Any]], settings: dict[str, Any],
                  page_label: str) -> dict[str, Any]:
    tol = float(settings.get("position_tolerance_pt", 3.0))
    min_ratio = float(settings.get("line_match_ratio", 0.5))
    max_dist = float(settings.get("max_match_distance_pt", 150.0))
    sx, sy, anchors = estimate_shift(before, after)

    used_b: set[int] = set()
    used_a: set[int] = set()
    pairs: list[tuple[int, int]] = []

    # 1) identical raw text, nearest after removing global shift
    candidates = []
    idx_a: dict[str, list[int]] = {}
    for j, l in enumerate(after):
        idx_a.setdefault(nfc(l["text"]), []).append(j)
    for i, l in enumerate(before):
        cb = _center(l["bbox"])
        for j in idx_a.get(nfc(l["text"]), []):
            ca = _center(after[j]["bbox"])
            candidates.append((_dist((cb[0] + sx, cb[1] + sy), ca), i, j))
    for _, i, j in sorted(candidates):
        if i in used_b or j in used_a:
            continue
        used_b.add(i)
        used_a.add(j)
        pairs.append((i, j))

    items: list[dict[str, Any]] = []
    n = 0

    def new_id() -> str:
        nonlocal n
        n += 1
        return f"{page_label}-T{n:03d}"

    moved = 0
    for i, j in pairs:
        cb, ca = _center(before[i]["bbox"]), _center(after[j]["bbox"])
        raw = (ca[0] - cb[0], ca[1] - cb[1])
        reg = (raw[0] - sx, raw[1] - sy)
        if abs(reg[0]) > tol or abs(reg[1]) > tol:
            moved += 1
            items.append({
                "id": new_id(), "kind": "TEXT_MOVED",
                "before": before[i]["text"], "after": after[j]["text"],
                "before_bbox_pt": before[i]["bbox"], "after_bbox_pt": after[j]["bbox"],
                "move_raw_pt": [round(raw[0], 2), round(raw[1], 2)],
                "move_after_canvas_shift_pt": [round(reg[0], 2), round(reg[1], 2)],
                "numeric_change": False, "numbers_before": [], "numbers_after": [],
                "field_hints": field_hints(before[i]["text"]),
            })
        elif before[i].get("font_size") and after[j].get("font_size") and \
                abs(float(before[i]["font_size"]) - float(after[j]["font_size"])) > 0.2:
            items.append({
                "id": new_id(), "kind": "TEXT_SIZE_CHANGED",
                "before": before[i]["text"], "after": after[j]["text"],
                "before_bbox_pt": before[i]["bbox"], "after_bbox_pt": after[j]["bbox"],
                "font_size_before": before[i]["font_size"], "font_size_after": after[j]["font_size"],
                "numeric_change": False, "numbers_before": [], "numbers_after": [],
                "field_hints": field_hints(before[i]["text"]),
            })

    # extraction order change (informational only)
    order_pairs = sorted(pairs, key=lambda p: before[p[0]]["order"])
    after_orders = [after[j]["order"] for _, j in order_pairs]
    order_changes = len(after_orders) - _lis_length(after_orders) if after_orders else 0

    # 2) similar lines near the same place -> changed
    rest_b = [i for i in range(len(before)) if i not in used_b]
    rest_a = [j for j in range(len(after)) if j not in used_a]
    sim = []
    for i in rest_b:
        cb = _center(before[i]["bbox"])
        tb = ws_norm(before[i]["text"])
        for j in rest_a:
            ca = _center(after[j]["bbox"])
            d = _dist((cb[0] + sx, cb[1] + sy), ca)
            if d > max_dist:
                continue
            ta = ws_norm(after[j]["text"])
            ratio = difflib.SequenceMatcher(a=tb, b=ta, autojunk=False).ratio()
            if ratio >= min_ratio:
                sim.append((ratio - d / (max_dist * 4), i, j, ratio))
    for _, i, j, ratio in sorted(sim, reverse=True):
        if i in used_b or j in used_a:
            continue
        used_b.add(i)
        used_a.add(j)
        bt, at = before[i]["text"], after[j]["text"]
        nb, na = numbers(bt), numbers(at)
        kind = "WHITESPACE_ONLY_CHANGE" if ws_norm(bt) == ws_norm(at) else "TEXT_CHANGED"
        items.append({
            "id": new_id(), "kind": kind, "before": bt, "after": at,
            "before_bbox_pt": before[i]["bbox"], "after_bbox_pt": after[j]["bbox"],
            "similarity": round(ratio, 3), "token_ops": _token_ops(bt, at),
            "numbers_before": nb, "numbers_after": na,
            "numeric_change": Counter(nb) != Counter(na),
            "field_hints": field_hints(bt, at),
        })

    # 3) leftovers: removed / added, unless it is only a line-break reflow
    rem = [i for i in range(len(before)) if i not in used_b]
    add = [j for j in range(len(after)) if j not in used_a]
    reflow = False
    if rem and add:
        tb = Counter(t for i in rem for t in tokens(before[i]["text"]))
        ta = Counter(t for j in add for t in tokens(after[j]["text"]))
        reflow = tb == ta
    if reflow:
        items.append({
            "id": new_id(), "kind": "LINE_BREAK_REFLOW_ONLY",
            "before": "\n".join(before[i]["text"] for i in rem),
            "after": "\n".join(after[j]["text"] for j in add),
            "before_bbox_pt": _union([before[i]["bbox"] for i in rem]),
            "after_bbox_pt": _union([after[j]["bbox"] for j in add]),
            "numeric_change": False, "numbers_before": [], "numbers_after": [], "field_hints": [],
        })
    else:
        for i in rem:
            nb = numbers(before[i]["text"])
            items.append({
                "id": new_id(), "kind": "TEXT_REMOVED", "before": before[i]["text"], "after": None,
                "before_bbox_pt": before[i]["bbox"], "after_bbox_pt": None,
                "numbers_before": nb, "numbers_after": [], "numeric_change": bool(nb),
                "field_hints": field_hints(before[i]["text"]),
            })
        for j in add:
            na = numbers(after[j]["text"])
            items.append({
                "id": new_id(), "kind": "TEXT_ADDED", "before": None, "after": after[j]["text"],
                "before_bbox_pt": None, "after_bbox_pt": after[j]["bbox"],
                "numbers_before": [], "numbers_after": na, "numeric_change": bool(na),
                "field_hints": field_hints(after[j]["text"]),
            })

    canvas_shift = None
    if anchors >= 2 and (abs(sx) > tol or abs(sy) > tol):
        canvas_shift = {"dx_pt": round(sx, 2), "dy_pt": round(sy, 2), "anchor_lines": anchors}
    return {
        "lines_before": len(before), "lines_after": len(after),
        "unchanged_lines": len(pairs) - moved,
        "extraction_order_changes": order_changes,
        "text_canvas_shift": canvas_shift,
        "items": items,
    }


def _union(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
