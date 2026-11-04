"""Comparison core shared by the LOCAL_ONLY CLI/API and the separate
APPROVED_EXTERNAL_B service. It works on two file paths that the caller has
already validated; it never decides which files form a pair."""
from __future__ import annotations

import multiprocessing as mp
import re
import time
from pathlib import Path
from typing import Any

from . import pdfio, requests_eval
from .common import ENGINE_VERSION, FinalError, atomic_write_json, now_iso, read_json
from .page_worker import process_page, run_and_save

NOT_CHECKED = [
    "색상·CMYK·별색(Pantone)·오버프린트",
    "재단선·도련·인쇄 적합성",
    "바코드 스캔 가능 여부·인쇄 품질",
    "법적 표시사항의 적정성(내용 판단)",
    "텍스트 레이어가 없는 영역의 문자 내용(OCR 미사용)",
]


def _page_tokens(page: Any) -> set[str]:
    try:
        return set(re.findall(r"\S+", page.get_text("text")))
    except Exception:
        return set()


def build_mapping(doc_b: Any, doc_a: Any, page_map: list[dict[str, Any]] | None) -> dict[str, Any]:
    nb, na = doc_b.page_count, doc_a.page_count
    entries: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    suggestion: list[dict[str, Any]] = []
    source = None
    if page_map:
        source = "MANIFEST_PAGE_MAP_CONFIRMED_BY_HUMAN"
        used_b, used_a = set(), set()
        for i, m in enumerate(page_map, 1):
            b, a = m.get("before_page"), m.get("after_page")
            if b in (None, "-") or a in (None, "-"):
                unmapped.append({"before_page": b if b not in ("-",) else None, "after_page": a if a not in ("-",) else None,
                                 "reason": "NO_COUNTERPART_PER_PAGE_MAP"})
                continue
            b, a = int(b), int(a)
            if not (1 <= b <= nb and 1 <= a <= na):
                raise FinalError("PAGE_MAP_PAGE_OUT_OF_RANGE")
            used_b.add(b)
            used_a.add(a)
            entries.append({"label": f"M{i:03d}", "before_page": b, "after_page": a,
                            "before_clip": m.get("before_clip"), "after_clip": m.get("after_clip")})
        for b in range(1, nb + 1):
            if b not in used_b and not any(u.get("before_page") == b for u in unmapped):
                unmapped.append({"before_page": b, "after_page": None, "reason": "NOT_IN_PAGE_MAP"})
        for a in range(1, na + 1):
            if a not in used_a and not any(u.get("after_page") == a for u in unmapped):
                unmapped.append({"before_page": None, "after_page": a, "reason": "NOT_IN_PAGE_MAP"})
        return {"source": source, "entries": entries, "unmapped": unmapped, "suggested_page_map": []}
    if nb == na:
        source = "AUTO_SAME_PAGE_COUNT_AND_SIZE"
        for i in range(nb):
            rb, ra = doc_b[i].rect, doc_a[i].rect
            if abs(rb.width - ra.width) > 1 or abs(rb.height - ra.height) > 1 or doc_b[i].rotation != doc_a[i].rotation:
                unmapped.append({"before_page": i + 1, "after_page": i + 1, "reason": "PAGE_MAP_REQUIRED_SIZE_OR_ROTATION_CHANGED"})
            else:
                entries.append({"label": f"M{i + 1:03d}", "before_page": i + 1, "after_page": i + 1})
    else:
        source = "NONE_PAGE_COUNT_CHANGED"
        for i in range(nb):
            unmapped.append({"before_page": i + 1, "after_page": None, "reason": "PAGE_MAP_REQUIRED_PAGE_COUNT_CHANGED"})
        for j in range(na):
            unmapped.append({"before_page": None, "after_page": j + 1, "reason": "PAGE_MAP_REQUIRED_PAGE_COUNT_CHANGED"})
    if unmapped:
        tb = [_page_tokens(doc_b[i]) for i in range(nb)]
        ta = [_page_tokens(doc_a[j]) for j in range(na)]
        for i in range(nb):
            best = None
            for j in range(na):
                if not tb[i] or not ta[j]:
                    continue
                jac = len(tb[i] & ta[j]) / max(1, len(tb[i] | ta[j]))
                if best is None or jac > best[0]:
                    best = (jac, j)
            if best and best[0] >= 0.3:
                suggestion.append({"before_page": i + 1, "after_page": best[1] + 1, "text_similarity": round(best[0], 3),
                                   "status": "SUGGESTION_NOT_CONFIRMED"})
    return {"source": source, "entries": entries, "unmapped": unmapped, "suggested_page_map": suggestion}


