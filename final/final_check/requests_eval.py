"""3-way check: human-written revision requests vs. the observed comparison.

Requests are never generated from the diff. Without a request file the
request_status is NOT_PROVIDED and no "missing/applied/wrong" verdict exists.
Statuses are evidence-based candidates for a human, never final approval.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import FinalError, read_json
from .textdiff import ws_norm

OPS = {"replace", "delete", "add", "keep", "visual_note"}


def load_requests(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = read_json(path)
    except Exception:
        raise FinalError("REQUESTS_JSON_SYNTAX_ERROR") from None
    if not isinstance(data, dict):
        raise FinalError("REQUESTS_MUST_BE_OBJECT")
    reqs = data.get("requests") or []
    prot = data.get("protected_fields") or []
    if not isinstance(reqs, list) or not isinstance(prot, list):
        raise FinalError("REQUESTS_AND_PROTECTED_FIELDS_MUST_BE_ARRAYS")
    if not reqs and not prot:
        return None
    seen = set()
    for r in reqs:
        if not isinstance(r, dict) or r.get("operation") not in OPS or not r.get("request_id"):
            raise FinalError("REQUEST_ITEM_INVALID_OPERATION_OR_ID")
        if r["request_id"] in seen:
            raise FinalError("REQUEST_ID_DUPLICATED")
        seen.add(r["request_id"])
    return data


def count_value(value: str, text: str) -> int:
    n = ws_norm(value)
    if not n:
        return 0
    escaped = re.escape(n)
    left = r"(?<![\w.])" if re.match(r"[\w]", n) else ""
    right = r"(?![\w])" if re.search(r"[\w]$", n) else ""
    return len(re.findall(left + escaped + right, ws_norm(text)))


def _center_in(b: list[float], region: list[float] | None, shift: tuple[float, float] = (0.0, 0.0)) -> bool:
    if not region:
        return True
    cx, cy = (b[0] + b[2]) / 2 - shift[0], (b[1] + b[3]) / 2 - shift[1]
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def _shift_of(page: dict[str, Any]) -> tuple[float, float]:
    vis = page.get("visual") or {}
    if vis.get("canvas_shift_pt"):
        return float(vis["canvas_shift_pt"][0]), float(vis["canvas_shift_pt"][1])
    ts = (page.get("text") or {}).get("text_canvas_shift")
    if ts:
        return float(ts["dx_pt"]), float(ts["dy_pt"])
    return 0.0, 0.0


def _scope(pages: list[dict[str, Any]], req: dict[str, Any], side: str, radius: float = 40.0) -> dict[str, Any]:
    page_no = req.get("page")
    region = req.get("region")
    context = req.get("context")
    lines: list[dict[str, Any]] = []
    statuses = set()
    used_pages = []
    for p in pages:
        if p.get("status") != "DONE":
            continue
        if page_no and p["after_page"] != int(page_no):
            continue
        used_pages.append(p["label"])
        statuses.add((p.get("text") or {}).get("status", "UNKNOWN"))
        shift = _shift_of(p) if side == "after" else (0.0, 0.0)
        # region is given in the BEFORE/after page frame of the user's PDF viewer.
        # For the after side, the region follows the canvas shift.
        side_lines = p["lines_before"] if side == "before" else p["lines_after"]
        for line in side_lines:
            if _center_in(line["bbox"], region, shift):
                lines.append({**line, "page_label": p["label"],
                              "page": p["before_page"] if side == "before" else p["after_page"]})
    context_found = True
    if context:
        anchors = [l for l in lines if count_value(context, l["text"]) or ws_norm(context) in ws_norm(l["text"])]
        context_found = bool(anchors)
        keep = []
        for l in lines:
            cx, cy = (l["bbox"][0] + l["bbox"][2]) / 2, (l["bbox"][1] + l["bbox"][3]) / 2
            for a in anchors:
                ax, ay = (a["bbox"][0] + a["bbox"][2]) / 2, (a["bbox"][1] + a["bbox"][3]) / 2
                if a["page_label"] == l["page_label"] and abs(cy - ay) <= radius and abs(cx - ax) <= radius * 8:
                    keep.append(l)
                    break
        lines = keep
    return {"lines": lines, "text": "\n".join(l["text"] for l in lines), "statuses": statuses,
            "pages": used_pages, "context_found": context_found}


def _evidence(scope: dict[str, Any], values: list[str]) -> list[dict[str, Any]]:
    out = []
    for l in scope["lines"]:
        if any(v and count_value(v, l["text"]) for v in values):
            out.append({"page": l["page"], "bbox_pt": l["bbox"], "text": l["text"]})
    return out[:10]


def _unverifiable(scope: dict[str, Any]) -> bool:
    return not scope["pages"] or all(str(s).startswith("UNVERIFIABLE") for s in scope["statuses"])


def _overlap(a: list[float] | None, b: list[float] | None) -> bool:
    if not a or not b:
        return True
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def find_conflicts(reqs: list[dict[str, Any]], protected: list[dict[str, Any]]) -> dict[str, list[str]]:
    conflicts: dict[str, list[str]] = {}
    for i, r1 in enumerate(reqs):
        for r2 in reqs[i + 1:]:
            if (r1.get("requested_by") or "") == (r2.get("requested_by") or ""):
                continue
            if r1.get("page") and r2.get("page") and r1["page"] != r2["page"]:
                continue
            if not _overlap(r1.get("region"), r2.get("region")):
                continue
            same_target = r1.get("before_value") and ws_norm(r1.get("before_value") or "") == ws_norm(r2.get("before_value") or "")
            different_result = ws_norm(r1.get("after_value") or "") != ws_norm(r2.get("after_value") or "") or r1["operation"] != r2["operation"]
            if same_target and different_result:
                conflicts.setdefault(r1["request_id"], []).append(r2["request_id"])
                conflicts.setdefault(r2["request_id"], []).append(r1["request_id"])
    for r in reqs:
        for p in protected:
            if r["operation"] in ("replace", "delete") and r.get("before_value") and \
                    ws_norm(r["before_value"]) == ws_norm(p.get("value") or ""):
                if r.get("page") and p.get("page") and r["page"] != p["page"]:
                    continue
                conflicts.setdefault(r["request_id"], []).append(p.get("field_id", "PROTECTED"))
    return conflicts


def evaluate(data: dict[str, Any] | None, pages: list[dict[str, Any]], before_hash: str,
             pair: dict[str, Any]) -> dict[str, Any]:
    if data is None:
        return {"request_status": "NOT_PROVIDED", "request_checks": [], "protected_checks": [],
                "notes": ["수정 요청서가 없어 반영 여부를 판정하지 않았습니다. 변경 사실만 보고합니다."]}
    notes = []
    global_hold = None
    if data.get("pair_id") and data["pair_id"] != pair["pair_id"]:
        global_hold = "REQUESTS_FILE_FOR_DIFFERENT_PAIR"
    if data.get("category") and data["category"] != pair["category"]:
        global_hold = "REQUESTS_CATEGORY_MISMATCH"
    pinned = data.get("baseline_content_sha256")
    if pinned and pinned != before_hash:
        global_hold = "REQUESTS_BASELINE_HASH_MISMATCH"
    if not pinned:
        notes.append("BASELINE_HASH_NOT_PINNED_IN_REQUESTS: 요청서가 어떤 기준본에 대한 것인지 해시로 고정되지 않았습니다.")
    reqs = data.get("requests") or []
    protected = data.get("protected_fields") or []
    conflicts = find_conflicts(reqs, protected)
    after_all_text = "\n".join(l["text"] for p in pages if p.get("status") == "DONE" for l in p.get("lines_after", []))
    checks = []
    for r in reqs:
        op = r["operation"]
        bv, av = r.get("before_value") or "", r.get("after_value") or ""
        sb, sa = _scope(pages, r, "before"), _scope(pages, r, "after")
        res: dict[str, Any] = {"request_id": r["request_id"], "requested_by": r.get("requested_by"),
                               "source_reference": r.get("source_reference"), "operation": op,
                               "page": r.get("page"), "region": r.get("region"), "context": r.get("context"),
                               "before_value": bv or None, "after_value": av or None}
        reason = None
        if global_hold:
            status, reason = "HOLD", global_hold
        elif r["request_id"] in conflicts:
            status, reason = "CONFLICT_HOLD", "CONFLICTING_REQUESTS_NEED_HUMAN_DECISION"
            res["conflict_with"] = conflicts[r["request_id"]]
        elif op == "visual_note":
            status, reason = "HOLD_HUMAN_VISUAL_CHECK", "VISUAL_REQUEST_NOT_AUTOMATICALLY_DECIDED"
            res["related_visual_regions"] = [
                v["id"] for p in pages if p.get("status") == "DONE" and (not r.get("page") or p["after_page"] == int(r["page"]))
                for v in (p.get("visual") or {}).get("regions", []) if _overlap(v["box_pt_after_frame"], r.get("region"))
            ]
        elif _unverifiable(sb) or _unverifiable(sa):
            status, reason = "UNVERIFIABLE", "NO_COMPARABLE_TEXT_IN_SCOPE"
        elif r.get("context") and not (sb["context_found"] and sa["context_found"]):
            status, reason = "HOLD", "CONTEXT_NOT_FOUND_ON_BOTH_SIDES"
        else:
            b_old, a_old = count_value(bv, sb["text"]), count_value(bv, sa["text"])
            b_new, a_new = count_value(av, sb["text"]), count_value(av, sa["text"])
            res["counts"] = {"before_value_in_before": b_old, "before_value_in_after": a_old,
                             "after_value_in_before": b_new, "after_value_in_after": a_new}
            if op == "replace":
                if b_old == 0:
                    status, reason = "HOLD", "BEFORE_VALUE_NOT_FOUND_IN_BASELINE_SCOPE"
                elif a_new > b_new and a_old < b_old:
                    status = "REFLECTED"
                elif a_old >= b_old and a_new <= b_new:
                    status = "NOT_REFLECTED"
                else:
                    status, reason = "HOLD", "PARTIAL_OR_AMBIGUOUS_CHANGE"
            elif op == "delete":
                if b_old == 0:
                    status, reason = "HOLD", "BEFORE_VALUE_NOT_FOUND_IN_BASELINE_SCOPE"
                elif a_old == 0:
                    status = "REFLECTED"
                elif a_old >= b_old:
                    status = "NOT_REFLECTED"
                else:
                    status, reason = "HOLD", "PARTIALLY_DELETED"
            elif op == "add":
                status = "REFLECTED" if a_new > b_new else "NOT_REFLECTED"
            else:  # keep
                if b_old == 0:
                    status, reason = "HOLD", "KEEP_VALUE_NOT_FOUND_IN_BASELINE_SCOPE"
                else:
                    status = "KEPT" if a_old >= b_old else "PROTECTED_CHANGED"
            prev = [v for v in (r.get("previous_values") or []) if v]
            if prev and any(count_value(v, sa["text"]) > count_value(v, sb["text"]) for v in prev):
                status, reason = "REVERT_SUSPECTED", "PREVIOUS_VALUE_REAPPEARED_NO_HISTORY_CONFIRMATION"
            if status == "NOT_REFLECTED" and av and count_value(av, after_all_text) > 0:
                res["note"] = "AFTER_VALUE_FOUND_OUTSIDE_REQUEST_SCOPE_NOT_COUNTED"
            res["evidence_before"] = _evidence(sb, [bv, av])
            res["evidence_after"] = _evidence(sa, [bv, av])
        res["status"] = status
        res["reason"] = reason
        checks.append(res)
    pchecks = []
    for p in protected:
        sb, sa = _scope(pages, p, "before"), _scope(pages, p, "after")
        val = p.get("value") or ""
        res = {"field_id": p.get("field_id"), "value": val, "page": p.get("page"), "region": p.get("region"),
               "context": p.get("context")}
        if global_hold:
            res.update(status="HOLD", reason=global_hold)
        elif _unverifiable(sb) or _unverifiable(sa):
            res.update(status="UNVERIFIABLE", reason="NO_COMPARABLE_TEXT_IN_SCOPE")
        else:
            b, a = count_value(val, sb["text"]), count_value(val, sa["text"])
            prev = [v for v in (p.get("previous_values") or []) if v]
            reverted = [v for v in prev if count_value(v, sa["text"]) > count_value(v, sb["text"])]
            if b == 0:
                res.update(status="HOLD", reason="PROTECTED_VALUE_NOT_FOUND_IN_BASELINE_SCOPE")
            elif a >= b and not reverted:
                res.update(status="KEPT", reason=None)
            elif reverted:
                res.update(status="REVERT_SUSPECTED", reason="PREVIOUS_VALUE_REAPPEARED_NO_HISTORY_CONFIRMATION",
                           reappeared_values=reverted)
            else:
                res.update(status="PROTECTED_CHANGED", reason="PROTECTED_VALUE_CHANGED_OR_REMOVED")
            res["evidence_before"] = _evidence(sb, [val] + prev)
            res["evidence_after"] = _evidence(sa, [val] + prev)
        pchecks.append(res)
    return {"request_status": "PROVIDED", "request_checks": checks, "protected_checks": pchecks, "notes": notes,
            "conflicts": conflicts}


def outside_scope(data: dict[str, Any] | None, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Changes not covered by any request (only meaningful when requests exist)."""
    if data is None:
        return []
    reqs = data.get("requests") or []
    out = []
    for p in pages:
        if p.get("status") != "DONE":
            continue
        covered_text = set()
        for item in (p.get("text") or {}).get("items", []):
            if item["kind"] in ("LINE_BREAK_REFLOW_ONLY",):
                continue
            joined = " ".join(x for x in (item.get("before"), item.get("after")) if x)
            box = item.get("after_bbox_pt") or item.get("before_bbox_pt")
            hit = False
            for r in reqs:
                if r.get("page") and int(r["page"]) != p["after_page"]:
                    continue
                if r.get("region") and not _overlap(box, r["region"]):
                    continue
                vals = [r.get("before_value"), r.get("after_value"), r.get("context")]
                if any(v and count_value(v, joined) for v in vals) or (r.get("region") and _overlap(box, r["region"])):
                    hit = True
                    break
            if hit:
                covered_text.add(item["id"])
                continue
            out.append({"id": item["id"], "page": p["after_page"], "kind": item["kind"],
                        "flag": "UNREQUESTED_NUMERIC_CHANGE" if item.get("numeric_change") else "OUTSIDE_REQUEST_SCOPE"})
        for v in (p.get("visual") or {}).get("regions", []):
            if v["linked_text_change_ids"] and all(t in covered_text for t in v["linked_text_change_ids"]):
                continue
            if any(r.get("region") and (not r.get("page") or int(r["page"]) == p["after_page"]) and
                   _overlap(v["box_pt_after_frame"], r["region"]) for r in reqs):
                continue
            if v["linked_text_change_ids"] and any(o["id"] in v["linked_text_change_ids"] for o in out):
                continue  # already listed via its text change
            out.append({"id": v["id"], "page": p["after_page"], "kind": v["kind"], "flag": "OUTSIDE_REQUEST_SCOPE_VISUAL"})
    return out
