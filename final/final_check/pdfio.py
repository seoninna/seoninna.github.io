"""Read-only PDF access with page-wise processing and pixel limits.

PyMuPDF opens files read-only here; this module never calls save/ez_save on
source documents. Rendering is done one page (or one clip) at a time and the
pixel count is capped by config before any pixmap is allocated.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from .common import FinalError

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        pymupdf = None  # type: ignore

BAD_CHAR_RE = re.compile("[�-]")


def require_pdf_library() -> None:
    if pymupdf is None:
        raise FinalError("PYMUPDF_NOT_INSTALLED_RUN_PIP_INSTALL_REQUIREMENTS")


def open_pdf(path: Path) -> Any:
    require_pdf_library()
    try:
        doc = pymupdf.open(str(path), filetype="pdf")
    except Exception:
        raise FinalError("PDF_OPEN_FAILED_DAMAGED_OR_NOT_PDF") from None
    if doc.needs_pass or doc.is_encrypted:
        doc.close()
        raise FinalError("PDF_ENCRYPTED_UNVERIFIABLE")
    if doc.page_count == 0:
        doc.close()
        raise FinalError("PDF_HAS_NO_PAGES")
    return doc


def rect_list(r: Any) -> list[float]:
    return [round(float(r.x0), 2), round(float(r.y0), 2), round(float(r.x1), 2), round(float(r.y1), 2)]


def page_info(page: Any) -> dict[str, Any]:
    info: dict[str, Any] = {
        "page_number": page.number + 1,
        "rect_pt": rect_list(page.rect),
        "width_pt": round(float(page.rect.width), 2),
        "height_pt": round(float(page.rect.height), 2),
        "rotation": int(page.rotation),
        "mediabox_pt": rect_list(page.mediabox),
        "cropbox_pt": rect_list(page.cropbox),
    }
    for name in ("trimbox", "bleedbox", "artbox"):
        try:
            box = getattr(page, name)
            info[f"{name}_pt"] = rect_list(box)
        except Exception:
            info[f"{name}_pt"] = None
    trim = info.get("trimbox_pt")
    info["trimbox_differs_from_cropbox"] = bool(trim and trim != info["cropbox_pt"])
    return info


def _to_display(page: Any, bbox: tuple[float, float, float, float]) -> list[float]:
    r = pymupdf.Rect(bbox)
    if page.rotation:
        r = r * page.rotation_matrix
    return [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)]


def _clip_rect(clip: list[float] | None) -> Any:
    return pymupdf.Rect(clip) if clip else None


def text_lines(page: Any, clip: list[float] | None = None) -> list[dict[str, Any]]:
    """Lines in display coordinates (pt), relative to the clip origin."""
    flags = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_MEDIABOX_CLIP
    data = page.get_text("dict", flags=flags)
    clip_r = _clip_rect(clip)
    ox, oy = (clip_r.x0, clip_r.y0) if clip_r else (0.0, 0.0)
    lines: list[dict[str, Any]] = []
    order = 0
    for block in data.get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if not text.strip():
                continue
            bbox = _to_display(page, tuple(line["bbox"]))
            if clip_r is not None:
                cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
                if not (clip_r.x0 <= cx <= clip_r.x1 and clip_r.y0 <= cy <= clip_r.y1):
                    continue
            sizes = [round(float(s.get("size", 0)), 2) for s in line.get("spans", [])]
            lines.append({
                "order": order,
                "text": text,
                "bbox": [round(bbox[0] - ox, 2), round(bbox[1] - oy, 2), round(bbox[2] - ox, 2), round(bbox[3] - oy, 2)],
                "font_size": max(sizes) if sizes else None,
                "bad_chars": len(BAD_CHAR_RE.findall(text)),
            })
            order += 1
    return lines


def content_profile(page: Any, lines: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Classify what the text layer can and cannot cover. Hints, not proof."""
    if lines is None:
        lines = text_lines(page)
    chars = sum(len(l["text"].strip()) for l in lines)
    bad = sum(l["bad_chars"] for l in lines)
    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    image_area = 0.0
    image_count = 0
    try:
        for info in page.get_image_info():
            image_count += 1
            r = pymupdf.Rect(info["bbox"]) & page.rect
            image_area += max(0.0, float(r.width * r.height))
    except Exception:
        pass
    try:
        drawings = len(page.get_cdrawings())
    except Exception:
        drawings = -1
    image_ratio = round(min(image_area / page_area, 1.0), 4)
    if chars == 0 and image_count == 0 and drawings <= 0:
        cls = "EMPTY_OR_UNREADABLE"
    elif chars == 0 and image_count > 0 and drawings <= 2:
        cls = "IMAGE_ONLY"
    elif chars == 0:
        cls = "NO_TEXT_LAYER_OUTLINE_OR_GRAPHICS"
    elif image_ratio > 0.02 or drawings > 50:
        cls = "MIXED_TEXT_AND_GRAPHICS"
    else:
        cls = "TEXT_LAYER_PRESENT"
    return {
        "text_chars": chars,
        "bad_or_private_use_chars": bad,
        "image_count": image_count,
        "image_area_ratio": image_ratio,
        "vector_drawing_count": drawings,
        "content_class": cls,
        "font_encoding_suspect": bad > 0,
    }


def plan_render(width_pt: float, height_pt: float, wanted_dpi: float, max_pixels: int) -> float:
    """Highest dpi <= wanted_dpi whose pixel count stays <= max_pixels."""
    area_in2 = max(width_pt / 72.0, 1e-6) * max(height_pt / 72.0, 1e-6)
    cap = math.sqrt(max_pixels / area_in2)
    return float(min(wanted_dpi, math.floor(cap * 100) / 100))


def render_gray(page: Any, dpi: float, clip: list[float] | None = None) -> np.ndarray:
    zoom = float(dpi) / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=_clip_rect(clip), colorspace=pymupdf.csGRAY, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, : pix.width].copy()
    del pix
    return arr


def save_png_gray(arr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    a = np.ascontiguousarray(arr, dtype=np.uint8)
    pix = pymupdf.Pixmap(pymupdf.csGRAY, a.shape[1], a.shape[0], a.tobytes(), False)
    pix.save(str(path))


def save_png_rgb(arr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    a = np.ascontiguousarray(arr, dtype=np.uint8)
    pix = pymupdf.Pixmap(pymupdf.csRGB, a.shape[1], a.shape[0], a.tobytes(), False)
    pix.save(str(path))


def artboard_hint(page: Any, clip: list[float] | None = None) -> int:
    """Rough count of separated content panels on a page (low-res, hint only)."""
    dpi = plan_render(float(page.rect.width), float(page.rect.height), 18, 400_000)
    img = render_gray(page, dpi, clip)
    ink = img < 235
    if not ink.any():
        return 0
    def runs(profile: np.ndarray, min_gap: int) -> int:
        count, in_run, gap = 0, False, 0
        for value in profile:
            if value:
                if not in_run:
                    count += 1
                in_run, gap = True, 0
            else:
                gap += 1
                if gap >= min_gap:
                    in_run = False
        return count
    cols = runs(ink.any(axis=0), max(3, img.shape[1] // 40))
    rows = runs(ink.any(axis=1), max(3, img.shape[0] // 40))
    return int(cols * rows)