def _run_isolated(spec: dict[str, Any], timeout: float) -> dict[str, Any]:
    out = Path(spec["page_dir"]) / f"{spec['label']}.json"
    if out.exists():
        out.unlink()
    ctx = mp.get_context("spawn")
    proc = ctx.Process(target=run_and_save, args=(spec,), daemon=True)
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        return {"label": spec["label"], "status": "FAILED", "error_code": "PAGE_TIMEOUT"}
    data = read_json(out)
    if not data:
        return {"label": spec["label"], "status": "FAILED", "error_code": "PAGE_WORKER_CRASHED",
                "exit_code": proc.exitcode}
    return data


def _run_inline(spec: dict[str, Any]) -> dict[str, Any]:
    try:
        res = process_page(spec)
        res["status"] = "DONE"
        return res
    except FinalError as err:
        return {"label": spec["label"], "status": "FAILED", "error_code": err.code}
    except MemoryError:
        return {"label": spec["label"], "status": "FAILED", "error_code": "OUT_OF_MEMORY"}
    except Exception as err:  # noqa: BLE001
        return {"label": spec["label"], "status": "FAILED", "error_code": "PAGE_PROCESSING_ERROR",
                "error_type": type(err).__name__}


def compare_files(*, before_path: Path, after_path: Path, before_hash: str, after_hash: str,
                  pair: dict[str, Any], requests_data: dict[str, Any] | None, cfg: dict[str, Any],
                  job_dir: Path, report_dir: Path, cache_dir: Path | None, max_pages: int | None = None) -> dict[str, Any]:
    proc = cfg["processing"]
    started = time.time()
    page_dir = job_dir / "pages"
    image_dir = report_dir / "images"
    page_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    doc_b = pdfio.open_pdf(before_path)
    try:
        doc_a = pdfio.open_pdf(after_path)
    except FinalError:
        doc_b.close()
        raise
    try:
        docinfo = {
            "before": {"page_count": doc_b.page_count, "repaired_on_open": bool(getattr(doc_b, "is_repaired", False))},
            "after": {"page_count": doc_a.page_count, "repaired_on_open": bool(getattr(doc_a, "is_repaired", False))},
        }
        mapping = build_mapping(doc_b, doc_a, pair.get("page_map") or None)
    finally:
        doc_b.close()
        doc_a.close()
    limit = int(max_pages or proc.get("max_pages_per_file", 400))
    entries = mapping["entries"]
    over_limit = entries[limit:]
    entries = entries[:limit]
    unprocessed = list(mapping["unmapped"]) + [
        {"before_page": e["before_page"], "after_page": e["after_page"], "reason": "UNPROCESSED_PAGE_LIMIT"} for e in over_limit
    ]
    pages: list[dict[str, Any]] = []
    attempts_log = []
    retries = int(proc.get("max_retries", 2))
    timeout = float(proc.get("page_timeout_seconds", 240))
    for e in entries:
        cached = read_json(page_dir / f"{e['label']}.json")
        if cached and cached.get("status") == "DONE":
            cached["from_cache"] = True
            pages.append({**e, **cached})
            continue
        spec = {
            **e, "before_path": str(before_path), "after_path": str(after_path),
            "before_hash": before_hash, "after_hash": after_hash,
            "page_dir": str(page_dir), "image_dir": str(image_dir),
            "cache_dir": str(cache_dir) if cache_dir else None,
            "processing": proc, "text_settings": cfg["text"], "visual_settings": cfg["visual"],
        }
        result: dict[str, Any] = {}
        for attempt in range(1, retries + 2):
            if proc.get("page_isolation") == "process":
                result = _run_isolated(spec, timeout)
            else:
                result = _run_inline(spec)
                atomic_write_json(page_dir / f"{e['label']}.json", result)
            result["attempts"] = attempt
            if result.get("status") == "DONE":
                break
        atomic_write_json(page_dir / f"{e['label']}.json", result)
        attempts_log.append({"label": e["label"], "attempts": result.get("attempts"), "status": result.get("status"),
                             "error_code": result.get("error_code")})
        if result.get("status") != "DONE":
            unprocessed.append({"before_page": e["before_page"], "after_page": e["after_page"],
                                "reason": result.get("error_code", "FAILED")})
        pages.append({**e, **result})
    req = requests_eval.evaluate(requests_data, pages, before_hash, pair)
    outside = requests_eval.outside_scope(requests_data, pages)
    return assemble(pair=pair, before_hash=before_hash, after_hash=after_hash, docinfo=docinfo, mapping=mapping,
                    pages=pages, unprocessed=unprocessed, req=req, outside=outside, attempts=attempts_log,
                    seconds=time.time() - started)


