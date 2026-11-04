#!/usr/bin/env python3
"""설치 확인용 합성(가상) 데모. 회사 원화를 사용하지 않습니다.

  python demo_synthetic.py --where ./demo

만드는 것:
  demo/synthetic_artwork/  가상 원화 PDF (세트·단품, before/after)  ← 테스트용 합성 자료
  demo/synthetic_results/  비교 결과 (보고서 HTML/PDF 포함)
  demo/config.demo.json    데모 설정
데모에서는 짝 승인을 자동으로 하지만(합성 자료이므로), 실제 원화에서는 사람이 승인해야 합니다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))

from final_check.common import FinalError, load_local_config, run_cli  # noqa: E402


def main() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--where", default="demo")
    args = ap.parse_args()
    from synthetic import LOGO, base_page, build_pdf, with_text

    base = Path(args.where).resolve()
    root = base / "synthetic_artwork"
    out = base / "synthetic_results"
    if root.exists() and any(root.rglob("*.pdf")):
        raise FinalError("DEMO_FOLDER_ALREADY_EXISTS_CHOOSE_ANOTHER_WHERE")
    old = time.time() - 3600
    b = base_page(texts=base_page()["texts"] + [(250, 230, "패널B 사용 방법", 9)])
    a = with_text(b, "피부 보습에 도움을 줍니다", "피부 보습과 진정에 도움을 줍니다")
    a = with_text(a, "사용기한 2027.11.04", "사용기한 2026.11.04")
    a = {**a, "rects": [((300, 100, 380, 140), LOGO[1])]}
    files = [
        (root / "세트" / "before" / "DEMO 가상세트 A100_v1.pdf", [b], (0, 0)),
        (root / "세트" / "after" / "DEMO 가상세트 A100_v2.pdf", [a], (0, 0)),
        (root / "단품" / "before" / "DEMO 가상단품 B200 50ml.pdf",
         [{"size": (300, 200), "texts": [(30, 40, "가상 단품 라벨", 12), (30, 60, "성분 정제수", 9)],
           "seg_digits": [(40, 100, "50", 18)], "rects": [LOGO]}], (0, 0)),
        (root / "단품" / "after" / "DEMO 가상단품 B200 50ml.pdf",
         [{"size": (300, 200), "texts": [(30, 40, "가상 단품 라벨", 12), (30, 60, "성분 정제수", 9)],
           "seg_digits": [(40, 100, "60", 18)], "rects": [LOGO]}], (6, 4)),
    ]
    for path, pages, shift in files:
        build_pdf(path, pages, shift=shift)
        os.utime(path, (old, old))
    cfg_path = base / "config.demo.json"
    cfg_path.write_text(json.dumps({"privacy_mode": "LOCAL_ONLY", "root_dir": str(root), "output_dir": str(out),
                                    "processing": {"page_isolation": "process"}}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    cfg = load_local_config(cfg_path)
    from final_check.local_runner import load_manifest, run_pair
    from pair_resolver import cmd_approve, cmd_scan

    scan = cmd_scan(cfg)
    results = []
    for p in load_manifest(cfg)["pairs"]:
        cmd_approve(cfg, type("A", (), {"pair_id": p["pair_id"], "artwork_id": "DEMO-" + p["category_code"],
                                        "by": "DEMO_AUTO_APPROVED_SYNTHETIC", "note": "합성 데모"})())
        if p["category_code"] == "SET":
            req_dir = cfg["_requests_dir"]
            req_dir.mkdir(parents=True, exist_ok=True)
            bh = next(x["before_content_sha256"] for x in load_manifest(cfg)["pairs"] if x["pair_id"] == p["pair_id"])
            (req_dir / f"{p['pair_id']}.json").write_text(json.dumps({
                "pair_id": p["pair_id"], "category": "세트",
                "baseline_content_sha256": bh,
                "requests": [
                    {"request_id": "R1", "requested_by": "BM", "source_reference": "DEMO 메일", "operation": "replace",
                     "page": 1, "before_value": "보습에", "after_value": "보습과 진정에"},
                    {"request_id": "R2", "requested_by": "DESIGNER", "source_reference": "DEMO 메일", "operation": "delete",
                     "page": 1, "before_value": "LOT A1234"}],
                "protected_fields": [{"field_id": "P1", "value": "2027.11.04", "page": 1, "previous_values": ["2026.11.04"]}],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        r = run_pair(cfg, p["pair_id"])
        results.append({"pair_id": p["pair_id"], "status": r.get("status"),
                        "overall_status": (r.get("summary") or {}).get("overall_status"),
                        "report": str(out / "reports" / p["pair_id"] / r["run_key"] / "report.private.html")})
    return {"ok": True, "synthetic_demo": True, "pairs_found": scan["candidates_unconfirmed"], "results": results,
            "note": "합성 자료 데모입니다. 실제 원화 검증이 아닙니다."}


if __name__ == "__main__":
    sys.exit(run_cli(main))
