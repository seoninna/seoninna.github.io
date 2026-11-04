"""Pixel comparison producing *visual change candidates* (not verdicts).

Steps per mapped page/region:
1. Pad both renders to the same canvas (white).
2. Estimate a single global translation (canvas shift) by phase correlation.
   The shift is recorded; it is accepted only if it explains most of the raw
   difference. Residual differences after the shift are kept as candidates, so a
   logo that moved relative to the rest of the artwork is NOT erased.
3. Tolerance diff: a pixel differs only if no pixel within +/-tolerance_px in the
   other image is within pixel_threshold (anti-aliasing tolerance). Small digits
   still differ by many pixels and are kept; nothing is dropped by size except
   specks below min_region_pixels (reported as a count, not hidden).
4. Group differing pixels into boxes on a coarse grid, classify and try to pair
   removed/added boxes into move candidates.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np


def pad_to(img: np.ndarray, h: int, w: int) -> np.ndarray:
    if img.shape == (h, w):
        return img
    out = np.full((h, w), 255, dtype=np.uint8)
    out[: img.shape[0], : img.shape[1]] = img
    return out


def shift_image(img: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Return S with S(y, x) = img(y + dy, x + dx), white outside."""
    h, w = img.shape
    out = np.full_like(img, 255)
    ys0, ys1 = max(0, -dy), min(h, h - dy)
    xs0, xs1 = max(0, -dx), min(w, w - dx)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = img[ys0 + dy: ys1 + dy, xs0 + dx: xs1 + dx]
    return out


def _neighborhood(img: np.ndarray, r: int) -> tuple[np.ndarray, np.ndarray]:
    if r <= 0:
        return img, img
    p = np.pad(img, r, mode="edge")
    h, w = img.shape
    lo = img.copy()
    hi = img.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            view = p[r + dy: r + dy + h, r + dx: r + dx + w]
            np.minimum(lo, view, out=lo)
            np.maximum(hi, view, out=hi)
    return lo, hi


def tolerance_mask(a: np.ndarray, b: np.ndarray, threshold: int, r: int) -> np.ndarray:
    a16 = a.astype(np.int16)
    b16 = b.astype(np.int16)
    blo, bhi = _neighborhood(b, r)
    alo, ahi = _neighborhood(a, r)
    m1 = (a16 < blo.astype(np.int16) - threshold) | (a16 > bhi.astype(np.int16) + threshold)
    m2 = (b16 < alo.astype(np.int16) - threshold) | (b16 > ahi.astype(np.int16) + threshold)
    return m1 | m2


def phase_shift(a: np.ndarray, b: np.ndarray) -> tuple[int, int]:
    """Translation (dy, dx) such that b(y, x) ~= a(y - dy, x - dx)."""
    f = max(1, int(max(a.shape) / 700))
    A = (255 - a[::f, ::f]).astype(np.float32)
    B = (255 - b[::f, ::f]).astype(np.float32)
    if A.sum() == 0 or B.sum() == 0:
        return 0, 0
    Fa = np.fft.rfft2(A)
    Fb = np.fft.rfft2(B)
    R = Fb * np.conj(Fa)
    R /= np.abs(R) + 1e-6
    corr = np.fft.irfft2(R, s=A.shape)
    py, px = np.unravel_index(int(np.argmax(corr)), corr.shape)
    if py > A.shape[0] // 2:
        py -= A.shape[0]
    if px > A.shape[1] // 2:
        px -= A.shape[1]
    dy, dx = int(py * f), int(px * f)
    if f > 1:  # refine at full resolution on a subsample
        best = None
        for ry in range(-f, f + 1):
            for rx in range(-f, f + 1):
                s = shift_image(b, dy + ry, dx + rx)
                score = int(np.count_nonzero(np.abs(a[::2, ::2].astype(np.int16) - s[::2, ::2]) > 48))
                if best is None or score < best[0]:
                    best = (score, dy + ry, dx + rx)
        assert best is not None
        dy, dx = best[1], best[2]
    return dy, dx


