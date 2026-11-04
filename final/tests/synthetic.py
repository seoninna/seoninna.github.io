"""Synthetic artwork PDFs for tests and the demo. Every file created here is a
TEST FIXTURE (가상 합성 자료), not company artwork. Product names are invented."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf  # type: ignore

SEG = {  # 7-segment digits drawn as filled vector rectangles (= "outlined" text, no text layer)
    "0": "abcfed", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
    "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
}


def _seg_rects(x: float, y: float, h: float, ch: str) -> list[pymupdf.Rect]:
    w, t = h * 0.55, h * 0.12
    half = h / 2
    parts = {
        "a": (x, y, x + w, y + t), "g": (x, y + half - t / 2, x + w, y + half + t / 2), "d": (x, y + h - t, x + w, y + h),
        "f": (x, y, x + t, y + half), "b": (x + w - t, y, x + w, y + half),
        "e": (x, y + half, x + t, y + h), "c": (x + w - t, y + half, x + w, y + h),
    }
    return [pymupdf.Rect(parts[s]) for s in SEG.get(ch, "")]


def draw_page(doc: pymupdf.Document, spec: dict[str, Any], shift: tuple[float, float] = (0, 0)) -> None:
    w, h = spec.get("size", (420, 300))
    page = doc.new_page(width=w, height=h)
    dx, dy = shift
    for x, y, text, fs in spec.get("texts", []):
        page.insert_text((x + dx, y + dy), text, fontname="korea", fontsize=fs)
    for rect, fill in spec.get("rects", []):
        r = pymupdf.Rect(rect) + (dx, dy, dx, dy)
        page.draw_rect(r, color=fill, fill=fill)
    for x, y, digits, size in spec.get("seg_digits", []):
        cx = x + dx
        for ch in digits:
            for r in _seg_rects(cx, y + dy, size, ch):
                page.draw_rect(r, color=(0, 0, 0), fill=(0, 0, 0))
            cx += size * 0.75
    for x, y, text, fs in spec.get("image_texts", []):
        tmp = pymupdf.open()
        tp = tmp.new_page(width=fs * len(text) * 1.1 + 10, height=fs * 1.6)
        tp.insert_text((4, fs * 1.15), text, fontname="korea", fontsize=fs)
        pix = tp.get_pixmap(dpi=200)
        page.insert_image(pymupdf.Rect(x + dx, y + dy, x + dx + tp.rect.width, y + dy + tp.rect.height), pixmap=pix)
        tmp.close()


def build_pdf(path: Path, pages: list[dict[str, Any]], shift: tuple[float, float] = (0, 0),
              encrypt: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for spec in pages:
        draw_page(doc, spec, shift)
    doc.set_metadata({"title": "SYNTHETIC TEST FIXTURE", "subject": "FINAL? synthetic artwork, not real"})
    if encrypt:
        doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="test", owner_pw="test-owner")
    else:
        doc.save(str(path))
    doc.close()
    return path


LOGO = ((300, 30, 380, 70), (0.1, 0.3, 0.6))


def base_page(**over: Any) -> dict[str, Any]:
    spec = {
        "size": (420, 300),
        "texts": [
            (30, 50, "가상크림 모이스처 GX-120", 14),
            (30, 80, "내용량 50ml", 11),
            (30, 105, "사용기한 2027.11.04", 10),
            (30, 130, "피부 보습에 도움을 줍니다", 10),
            (30, 155, "제조번호 LOT A1234", 9),
        ],
        "rects": [LOGO],
    }
    spec.update(over)
    return spec


def with_text(spec: dict[str, Any], old: str, new: str | None) -> dict[str, Any]:
    texts = []
    for x, y, t, fs in spec["texts"]:
        if t == old:
            if new is not None:
                texts.append((x, y, new, fs))
        else:
            texts.append((x, y, t, fs))
    return {**spec, "texts": texts}
