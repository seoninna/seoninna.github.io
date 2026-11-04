#!/usr/bin/env python3
"""FINAL? 세트·단품별 before/after 짝 후보 생성과 사람 확인(승인).

  python pair_resolver.py scan    --config config.local.json
  python pair_resolver.py approve --config config.local.json --pair-id SET_0123456789 --artwork-id 내가정한ID --by 이름
  python pair_resolver.py add     --config config.local.json --category-code SET --before "세트/before/a.pdf" --after "세트/after/a.pdf"
  python pair_resolver.py set-page-map --config config.local.json --pair-id SET_0123456789 --map "1:1,2:3,3:-"
  python pair_resolver.py unapprove --config config.local.json --pair-id SET_0123456789
  python pair_resolver.py status  --config config.local.json

후보 목록(파일명 포함)은 output_dir/pairs/pair_candidates.private.html 에서 본인이 직접 확인합니다.
화면에는 pair_id와 건수만 출력됩니다. 파일명 유사도·수정일만으로 확정하지 않습니다.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from final_check import layout, pairing  # noqa: E402
from final_check.common import (FinalError, atomic_write_json, atomic_write_text, ensure_output_dir,  # noqa: E402
                                load_local_config, now_iso, run_cli, sha256_file)
from final_check.local_runner import get_pair, load_manifest, resolve_pair_paths, save_manifest  # noqa: E402


def _html(result: dict, manifest: dict) -> str:
    e = html.escape
    rows = []
    approved = {p["pair_id"]: p for p in manifest["pairs"]}
    rows.append("<!doctype html><meta charset='utf-8'><title>FINAL? 짝 후보</title><style>body{font-family:sans-serif;margin:20px}"
                "table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:5px;vertical-align:top}"
                "code{background:#f3f3f3;padding:1px 4px}.warn{color:#b00}</style>")
    rows.append("<h1>FINAL? before/after 짝 후보 (PRIVATE — 외부 공유 금지)</h1>"
                "<p>아래는 <b>파일 이름만으로 만든 후보</b>입니다. 같은 원화인지(코드·용량·구성·포장·국가) 직접 확인한 뒤 승인하세요. "
                "세트와 단품은 서로 짝지을 수 없습니다.</p>")
    rows.append("<h2>1. 후보 (승인 전)</h2><table><tr><th>pair_id</th><th>구분</th><th>before</th><th>after</th><th>근거</th><th>상태</th><th>승인 명령</th></tr>")
    for c in result["candidates"]:
        st = approved.get(c["pair_id"], {})
        state = "승인됨" if st.get("approved_for_comparison") else "미승인"
        warn = "" if c["after_file_state"] == "STABLE" and c["before_file_state"] == "STABLE" else \
            f"<div class='warn'>파일 상태: {e(c['before_file_state'])} / {e(c['after_file_state'])}</div>"
        cmd = f"python pair_resolver.py approve --config config.local.json --pair-id {c['pair_id']} --artwork-id (원화ID) --by (이름)"
        rows.append(f"<tr><td><code>{e(c['pair_id'])}</code></td><td>{e(c['category'])}</td><td>{e(c['before_relative_path'])}</td>"
                    f"<td>{e(c['after_relative_path'])}{warn}</td><td>{e(c['matching_basis'])}<br><small>후보 계산 때만 무시한 단어: {e(', '.join(c['stripped_words_for_candidate_only']))}</small></td>"
                    f"<td>{state}</td><td><code>{e(cmd)}</code></td></tr>")
    rows.append("</table><h2>2. PAIR_NEEDS_CONFIRMATION (자동으로 정하지 않음)</h2><table><tr><th>ID</th><th>사유</th><th>before</th><th>after 후보</th><th>직접 지정 명령</th></tr>")
    for i in result["issues"]:
        cands = "<br>".join(f"{e(a['after_relative_path'])} <small>({e(a['basis'])})</small>" for a in i["after_candidates"]) or "-"
        b = i.get("before_relative_path") or "-"
        after_col = cands if i["after_candidates"] else e(i.get("after_relative_path") or "-")
        cmd = f"python pair_resolver.py add --config config.local.json --category-code {i['category_code']} --before \"(before 상대경로)\" --after \"(after 상대경로)\""
        rows.append(f"<tr><td>{e(i['issue_id'])}</td><td>{e(i['reason'])}</td><td>{e(b)}</td>"
                    f"<td>{after_col}</td><td><code>{e(cmd)}</code></td></tr>")
    rows.append("</table><h2>3. 이름은 비슷하지만 차단된 조합</h2><p>용량·코드·국가·포장 단어가 달라 후보에서 제외했습니다 (file_id 기준).</p><ul>")
    for b in result["blocked_similar_names"]:
        rows.append(f"<li>{e(b['category_code'])}: {e(b['before_file_id'])} ↔ {e(b['after_file_id'])} — {e(', '.join(b['blocked_reasons']))}</li>")
    rows.append("</ul>")
    return "".join(rows)


def cmd_scan(cfg: dict) -> dict:
    files, skipped, _ = layout.scan_all(cfg)
    result = pairing.build_candidates(files, cfg["groups"], float(cfg["matching"].get("weak_similarity_threshold", 0.75)))
    manifest = load_manifest(cfg)
    known = {p["pair_id"] for p in manifest["pairs"]}
    added = 0
    for c in result["candidates"]:
        if c["pair_id"] not in known:
            manifest["pairs"].append({
                "pair_id": c["pair_id"], "category": c["category"], "category_code": c["category_code"],
                "artwork_id": None, "before_relative_path": c["before_relative_path"],
                "after_relative_path": c["after_relative_path"], "matching_basis": c["matching_basis"],
                "status": "CANDIDATE_UNCONFIRMED", "approved_for_comparison": False,
                "before_content_sha256": None, "after_content_sha256_at_approval": None,
                "approved_by": None, "approved_at": None, "page_map": [], "requests_file": None, "notes": "",
            })
            added += 1
    save_manifest(cfg, manifest)
    out = ensure_output_dir(cfg) / "pairs"
    atomic_write_json(out / "pair_candidates.private.json", {"classification": "LOCAL_PRIVATE_DO_NOT_UPLOAD",
                                                              "generated_at": now_iso(), **result, "skipped": skipped})
    atomic_write_text(out / "pair_candidates.private.html", _html(result, manifest))
    reasons: dict[str, int] = {}
    for i in result["issues"]:
        reasons[i["reason"]] = reasons.get(i["reason"], 0) + 1
    return {"pdf_files": len(files), "candidates_unconfirmed": len(result["candidates"]),
            "new_candidates_added_to_manifest": added, "pair_needs_confirmation": len(result["issues"]),
            "needs_confirmation_reasons": reasons, "blocked_similar_names": len(result["blocked_similar_names"]),
            "approved_pairs": sum(1 for p in manifest["pairs"] if p.get("approved_for_comparison")),
            "skipped": skipped, "next": "output_dir/pairs/pair_candidates.private.html 을 열어 확인 후 approve"}


def cmd_approve(cfg: dict, args) -> dict:
    if not args.artwork_id or not args.by:
        raise FinalError("ARTWORK_ID_AND_APPROVER_REQUIRED")
    manifest = load_manifest(cfg)
    pair = get_pair(manifest, args.pair_id)
    b, a = resolve_pair_paths(cfg, pair)
    for side, p in (("BEFORE", b), ("AFTER", a)):
        state = layout.file_state(cfg, p)
        if state != "STABLE":
            raise FinalError(f"{side}_FILE_{state}")
    pair.update({
        "artwork_id": args.artwork_id, "approved_by": args.by, "approved_at": now_iso(),
        "approved_for_comparison": True, "status": "APPROVED_FOR_COMPARISON",
        "before_content_sha256": sha256_file(b), "after_content_sha256_at_approval": sha256_file(a),
        "notes": args.note or pair.get("notes", ""),
    })
    save_manifest(cfg, manifest)
    return {"pair_id": pair["pair_id"], "approved_for_comparison": True,
            "meaning": "이 두 파일을 비교 대상으로 확인함. 원화 최종 승인이 아님."}


def cmd_add(cfg: dict, args) -> dict:
    group = next((g for g in cfg["groups"] if g["code"] == args.category_code), None)
    if not group:
        raise FinalError("UNKNOWN_CATEGORY_CODE")
    groups_dirs = layout.resolve_all_groups(cfg)
    b = layout.safe_source_path(cfg, groups_dirs, group["code"], "before", args.before)
    a = layout.safe_source_path(cfg, groups_dirs, group["code"], "after", args.after)
    br = b.relative_to(cfg["_root"]).as_posix()
    ar = a.relative_to(cfg["_root"]).as_posix()
    pid = pairing.pair_id_for(group["code"], br, ar)
    manifest = load_manifest(cfg)
    if any(p["pair_id"] == pid for p in manifest["pairs"]):
        return {"pair_id": pid, "already_in_manifest": True}
    manifest["pairs"].append({
        "pair_id": pid, "category": group["category"], "category_code": group["code"], "artwork_id": None,
        "before_relative_path": br, "after_relative_path": ar, "matching_basis": "MANUAL_BY_USER",
        "status": "CANDIDATE_UNCONFIRMED", "approved_for_comparison": False, "before_content_sha256": None,
        "after_content_sha256_at_approval": None, "approved_by": None, "approved_at": None, "page_map": [],
        "requests_file": None, "notes": "",
    })
    save_manifest(cfg, manifest)
    return {"pair_id": pid, "added": True, "next": "approve 명령으로 확인하세요"}


def cmd_page_map(cfg: dict, args) -> dict:
    manifest = load_manifest(cfg)
    pair = get_pair(manifest, args.pair_id)
    entries = []
    for part in (args.map or "").split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+|-)\s*:\s*(\d+|-)", part)
        if not m:
            raise FinalError("PAGE_MAP_FORMAT_USE_1:1,2:3,3:-")
        b, a = m.group(1), m.group(2)
        entries.append({"before_page": None if b == "-" else int(b), "after_page": None if a == "-" else int(a),
                        "confirmed_by": args.by, "confirmed_at": now_iso()})
    pair["page_map"] = entries
    save_manifest(cfg, manifest)
    return {"pair_id": pair["pair_id"], "page_map_entries": len(entries)}


def cmd_unapprove(cfg: dict, args) -> dict:
    manifest = load_manifest(cfg)
    pair = get_pair(manifest, args.pair_id)
    pair.update({"approved_for_comparison": False, "status": "CANDIDATE_UNCONFIRMED", "approved_at": None})
    save_manifest(cfg, manifest)
    return {"pair_id": pair["pair_id"], "approved_for_comparison": False}


def cmd_status(cfg: dict) -> dict:
    manifest = load_manifest(cfg)
    by = {}
    for p in manifest["pairs"]:
        k = f"{p.get('category_code')}/{'approved' if p.get('approved_for_comparison') else 'unconfirmed'}"
        by[k] = by.get(k, 0) + 1
    return {"pairs": len(manifest["pairs"]), "by_category_status": by,
            "approved_pair_ids": [p["pair_id"] for p in manifest["pairs"] if p.get("approved_for_comparison")]}


def main() -> dict:
    ap = argparse.ArgumentParser(description="FINAL? pair resolver")
    ap.add_argument("command", choices=["scan", "approve", "add", "set-page-map", "unapprove", "status"])
    ap.add_argument("--config", default="config.local.json")
    ap.add_argument("--pair-id")
    ap.add_argument("--artwork-id")
    ap.add_argument("--by")
    ap.add_argument("--note")
    ap.add_argument("--category-code")
    ap.add_argument("--before")
    ap.add_argument("--after")
    ap.add_argument("--map")
    args = ap.parse_args()
    cfg = load_local_config(args.config)
    if args.command == "scan":
        return cmd_scan(cfg)
    if args.command == "approve":
        return cmd_approve(cfg, args)
    if args.command == "add":
        if not (args.category_code and args.before and args.after):
            raise FinalError("CATEGORY_CODE_BEFORE_AFTER_REQUIRED")
        return cmd_add(cfg, args)
    if args.command == "set-page-map":
        return cmd_page_map(cfg, args)
    if args.command == "unapprove":
        return cmd_unapprove(cfg, args)
    return cmd_status(cfg)


if __name__ == "__main__":
    sys.exit(run_cli(main))