def shift_bilinear(img: np.ndarray, dy: float, dx: float) -> np.ndarray:
    """Sub-pixel version of shift_image (bilinear, white outside)."""
    iy, ix = int(np.floor(dy)), int(np.floor(dx))
    fy, fx = dy - iy, dx - ix
    if fy == 0 and fx == 0:
        return shift_image(img, iy, ix)
    s00 = shift_image(img, iy, ix).astype(np.float32)
    s01 = shift_image(img, iy, ix + 1).astype(np.float32)
    s10 = shift_image(img, iy + 1, ix).astype(np.float32)
    s11 = shift_image(img, iy + 1, ix + 1).astype(np.float32)
    out = (1 - fy) * ((1 - fx) * s00 + fx * s01) + fy * ((1 - fx) * s10 + fx * s11)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def subpixel_refine(a: np.ndarray, b: np.ndarray, dy: float, dx: float, thr: int) -> tuple[float, float]:
    best = None
    steps = [-0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75]
    sa = a[::2, ::2].astype(np.int16)
    for ry in steps:
        for rx in steps:
            cand = shift_bilinear(b, dy + ry, dx + rx)
            score = int(np.count_nonzero(np.abs(sa - cand[::2, ::2]) > thr))
            if best is None or score < best[0]:
                best = (score, dy + ry, dx + rx)
    assert best is not None
    return best[1], best[2]


def _dilate(grid: np.ndarray, g: int) -> np.ndarray:
    if g <= 0:
        return grid
    p = np.pad(grid, g)
    out = np.zeros_like(grid)
    h, w = grid.shape
    for dy in range(-g, g + 1):
        for dx in range(-g, g + 1):
            out |= p[g + dy: g + dy + h, g + dx: g + dx + w]
    return out


