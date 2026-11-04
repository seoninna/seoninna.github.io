#!/usr/bin/env python3
"""FINAL? 로컬 사전 점검 (원본을 변경하지 않음).

  python local_preflight.py --env-only                 # 설치 상태만 확인 (원화 폴더 접근 없음)
  python local_preflight.py --config config.local.json # 폴더 구조·파일 목록·PDF 구조 점검

PDF는 읽기 전용으로 한 파일씩 열어 페이지 수·크기·회전·텍스트 레이어 유무만 확인합니다.
결과는 output_dir/preflight/ 에 저장되고, 화면에는 건수와 오류 코드만 출력됩니다.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from final_check import layout, pdfio  # noqa: E402
from final_check.common import (ENGINE_VERSION, FinalError, atomic_write_json, ensure_output_dir,  # noqa: E402
                                load_local_config, network_guard_active, now_iso, run_cli)


def env_check() -> dict:
    info = {"engine_version": ENGINE_VERSION, "python": sys.version.split()[0], "network_guard": network_guard_active()}
    try:
        import numpy
        info["numpy"] = numpy.__version__
    except ImportError:
        raise FinalError("NUMPY_NOT_INSTALLED_RUN_PIP_INSTALL_REQUIREMENTS") from None
    pdfio.require_pdf_library()
    info["pymupdf"] = getattr(pdfio.pymupdf, "VersionBind", getattr(pdfio.pymupdf, "__version__", "?"))
    if sys.version_info < (3, 9):
        raise FinalError("PYTHON_3_9_OR_NEWER_REQUIRED")
    return info


def main() -> dict:
    ap = argparse.ArgumentParser(description="FINAL? local preflight (read-only)")
    ap.add_argument("--config", default="config.local.json")
    ap.add_argument("--env-only", action="store_true")
    ap.add_argument("--no-pdf-open", action="store_true", help="파일 목록만, PDF 내부 구조는 열지 않음")
    ap.add_argument("--max-files", type=int, default=0, help="0=전체. 테스트로 일부만 열 때 사용")
    args = ap.parse_args()
    env = env_check()
    if args.env_only:
        return {"ok": True, "environment": env, "source_accessed": False}
    cfg = load_local_config(args.config)
    files, skipped, _ = layout.scan_all(cfg)
    out = ensure_output_dir(cfg) / "preflight"
    counts = {"pdf_files": len(files), "by_category_side": {}, "file_states": {}, "content_classes": {},
              "pdf_errors": {}, "pages_total": 0, "large_files_over_warning": 0, "multi_artboard_hint_pages": 0,
              "rotated_pages": 0, "trimbox_set_pages": 0, "skipped": skipped}
    warn_bytes = float(cfg["file_rules"]["file_size_warning_mb"]) * 1024 * 1024
    opened = 0
    started = time.time()
    for rec in files:
        key = f"{rec['category_code']}/{rec['side']}"
        counts["by_category_side"][key] = counts["by_category_side"].get(key, 0) + 1
        counts["file_states"][rec["file_state"]] = counts["file_states"].get(rec["file_state"], 0) + 1
        if rec["size_bytes"] > warn_bytes:
            counts["large_files_over_warning"] += 1
        if args.no_pdf_open or rec["file_state"] != "STABLE" or (args.max_files and opened >= args.max_files):
            rec["pdf_checked"] = False
            continue
        opened += 1
        path = cfg["_root"] / rec["root_relative_path"]
        try:
            doc = pdfio.open_pdf(path)
        except FinalError as err:
            rec["pdf_error"] = err.code
            counts["pdf_errors"][err.code] = counts["pdf_errors"].get(err.code, 0) + 1
            continue
        try:
            rec["page_count"] = doc.page_count
            rec["repaired_on_open"] = bool(getattr(doc, "is_repaired", False))
            pages = []
            for page in doc:  # one page at a time
                info = pdfio.page_info(page)
                prof = pdfio.content_profile(page)
                info.update(prof)
                if cfg["processing"].get("artboard_hint"):
                    try:
                        info["artboard_hint"] = pdfio.artboard_hint(page)
                    except Exception:
                        info["artboard_hint"] = None
                if (info.get("artboard_hint") or 0) > 1:
                    counts["multi_artboard_hint_pages"] += 1
                if info["rotation"]:
                    counts["rotated_pages"] += 1
                if info["trimbox_differs_from_cropbox"]:
                    counts["trimbox_set_pages"] += 1
                counts["content_classes"][prof["content_class"]] = counts["content_classes"].get(prof["content_class"], 0) + 1
                pages.append(info)
            counts["pages_total"] += len(pages)
            rec["pages"] = pages
            rec["pdf_checked"] = True
        finally:
            doc.close()
    atomic_write_json(out / "preflight.private.json", {
        "classification": "LOCAL_PRIVATE_DO_NOT_UPLOAD", "generated_at": now_iso(), "environment": env,
        "files": files, "counts": counts,
        "notes": ["content_class와 artboard_hint는 힌트입니다. 실제 검수 가능 범위는 비교 보고서의 coverage를 따릅니다."]})
    summary = {"ok": True, "pdf_opened": opened, "seconds": round(time.time() - started, 1), **counts}
    atomic_write_json(out / "preflight_summary.json", summary)
    return summary


if __name__ == "__main__":
    sys.exit(run_cli(main))
