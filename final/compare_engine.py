#!/usr/bin/env python3
"""FINAL? 로컬 비교 엔진 (LOCAL_ONLY, 외부 AI·네트워크 호출 없음).

  python compare_engine.py --config config.local.json --pair-id SET_0123456789
  python compare_engine.py --config config.local.json --list-pending
  python compare_engine.py --config config.local.json --pending          # 승인된 짝 중 새 수정본 모두 비교
  python compare_engine.py --config config.local.json --record-delivery RUN_KEY --delivery-status LOCAL_ONLY_NOT_SENT

상세 보고서: output_dir/reports/<pair_id>/<run_key>/report.private.html (로컬 전용)
화면 출력: 상태 코드와 건수만.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from final_check.common import load_local_config, run_cli  # noqa: E402
from final_check.local_runner import find_pending, record_delivery, run_pair  # noqa: E402


def _console(result: dict) -> dict:
    """Strip the notification body; keep only codes and counts for the console."""
    out = {k: v for k, v in result.items() if k not in ("safe_notification",)}
    if "summary" in out and isinstance(out["summary"], dict):
        s = out["summary"]
        out["summary"] = {k: s.get(k) for k in ("overall_status", "request_status", "text_changes_by_kind",
                                                 "numeric_text_changes", "visual_candidates_by_kind", "entries_compared",
                                                 "unprocessed_entries", "text_unverifiable_or_partial_entries",
                                                 "visual_skipped_entries", "request_status_counts", "pdf_report")}
    if result.get("status") == "COMPARED":
        out["report"] = "output_dir/reports/<pair_id>/<run_key>/report.private.html"
    return out


def main() -> dict:
    ap = argparse.ArgumentParser(description="FINAL? local compare engine")
    ap.add_argument("--config", default="config.local.json")
    ap.add_argument("--pair-id")
    ap.add_argument("--event-id")
    ap.add_argument("--force", action="store_true", help="같은 내용이라도 다시 비교")
    ap.add_argument("--max-pages", type=int)
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--list-pending", action="store_true")
    ap.add_argument("--record-delivery", metavar="RUN_KEY")
    ap.add_argument("--delivery-status")
    ap.add_argument("--message-id")
    args = ap.parse_args()
    cfg = load_local_config(args.config)
    if args.record_delivery:
        return record_delivery(cfg, args.record_delivery, args.delivery_status or "", args.message_id)
    if args.list_pending:
        return find_pending(cfg)
    if args.pending:
        pend = find_pending(cfg)
        results = []
        for item in pend["pending"]:
            try:
                r = run_pair(cfg, item["pair_id"], event_id=item["event_id"], max_pages=args.max_pages)
                results.append({"pair_id": item["pair_id"], "status": r.get("status") or r.get("error_code"),
                                "run_key": r.get("run_key"),
                                "overall_status": (r.get("summary") or {}).get("overall_status")})
            except Exception as err:  # noqa: BLE001
                results.append({"pair_id": item["pair_id"], "status": getattr(err, "code", "UNEXPECTED_ERROR")})
        return {"ok": True, "processed": results, "waiting_not_stable": pend["waiting_not_stable"],
                "already_compared": pend["already_compared"], "errors": pend["errors"]}
    if not args.pair_id:
        return {"ok": False, "error_code": "PAIR_ID_REQUIRED_OR_USE_PENDING"}
    return _console(run_pair(cfg, args.pair_id, event_id=args.event_id, force=args.force, max_pages=args.max_pages))


if __name__ == "__main__":
    sys.exit(run_cli(main))