def find_regions(mask: np.ndarray, cell: int, gap: int, min_pixels: int, max_regions: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    h, w = mask.shape
    gh, gw = -(-h // cell), -(-w // cell)
    padded = np.zeros((gh * cell, gw * cell), dtype=bool)
    padded[:h, :w] = mask
    grid = padded.reshape(gh, cell, gw, cell).any(axis=(1, 3))
    joined = _dilate(grid, gap)
    labels = np.zeros(joined.shape, dtype=np.int32)
    comps: list[tuple[int, int, int, int]] = []
    current = 0
    for sy, sx in zip(*np.nonzero(grid)):
        if labels[sy, sx]:
            continue
        current += 1
        q = deque([(int(sy), int(sx))])
        labels[sy, sx] = current
        y0 = y1 = int(sy)
        x0 = x1 = int(sx)
        while q:
            y, x = q.popleft()
            if grid[y, x]:
                y0, y1, x0, x1 = min(y0, y), max(y1, y), min(x0, x), max(x1, x)
            for ny in (y - 1, y, y + 1):
                for nx in (x - 1, x, x + 1):
                    if 0 <= ny < gh and 0 <= nx < gw and joined[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = current
                        q.append((ny, nx))
        comps.append((y0, y1, x0, x1))
    regions = []
    dropped_specks = 0
    for y0, y1, x0, x1 in comps:
        box = [x0 * cell, y0 * cell, min(w, (x1 + 1) * cell), min(h, (y1 + 1) * cell)]
        px = int(np.count_nonzero(mask[box[1]: box[3], box[0]: box[2]]))
        if px < min_pixels:
            dropped_specks += 1
            continue
        regions.append({"box_px": box, "diff_pixels": px})
    regions.sort(key=lambda r: -r["diff_pixels"])
    truncated = max(0, len(regions) - max_regions)
    return regions[:max_regions], {"specks_below_min_pixels": dropped_specks, "regions_truncated": truncated}


def _ncc(x: np.ndarray, y: np.ndarray) -> float:
    h, w = min(x.shape[0], y.shape[0]), min(x.shape[1], y.shape[1])
    if h < 3 or w < 3:
        return 0.0
    a = x[:h, :w].astype(np.float32)
    b = y[:h, :w].astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den > 0 else 0.0


def _content_box(img: np.ndarray, box: list[int]) -> list[int] | None:
    x0, y0, x1, y1 = box
    ink = img[y0:y1, x0:x1] < 200
    if not ink.any():
        return None
    ys, xs = np.nonzero(ink)
    return [x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()) + 1, y0 + int(ys.max()) + 1]


def compare_images(a: np.ndarray, b: np.ndarray, settings: dict[str, Any]) -> dict[str, Any]:
    h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    size_differs = a.shape != b.shape
    a = pad_to(a, h, w)
    b = pad_to(b, h, w)
    thr = int(settings.get("pixel_threshold", 48))
    r = int(settings.get("tolerance_px", 0))
    raw_mask = tolerance_mask(a, b, thr, r)
    raw_px = int(np.count_nonzero(raw_mask))
    dy = dx = 0.0
    shift_accepted = False
    mask = raw_mask
    b_al = b
    if raw_px and not settings.get("_disable_shift"):
        sdy, sdx = phase_shift(a, b)
        frac = float(settings.get("canvas_shift_max_fraction", 0.25))
        hint = settings.get("_hint_shift_px")  # from text anchors (pt -> px), may be fractional
        options = []
        if (sdy or sdx) and abs(sdy) <= h * frac and abs(sdx) <= w * frac:
            options.append((float(sdy), float(sdx)))
        if hint and (abs(hint[0]) > 0.3 or abs(hint[1]) > 0.3):
            options.append((float(hint[1]), float(hint[0])))
        best = None
        hint_opt = (float(hint[1]), float(hint[0])) if hint else None
        for oy, ox in options:
            ry, rx = subpixel_refine(a, b, oy, ox, thr)
            cand = shift_bilinear(b, ry, rx)
            cmask = tolerance_mask(a, cand, int(settings.get("pixel_threshold_after_shift", 64)),
                                   int(settings.get("tolerance_px_after_shift", 0)))
            cpx = int(np.count_nonzero(cmask))
            # Image-only estimate must explain most of the difference. A shift confirmed by
            # unchanged text lines (PDF coordinates) only has to reduce it, because a real
            # element move (e.g. logo) legitimately remains as residual.
            limit = raw_px * (0.9 if (oy, ox) == hint_opt else 0.5)
            if cpx < limit and (best is None or cpx < best[0]):
                best = (cpx, ry, rx, cmask, cand)
        if best:
            _, dy, dx, mask, b_al = best
            shift_accepted = True
    regions, region_stats = find_regions(
        mask,
        int(settings.get("cell_px", 6)),
        int(settings.get("merge_gap_cells", 2)),
        int(settings.get("min_region_pixels", 6)),
        int(settings.get("max_regions_per_page", 150)),
    )
    # classify
    for reg in regions:
        x0, y0, x1, y1 = reg["box_px"]
        ink_b = int(np.count_nonzero(a[y0:y1, x0:x1] < 128))
        ink_a = int(np.count_nonzero(b_al[y0:y1, x0:x1] < 128))
        if ink_b > 0 and ink_a <= ink_b * 0.1:
            reg["kind"] = "CONTENT_REMOVED_CANDIDATE"
        elif ink_a > 0 and ink_b <= ink_a * 0.1:
            reg["kind"] = "CONTENT_ADDED_CANDIDATE"
        else:
            reg["kind"] = "CONTENT_MODIFIED_CANDIDATE"
        reg["ink_before_px"] = ink_b
        reg["ink_after_px"] = ink_a
        sub = mask[y0:y1, x0:x1]
        peak = int(np.abs(a[y0:y1, x0:x1].astype(np.int16) - b_al[y0:y1, x0:x1])[sub].max()) if sub.any() else 0
        reg["max_abs_diff"] = peak
        reg["low_contrast_edge_only"] = peak < 128
        # local move inside one region (small displacement)
        if reg["kind"] == "CONTENT_MODIFIED_CANDIDATE":
            pad = max(8, (y1 - y0) // 2, (x1 - x0) // 2)
            X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
            ca, cb = a[Y0:Y1, X0:X1], b_al[Y0:Y1, X0:X1]
            ldy, ldx = phase_shift(ca, cb)
            if ldy or ldx:
                before_px = int(np.count_nonzero(tolerance_mask(ca, cb, thr, r)))
                after_px = int(np.count_nonzero(tolerance_mask(ca, shift_image(cb, ldy, ldx), thr, r)))
                if before_px and after_px <= before_px * 0.2:
                    reg["kind"] = "MOVE_CANDIDATE"
                    reg["move_px"] = [ldx, ldy]
    # pair removed/added regions into moves
    removed = [g for g in regions if g["kind"] == "CONTENT_REMOVED_CANDIDATE"]
    added = [g for g in regions if g["kind"] == "CONTENT_ADDED_CANDIDATE"]
    min_score = float(settings.get("move_match_score", 0.85))
    for rg in removed:
        rb = _content_box(a, rg["box_px"])
        if rb is None:
            continue
        best = None
        for ag in added:
            if ag.get("paired_with") is not None:
                continue
            ab = _content_box(b_al, ag["box_px"])
            if ab is None:
                continue
            rw, rh = rb[2] - rb[0], rb[3] - rb[1]
            aw, ah = ab[2] - ab[0], ab[3] - ab[1]
            if not (0.75 <= (aw + 1) / (rw + 1) <= 1.33 and 0.75 <= (ah + 1) / (rh + 1) <= 1.33):
                continue
            score = _ncc(a[rb[1]: rb[3], rb[0]: rb[2]], b_al[ab[1]: ab[3], ab[0]: ab[2]])
            if score >= min_score and (best is None or score > best[0]):
                best = (score, ag, ab)
        if best:
            score, ag, ab = best
            vec = [ab[0] - rb[0], ab[1] - rb[1]]
            rg["kind"] = ag["kind"] = "MOVE_CANDIDATE"
            rg["move_px"] = ag["move_px"] = vec
            rg["move_match_score"] = ag["move_match_score"] = round(score, 3)
            rg["paired_with"] = id(ag)
            ag["paired_with"] = id(rg)
    for i, reg in enumerate(regions):
        reg["index"] = i + 1
    ids = {id(reg): reg["index"] for reg in regions}
    for reg in regions:
        if reg.get("paired_with") is not None:
            reg["paired_with"] = ids.get(reg["paired_with"])
    return {
        "canvas_px": [w, h],
        "size_differs": size_differs,
        "raw_diff_pixels": raw_px,
        "canvas_shift_px": [round(dx, 2), round(dy, 2)] if shift_accepted else None,
        "diff_pixels_after_canvas_shift": int(np.count_nonzero(mask)),
        "regions": regions,
        **region_stats,
        "_a": a,
        "_b_aligned": b_al,
    }


def overlay_rgb(a: np.ndarray, b_al: np.ndarray, regions: list[dict[str, Any]]) -> np.ndarray:
    """R = before, G/B = after. Cyan = only in before, red = only in after."""
    img = np.dstack([a, b_al, b_al]).copy()
    h, w = a.shape
    t = 2
    for reg in regions:
        x0, y0, x1, y1 = reg["box_px"]
        x0, y0 = max(0, x0 - 3), max(0, y0 - 3)
        x1, y1 = min(w, x1 + 3), min(h, y1 + 3)
        color = (255, 140, 0) if reg["kind"] != "MOVE_CANDIDATE" else (160, 0, 255)
        img[y0: y0 + t, x0:x1] = color
        img[max(y0, y1 - t): y1, x0:x1] = color
        img[y0:y1, x0: x0 + t] = color
        img[y0:y1, max(x0, x1 - t): x1] = color
    return img
