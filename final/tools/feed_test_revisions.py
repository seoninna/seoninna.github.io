#!/usr/bin/env python3
"""TEST/DEMO ONLY: drop new synthetic after-revisions into the demo folder over time,
so n8n's Schedule Trigger has real new work on each automatic run.

  python tools/feed_test_revisions.py --where demo --count 5 --every-min 11

- Writes ONLY into <where>/synthetic_artwork created by demo_synthetic.py.
  Refuses any other folder, so it can never touch real artwork.
- Every file it writes is a synthetic fixture. Label runs fed by this tool as
  "합성 자료 자동 실행" in reports; do not present them as real artwork results.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tests"))

from synthetic import LOGO, base_page, build_pdf, with_text  # noqa: E402


def revisions(i: int):
    b = base_page(texts=base_page()["texts"] + [(250, 230, "패널B 사용 방법", 9)])
    single = lambda label, digits, extra: [{"size": (300, 200),  # noqa: E731
                                           "texts": [(30, 40, label, 12), (30, 60, extra, 9)],
                                           "seg_digits": [(40, 100, digits, 18)], "rects": [LOGO]}]
    plans = [
        ("세트", "DEMO 가상세트 A100_v2.pdf", [with_text(b, "내용량 50ml", f"내용량 {60 + i * 5}ml")]),
        ("단품", "DEMO 가상단품 B200 50ml.pdf", single("가상 단품 라벨", str(70 + i), "성분 정제수 글리세린")),
        ("세트", "DEMO 가상세트 A100_v2.pdf", [with_text(b, "사용기한 2027.11.04", f"사용기한 2027.{11 if i % 2 else 12}.0{i % 9 + 1}")]),
        ("단품", "DEMO 가상단품 B200 50ml.pdf", single("가상 단품 라벨 리뉴얼", "50", f"성분 정제수 {i}차")),
        ("세트", "DEMO 가상세트 A100_v2.pdf", [{**with_text(b, "제조번호 LOT A1234", None),
                                               "rects": [((300, 60 + i * 8, 380, 100 + i * 8), LOGO[1])]}]),
    ]
    return plans[i % len(plans)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--where", default="demo")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--every-min", type=float, default=11)
    args = ap.parse_args()
    root = Path(args.where).resolve() / "synthetic_artwork"
    cfg = Path(args.where).resolve() / "config.demo.json"
    if not cfg.exists() or json.loads(cfg.read_text(encoding="utf-8")).get("root_dir") != str(root):
        print(json.dumps({"ok": False, "error_code": "RUN_DEMO_SYNTHETIC_FIRST_THIS_TOOL_ONLY_WRITES_DEMO_FOLDER"}))
        return 2
    for i in range(args.count):
        cat, name, pages = revisions(i)
        build_pdf(root / cat / "after" / name, pages)
        print(json.dumps({"ok": True, "revision": i + 1, "of": args.count, "category": cat,
                          "written_at": datetime.now().strftime("%H:%M:%S"), "synthetic": True}, ensure_ascii=False),
              flush=True)
        if i + 1 < args.count:
            time.sleep(args.every_min * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