def assemble(**kw: Any) -> dict[str, Any]:
    pages = kw["pages"]
    done = [p for p in pages if p.get("status") == "DONE"]
    text_counts: dict[str, int] = {}
    vis_counts: dict[str, int] = {}
    numeric = 0
    text_unverifiable = []
    visual_skipped = []
    canvas_shifts = []
    for p in done:
        t = p.get("text") or {}
        if str(t.get("status", "")).startswith(("UNVERIFIABLE", "PARTIAL")):
            text_unverifiable.append({"label": p["label"], "after_page": p["after_page"], "status": t.get("status")})
        for item in t.get("items", []):
            text_counts[item["kind"]] = text_counts.get(item["kind"], 0) + 1
            numeric += 1 if item.get("numeric_change") else 0
        v = p.get("visual") or {}
        if v.get("status") != "COMPARED_CANDIDATES_ONLY":
            visual_skipped.append({"label": p["label"], "after_page": p["after_page"], "status": v.get("status")})
        if v.get("canvas_shift_pt"):
            canvas_shifts.append({"label": p["label"], "shift_pt": v["canvas_shift_pt"], "shift_mm": v.get("canvas_shift_mm")})
        for reg in v.get("regions", []):
            vis_counts[reg["kind"]] = vis_counts.get(reg["kind"], 0) + 1
        if v.get("regions_truncated"):
            visual_skipped.append({"label": p["label"], "after_page": p["after_page"], "status": "REGIONS_TRUNCATED",
                                   "count": v["regions_truncated"]})
    total_pages = max(kw["docinfo"]["before"]["page_count"], kw["docinfo"]["after"]["page_count"])
    if not done:
        overall = "UNVERIFIABLE_NOTHING_COMPARED"
    elif kw["unprocessed"] or text_unverifiable or visual_skipped:
        overall = "PARTIAL_COVERAGE"
    else:
        overall = "COMPARED_WITH_LIMITATIONS"
    req = kw["req"]
    rc = {}
    for c in req.get("request_checks", []) + req.get("protected_checks", []):
        rc[c["status"]] = rc.get(c["status"], 0) + 1
    return {
        "schema_version": "3.0",
        "engine_version": ENGINE_VERSION,
        "generated_at": now_iso(),
        "overall_status": overall,
        "final_approval": False,
        "pair": {k: kw["pair"].get(k) for k in ("pair_id", "category", "category_code", "artwork_id",
                                                "before_relative_path", "after_relative_path")},
        "hashes": {"before_sha256": kw["before_hash"], "after_sha256": kw["after_hash"]},
        "documents": kw["docinfo"],
        "page_mapping": {"source": kw["mapping"]["source"], "compared": [
            {"label": p["label"], "before_page": p["before_page"], "after_page": p["after_page"],
             "before_clip_pt": p.get("before_clip"), "after_clip_pt": p.get("after_clip")} for p in pages],
            "suggested_page_map": kw["mapping"]["suggested_page_map"]},
        "coverage": {
            "pages_in_larger_document": total_pages,
            "mapped_entries": len(pages),
            "entries_compared": len(done),
            "unprocessed": kw["unprocessed"],
            "text_unverifiable_or_partial": text_unverifiable,
            "visual_skipped": visual_skipped,
        },
        "canvas_shifts": canvas_shifts,
        "counts": {"text_changes_by_kind": text_counts, "numeric_text_changes": numeric,
                   "visual_candidates_by_kind": vis_counts, "request_statuses": rc},
        "requests": req,
        "outside_request_scope": kw["outside"],
        "not_checked": NOT_CHECKED,
        "attempts": kw["attempts"],
        "processing_seconds": round(kw["seconds"], 2),
        "pages": pages,
    }
