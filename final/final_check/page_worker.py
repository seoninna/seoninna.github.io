"""Process ONE mapped page (or clip) pair: text + visual. Runs inline or in a
separate process (page_isolation=process) so a crash/timeout on one huge page
does not lose the other pages. Results are written as private JSON."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from . import pdfio, textdiff, visual
from .common import FinalError, atomic_write_json, install_network_guard, quiet_pdf_library


def _maybe_test_fault(spec: dict[str, Any]) -> None:
    """TEST-ONLY fault injection. Active only when FINAL_TEST_FAULT is set by the
    synthetic test-suite (format '<label>:<times>'). Never set in real runs."""
    value = os.environ.get("FINAL_TEST_FAULT")
    if not value:
        return
    label, _, times = value.partition(":")
    if label != spec["label"]:
        return
    marker = Path(spec["page_dir"]) / f".test_fault_{label}"
    seen = int(marker.read_text()) if marker.exists() else 0
    if seen < int(times or 1):
        marker.write_text(str(seen + 1))
        if os.environ.get("FINAL_TEST_FAULT_MODE") == "hang":
            import time
            time.sleep(3600)
        raise RuntimeError("TEST_INJECTED_FAULT")


def _render_cached(page: Any, dpi: float, clip: list[float] | None, cache_dir: Path | None,
                   file_hash: str, page_no: int) -> np.ndarray:
    if cache_dir is None:
        return pdfio.render_gray(page, dpi, clip)
    clip_key = "full" if not clip else "c" + "_".join(str(int(v)) for v in clip)
    path = cache_dir / file_hash[:16] / f"p{page_no}_{clip_key}_{dpi:.2f}.png"
    if path.exists():
        try:
            pix = pdfio.pymupdf.Pixmap(str(path))
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, : pix.width].copy()
            return arr
        except Exception:
            pass
    arr = pdfio.render_gray(page, dpi, clip)
    try:
        pdfio.save_png_gray(arr, path)
    except Exception:
        pass
    return arr


def _place(arr: np.ndarray, off_y: int, off_x: int, shape: tuple[int, int]) -> np.ndarray:
    """Copy arr into a white canvas of `shape` so that arr[r, c] lands at (r+off_y, c+off_x)."""
    out = np.full(shape, 255, dtype=np.uint8)
    h, w = arr.shape
    y0, x0 = max(0, off_y), max(0, off_x)
    y1, x1 = min(shape[0], off_y + h), min(shape[1], off_x + w)
    if y1 > y0 and x1 > x0:
        out[y0:y1, x0:x1] = arr[y0 - off_y: y1 - off_y, x0 - off_x: x1 - off_x]
    return out


def _aligned_after(pa: Any, dpi: float, ca: list[float] | None, cb: list[float] | None,
                   s_px: tuple[float, float], shape: tuple[int, int]) -> np.ndarray:
    """Re-render the after page translated by -shift so the PDF renderer itself does
    the sub-pixel alignment (no resampling blur)."""
    mp = pdfio.pymupdf
    z = dpi / 72.0
    ob = (mp.Rect(cb) * mp.Matrix(z, z)).irect if cb else mp.IRect(0, 0, 0, 0)
    cao = (ca[0], ca[1]) if ca else (0.0, 0.0)
    cbo = (cb[0], cb[1]) if cb else (0.0, 0.0)
    tx = s_px[0] + (cao[0] - cbo[0]) * z
    ty = s_px[1] + (cao[1] - cbo[1]) * z
    clip = None
    if ca:
        clip = mp.Rect(ca) + (s_px[0] / z, s_px[1] / z, s_px[0] / z, s_px[1] / z)
    pix = pa.get_pixmap(matrix=mp.Matrix(z, 0, 0, z, -tx, -ty), clip=clip, colorspace=mp.csGRAY, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, : pix.width].copy()
    return _place(arr, pix.y - ob.y0, pix.x - ob.x0, shape)


def _residual(a: np.ndarray, b: np.ndarray, thr: int) -> int:
    h, w = a.shape
    my, mx = max(2, h // 30), max(2, w // 30)
    return int(np.count_nonzero(np.abs(a[my:h - my, mx:w - mx].astype(np.int16) - b[my:h - my, mx:w - mx]) > thr))


def _refine_by_rerender(img_b: np.ndarray, pa: Any, dpi: float, ca: Any, cb: Any,
                        est: tuple[float, float], thr: int) -> tuple[float, float]:
    steps = [-0.5, -0.375, -0.25, -0.125, 0.0, 0.125, 0.25, 0.375, 0.5]
    if img_b.size > 3_000_000:
        steps = [-0.5, -0.25, 0.0, 0.25, 0.5]
    sx, sy = est
    best = (_residual(img_b, _aligned_after(pa, dpi, ca, cb, (sx, sy), img_b.shape), thr), sx)
    for o in steps:
        if o == 0:
            continue
        r = _residual(img_b, _aligned_after(pa, dpi, ca, cb, (est[0] + o, sy), img_b.shape), thr)
        if r < best[0]:
            best = (r, est[0] + o)
    sx = best[1]
    best_y = (best[0], sy)
    for o in steps:
        if o == 0:
            continue
        r = _residual(img_b, _aligned_after(pa, dpi, ca, cb, (sx, est[1] + o), img_b.shape), thr)
        if r < best_y[0]:
            best_y = (r, est[1] + o)
    return sx, best_y[1]


def _intersects(a: list[float], b: list[float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _fine_crop(page: Any, box_pt: list[float], clip: list[float] | None, dpi: float, max_pixels: int,
               path: Path) -> str | None:
    ox, oy = (clip[0], clip[1]) if clip else (0.0, 0.0)
    pad = 6.0
    rect = [box_pt[0] + ox - pad, box_pt[1] + oy - pad, box_pt[2] + ox + pad, box_pt[3] + oy + pad]
    r = pdfio.pymupdf.Rect(rect) & page.rect
    if r.is_empty:
        return None
    use_dpi = pdfio.plan_render(float(r.width), float(r.height), dpi, max_pixels)
    arr = pdfio.render_gray(page, use_dpi, [r.x0, r.y0, r.x1, r.y1])
    pdfio.save_png_gray(arr, path)
    return path.name


def process_page(spec: dict[str, Any]) -> dict[str, Any]:
    _maybe_test_fault(spec)
    proc = spec["processing"]
    page_dir = Path(spec["page_dir"])
    img_dir = Path(spec["image_dir"])
    cache_dir = Path(spec["cache_dir"]) if spec.get("cache_dir") else None
    label = spec["label"]
    result: dict[str, Any] = {
        "label": label,
        "before_page": spec["before_page"], "after_page": spec["after_page"],
        "before_clip_pt": spec.get("before_clip"), "after_clip_pt": spec.get("after_clip"),
        "notes": [],
    }
    doc_b = pdfio.open_pdf(Path(spec["before_path"]))
    doc_a = pdfio.open_pdf(Path(spec["after_path"]))
    try:
        pb = doc_b[spec["before_page"] - 1]
        pa = doc_a[spec["after_page"] - 1]
        cb, ca = spec.get("before_clip"), spec.get("after_clip")
        result["before_info"] = pdfio.page_info(pb)
        result["after_info"] = pdfio.page_info(pa)
        if result["before_info"]["rotation"] != result["after_info"]["rotation"]:
            result["notes"].append("ROTATION_DIFFERS")
        # ---------------- text ----------------
        lb = pdfio.text_lines(pb, cb)
        la = pdfio.text_lines(pa, ca)
        prof_b = pdfio.content_profile(pb, lb)
        prof_a = pdfio.content_profile(pa, la)
        result["before_profile"], result["after_profile"] = prof_b, prof_a
        result["lines_before"], result["lines_after"] = lb, la
        cb_chars, ca_chars = prof_b["text_chars"], prof_a["text_chars"]
        if cb_chars == 0 and ca_chars == 0:
            text = {"status": "UNVERIFIABLE_NO_TEXT_LAYER", "items": []}
        elif cb_chars == 0 or ca_chars == 0:
            # e.g. text outlined in one version: a text diff would claim that
            # everything was deleted/added, which would be misleading.
            text = {"status": "UNVERIFIABLE_TEXT_LAYER_ONLY_ONE_SIDE", "items": []}
        else:
            text = textdiff.compare_lines(lb, la, spec["text_settings"], label)
            enc = prof_b["font_encoding_suspect"] or prof_a["font_encoding_suspect"]
            text["status"] = "PARTIAL_FONT_ENCODING_SUSPECT" if enc else "COMPARED_TEXT_LAYER_ONLY"
        result["text"] = text
        # ---------------- visual ----------------
        wb = float(cb[2] - cb[0]) if cb else float(pb.rect.width)
        hb = float(cb[3] - cb[1]) if cb else float(pb.rect.height)
        wa = float(ca[2] - ca[0]) if ca else float(pa.rect.width)
        ha = float(ca[3] - ca[1]) if ca else float(pa.rect.height)
        dpi = min(pdfio.plan_render(wb, hb, proc["preview_dpi"], proc["max_page_pixels"]),
                  pdfio.plan_render(wa, ha, proc["preview_dpi"], proc["max_page_pixels"]))
        vis: dict[str, Any] = {"dpi": dpi}
        if dpi < float(proc["min_visual_dpi"]):
            vis["status"] = "SKIPPED_PIXEL_LIMIT_PAGE_TOO_LARGE"
            result["visual"] = vis
            return result
        if abs(wb - wa) > 1.0 or abs(hb - ha) > 1.0:
            result["notes"].append("PAGE_OR_CLIP_SIZE_DIFFERS_ANCHORED_TOP_LEFT")
        img_b = _render_cached(pb, dpi, cb, cache_dir, spec["before_hash"], spec["before_page"])
        img_a = _render_cached(pa, dpi, ca, cache_dir, spec["after_hash"], spec["after_page"])
        vset = dict(spec["visual_settings"])
        tshift = text.get("text_canvas_shift") if isinstance(text, dict) else None
        if tshift:
            vset["_hint_shift_px"] = [tshift["dx_pt"] * dpi / 72.0, tshift["dy_pt"] * dpi / 72.0]
        cmp = visual.compare_images(img_b, img_a, vset)
        a_arr, b_al = cmp.pop("_a"), cmp.pop("_b_aligned")
        if cmp["canvas_shift_px"] and img_b.shape == a_arr.shape:
            # Exact shift from PDF text coordinates when available, else re-render search.
            if tshift and tshift.get("anchor_lines", 0) >= 2:
                s_px = (tshift["dx_pt"] * dpi / 72.0, tshift["dy_pt"] * dpi / 72.0)
                shift_source = "TEXT_COORDINATES"
            else:
                s_px = _refine_by_rerender(img_b, pa, dpi, ca, cb, tuple(cmp["canvas_shift_px"]),
                                           int(vset.get("pixel_threshold", 48)))
                shift_source = "RENDER_SEARCH"
            aligned = _aligned_after(pa, dpi, ca, cb, s_px, img_b.shape)
            cmp2 = visual.compare_images(img_b, aligned, {**vset, "_disable_shift": True})
            a2, b2 = cmp2.pop("_a"), cmp2.pop("_b_aligned")
            if cmp2["diff_pixels_after_canvas_shift"] <= cmp["diff_pixels_after_canvas_shift"]:
                cmp2["raw_diff_pixels"] = cmp["raw_diff_pixels"]
                cmp2["canvas_shift_px"] = [round(s_px[0], 3), round(s_px[1], 3)]
                cmp2["canvas_shift_source"] = shift_source
                cmp, a_arr, b_al = cmp2, a2, b2
            else:
                cmp["canvas_shift_source"] = "BILINEAR_ESTIMATE"
        scale = 72.0 / dpi
        shift = cmp["canvas_shift_px"]
        vis.update({k: v for k, v in cmp.items() if k != "regions"})
        vis["canvas_shift_pt"] = [round(shift[0] * scale, 2), round(shift[1] * scale, 2)] if shift else None
        vis["canvas_shift_mm"] = [round(shift[0] * scale * 25.4 / 72, 2), round(shift[1] * scale * 25.4 / 72, 2)] if shift else None
        # how much ink lies outside any extracted text line (text layer cannot cover it)
        ink = a_arr < 200
        total_ink = int(np.count_nonzero(ink))
        if total_ink:
            covered = np.zeros_like(ink)
            for line in lb:
                x0, y0, x1, y1 = (int(v / scale) for v in line["bbox"])
                covered[max(0, y0 - 1): y1 + 2, max(0, x0 - 1): x1 + 2] = True
            vis["before_ink_outside_text_lines_ratio"] = round(float(np.count_nonzero(ink & ~covered)) / total_ink, 4)
        sx_pt = vis["canvas_shift_pt"][0] if shift else 0.0
        sy_pt = vis["canvas_shift_pt"][1] if shift else 0.0
        regions_out = []
        fine_dpi = float(proc.get("fine_crop_dpi", 0) or 0)
        page_px = a_arr.shape[0] * a_arr.shape[1]
        h, w = a_arr.shape
        for reg in cmp["regions"]:
            x0, y0, x1, y1 = reg["box_px"]
            box_pt = [round(x0 * scale, 2), round(y0 * scale, 2), round(x1 * scale, 2), round(y1 * scale, 2)]
            box_pt_after = [round(box_pt[0] + sx_pt, 2), round(box_pt[1] + sy_pt, 2),
                            round(box_pt[2] + sx_pt, 2), round(box_pt[3] + sy_pt, 2)]
            linked = []
            for item in text.get("items", []):
                bb, ab = item.get("before_bbox_pt"), item.get("after_bbox_pt")
                if (bb and _intersects(bb, box_pt)) or (ab and _intersects(ab, box_pt_after)):
                    linked.append(item["id"])
            overlaps_text = any(_intersects(l["bbox"], box_pt) for l in lb) or \
                any(_intersects(l["bbox"], box_pt_after) for l in la)
            rid = f"{label}-V{reg['index']:03d}"
            pad = 12
            X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
            crop_b = img_dir / f"{rid}_before.png"
            crop_a = img_dir / f"{rid}_after.png"
            crops = {"resolution": "preview", "dpi": dpi}
            small = (x1 - x0) * (y1 - y0) <= page_px * float(spec["visual_settings"].get("fine_crop_max_region_fraction", 0.05))
            if fine_dpi > dpi and small:
                try:
                    nb = _fine_crop(pb, box_pt, cb, fine_dpi, int(proc["max_fine_crop_pixels"]), crop_b)
                    na = _fine_crop(pa, box_pt_after, ca, fine_dpi, int(proc["max_fine_crop_pixels"]), crop_a)
                    if nb and na:
                        crops = {"resolution": "fine", "dpi": fine_dpi}
                except Exception:
                    crops = {"resolution": "preview", "dpi": dpi}
            if crops["resolution"] == "preview":
                pdfio.save_png_gray(a_arr[Y0:Y1, X0:X1], crop_b)
                pdfio.save_png_gray(b_al[Y0:Y1, X0:X1], crop_a)
            crops.update({"before": crop_b.name, "after": crop_a.name})
            out = {
                "id": rid, "kind": reg["kind"], "diff_pixels": reg["diff_pixels"],
                "box_pt_before_frame": box_pt, "box_pt_after_frame": box_pt_after,
                "linked_text_change_ids": linked,
                "overlaps_text_layer": overlaps_text,
                "visual_only": not linked,
                "max_abs_diff": reg.get("max_abs_diff"),
                "low_contrast_edge_only": reg.get("low_contrast_edge_only", False),
                "crops": crops,
            }
            if reg.get("move_px"):
                out["move_pt"] = [round(reg["move_px"][0] * scale, 2), round(reg["move_px"][1] * scale, 2)]
                out["paired_region"] = f"{label}-V{reg['paired_with']:03d}" if reg.get("paired_with") else None
                out["move_match_score"] = reg.get("move_match_score")
            regions_out.append(out)
        vis["regions"] = regions_out
        overlay = img_dir / f"{label}_overlay.png"
        pdfio.save_png_rgb(visual.overlay_rgb(a_arr, b_al, cmp["regions"]), overlay)
        vis["overlay"] = overlay.name
        vis["status"] = "COMPARED_CANDIDATES_ONLY"
        result["visual"] = vis
        return result
    finally:
        doc_b.close()
        doc_a.close()


def run_and_save(spec: dict[str, Any]) -> None:
    """Entry point for a child process: never prints, writes result JSON."""
    install_network_guard()
    quiet_pdf_library()
    out = Path(spec["page_dir"]) / f"{spec['label']}.json"
    try:
        result = process_page(spec)
        result["status"] = "DONE"
    except FinalError as err:
        result = {"label": spec["label"], "status": "FAILED", "error_code": err.code}
    except MemoryError:
        result = {"label": spec["label"], "status": "FAILED", "error_code": "OUT_OF_MEMORY"}
    except Exception as err:  # noqa: BLE001
        result = {"label": spec["label"], "status": "FAILED", "error_code": "PAGE_PROCESSING_ERROR",
                  "error_type": type(err).__name__}
    atomic_write_json(out, result)


def child_main(spec_json: str) -> None:  # pragma: no cover - used by spawn
    run_and_save(json.loads(spec_json))
