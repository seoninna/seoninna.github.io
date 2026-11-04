"""Report outputs.

PRIVATE (local only, contains artwork text/paths/crops):
  report.private.json, report.private.html, report.private.pdf, images/
SAFE (no artwork text, no file names, no paths, no artwork_id):
  summary.safe.json, notify_safe.txt, notify_safe.html
The safe files are the only content designed for an optional, approved
notification. Whether even these may leave the PC is the user's decision.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .common import atomic_write_json, atomic_write_text

TEXT_KIND_KO = {
    "TEXT_CHANGED": "문구·숫자 변경",
    "TEXT_ADDED": "문구 추가",
    "TEXT_REMOVED": "문구 삭제",
    "TEXT_MOVED": "문구 위치 이동(캔버스 이동 보정 후에도 이동)",
    "TEXT_SIZE_CHANGED": "글자 크기 변경",
    "WHITESPACE_ONLY_CHANGE": "공백만 다름(보조 결과)",
    "LINE_BREAK_REFLOW_ONLY": "줄바꿈만 다름(보조 결과)",
}
VIS_KIND_KO = {
    "CONTENT_ADDED_CANDIDATE": "추가된 내용 후보",
    "CONTENT_REMOVED_CANDIDATE": "삭제된 내용 후보",
    "CONTENT_MODIFIED_CANDIDATE": "변경된 영역 후보",
    "MOVE_CANDIDATE": "이동 후보",
}
REQ_KO = {
    "REFLECTED": "요청 반영 근거 있음 (사람 확인 필요)",
    "NOT_REFLECTED": "미반영 의심 (요청 대상 값이 그대로 있음)",
    "HOLD": "판단 유보",
    "CONFLICT_HOLD": "요청 충돌 — 사람이 결정",
    "UNVERIFIABLE": "검수 불가 (해당 범위 텍스트 없음)",
    "HOLD_HUMAN_VISUAL_CHECK": "시각 확인 필요",
    "KEPT": "유지 확인",
    "PROTECTED_CHANGED": "유지 항목 변경",
    "REVERT_SUSPECTED": "유지 항목 변경/원복 의심",
}
OVERALL_KO = {
    "COMPARED_WITH_LIMITATIONS": "매핑된 페이지를 비교함 — 아래 '검수하지 않은 항목'은 사람이 확인",
    "PARTIAL_COVERAGE": "일부만 비교됨 — 미처리·검수불가 영역이 있음",
    "UNVERIFIABLE_NOTHING_COMPARED": "비교하지 못함 — 결과를 '변경 없음'으로 해석하지 마세요",
}
REASON_KO = {
    "PAGE_MAP_REQUIRED_PAGE_COUNT_CHANGED": "페이지 수가 달라 페이지 대응(page_map) 확인 필요",
    "PAGE_MAP_REQUIRED_SIZE_OR_ROTATION_CHANGED": "페이지 크기/회전이 달라 대응 확인 필요",
    "NOT_IN_PAGE_MAP": "page_map에 없는 페이지",
    "NO_COUNTERPART_PER_PAGE_MAP": "page_map에서 대응 없음으로 지정",
    "UNPROCESSED_PAGE_LIMIT": "처리 페이지 수 제한으로 미처리",
    "PAGE_TIMEOUT": "시간 초과",
    "PAGE_WORKER_CRASHED": "처리 중 중단",
    "OUT_OF_MEMORY": "메모리 부족",
    "UNVERIFIABLE_NO_TEXT_LAYER": "텍스트 레이어 없음(아웃라인/이미지) — 문자 비교 불가, 시각 후보만",
    "UNVERIFIABLE_TEXT_LAYER_ONLY_ONE_SIDE": "한쪽만 텍스트 레이어 있음(아웃라인 전환 가능) — 문자 비교 불가",
    "PARTIAL_FONT_ENCODING_SUSPECT": "글꼴 인코딩 의심 문자 포함 — 일부 문자 비교 불확실",
    "SKIPPED_PIXEL_LIMIT_PAGE_TOO_LARGE": "렌더 픽셀 제한 초과 — 시각 비교 미처리",
    "REGIONS_TRUNCATED": "변경 후보가 많아 일부 박스 생략",
}

CSS = """
body{font-family:-apple-system,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;margin:24px;color:#111;background:#fff;line-height:1.45}
h1{margin:0}.tag{color:#555;margin:0 0 12px}h2{border-bottom:2px solid #222;padding-bottom:4px;margin-top:28px}
.banner{padding:12px 16px;border-radius:6px;background:#fff4e5;border:1px solid #f0a040;margin:12px 0}
.banner.bad{background:#fde8e8;border-color:#d33}.muted{color:#666;font-size:90%}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:92%}th,td{border:1px solid #bbb;padding:5px 7px;vertical-align:top;text-align:left}
th{background:#f2f2f2}code,.raw{font-family:Consolas,monospace;white-space:pre-wrap;word-break:break-all}
.crops img{max-width:340px;max-height:240px;border:1px solid #999;margin-right:6px}.ov{max-width:100%;border:1px solid #999}
.k{display:inline-block;padding:1px 6px;border-radius:4px;background:#eef;font-size:85%}
"""


def e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _raw(value: Any) -> str:
    # show leading/trailing spaces explicitly so spacing changes are visible
    if value is None:
        return "<span class='muted'>(없음)</span>"
    s = str(value)
    return "<span class='raw'>" + e(s).replace(" ", "␣") + "</span>"


def build_html(rep: dict[str, Any], for_pdf: bool = False) -> str:
    p = rep["pair"]
    cov = rep["coverage"]
    req = rep["requests"]
    provided = req["request_status"] == "PROVIDED"
    bad = rep["overall_status"] != "COMPARED_WITH_LIMITATIONS"
    out = [f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>FINAL? 검수 보고서</title><style>{CSS}</style></head><body>"]
    out.append("<h1>FINAL? 원화 비교 보고서</h1><p class='tag'>Is this really the final version? — 로컬 전용(PRIVATE) 문서. 외부 공유 금지.</p>")
    out.append(f"<div class='banner{' bad' if bad else ''}'><b>상태: {e(rep['overall_status'])}</b> — {e(OVERALL_KO.get(rep['overall_status'], ''))}<br>"
               "이 보고서는 <b>최종 승인이 아닙니다</b>. 픽셀 차이는 '시각적 변경 후보'이며 잘못 수정되었다는 확정이 아닙니다.</div>")
    out.append("<h2>1. 비교 대상</h2><table>")
    rows = [("pair_id", p.get("pair_id")), ("구분", p.get("category")), ("원화 ID(사람 확인값)", p.get("artwork_id")),
            ("이전본(before) 상대경로", p.get("before_relative_path")), ("수정본(after) 상대경로", p.get("after_relative_path")),
            ("before SHA-256", rep["hashes"]["before_sha256"]), ("after SHA-256", rep["hashes"]["after_sha256"]),
            ("페이지 수 before / after", f"{rep['documents']['before']['page_count']} / {rep['documents']['after']['page_count']}"),
            ("페이지 대응 방식", rep["page_mapping"]["source"]), ("생성 시각(UTC)", rep["generated_at"]),
            ("엔진 버전", rep["engine_version"])]
    out += [f"<tr><th>{e(k)}</th><td><code>{e(v)}</code></td></tr>" for k, v in rows]
    out.append("</table><p class='muted'>before 폴더에 있다는 이유만으로 '최종 승인본'이 아닙니다. 수정본은 다음 기준본으로 자동 승격되지 않습니다.</p>")

    out.append("<h2>2. 검수 범위와 미처리 영역</h2>")
    out.append(f"<p>대응된 항목 {cov['mapped_entries']}개 중 {cov['entries_compared']}개 비교. 큰 문서 기준 페이지 {cov['pages_in_larger_document']}쪽.</p>")
    if cov["unprocessed"] or cov["text_unverifiable_or_partial"] or cov["visual_skipped"]:
        out.append("<table><tr><th>before 쪽</th><th>after 쪽</th><th>상태</th><th>설명</th></tr>")
        for u in cov["unprocessed"]:
            out.append(f"<tr><td>{e(u.get('before_page'))}</td><td>{e(u.get('after_page'))}</td><td><code>{e(u['reason'])}</code></td><td>{e(REASON_KO.get(u['reason'], '미처리'))}</td></tr>")
        for u in cov["text_unverifiable_or_partial"]:
            out.append(f"<tr><td colspan=2>{e(u['label'])} (after {e(u['after_page'])}쪽)</td><td><code>{e(u['status'])}</code></td><td>{e(REASON_KO.get(u['status'], ''))}</td></tr>")
        for u in cov["visual_skipped"]:
            out.append(f"<tr><td colspan=2>{e(u['label'])} (after {e(u['after_page'])}쪽)</td><td><code>{e(u['status'])}</code></td><td>{e(REASON_KO.get(u['status'], ''))}</td></tr>")
        out.append("</table>")
    else:
        out.append("<p>대응된 모든 페이지에서 텍스트 레이어 비교와 시각 비교를 수행했습니다. (텍스트 레이어 밖의 그래픽 문자 내용은 시각 후보로만 확인)</p>")
    if rep["page_mapping"]["suggested_page_map"]:
        out.append("<p><b>페이지 대응 제안(미확정)</b> — 맞으면 pair_resolver.py set-page-map 으로 확정하세요.</p><table><tr><th>before</th><th>after</th><th>텍스트 유사도</th></tr>")
        for s in rep["page_mapping"]["suggested_page_map"]:
            out.append(f"<tr><td>{s['before_page']}</td><td>{s['after_page']}</td><td>{s['text_similarity']}</td></tr>")
        out.append("</table>")
    if rep["canvas_shifts"]:
        out.append("<p><b>전체 캔버스 이동 감지</b>: 아래 시각 후보는 이 이동을 보정한 뒤의 차이입니다. 개별 요소 이동은 보정 후에도 남도록 처리했습니다.</p><ul>")
        for c in rep["canvas_shifts"]:
            out.append(f"<li>{e(c['label'])}: dx,dy = {e(c['shift_pt'])} pt ({e(c['shift_mm'])} mm)</li>")
        out.append("</ul>")

    out.append("<h2>3. 수정 요청 대조</h2>")
    if not provided:
        out.append("<p><b>request_status = NOT_PROVIDED</b> — 수정 요청서가 없어 반영 여부를 판정하지 않았습니다. "
                   "아래 변경 목록은 '무엇이 달라졌는지'이며, 의도된 수정인지는 사람이 판단합니다.</p>")
    else:
        for n in req.get("notes", []):
            out.append(f"<p class='muted'>{e(n)}</p>")
        out.append("<table><tr><th>요청 ID</th><th>요청자</th><th>작업</th><th>범위</th><th>before 값 → after 값</th><th>결과</th><th>근거</th></tr>")
        for c in req["request_checks"]:
            ev = "".join(f"<div>before p{x['page']} {e(x['bbox_pt'])}: {_raw(x['text'])}</div>" for x in c.get("evidence_before", []))
            ev += "".join(f"<div>after p{x['page']} {e(x['bbox_pt'])}: {_raw(x['text'])}</div>" for x in c.get("evidence_after", []))
            extra = f"<br><span class='muted'>{e(c.get('reason'))} {e(c.get('note') or '')} {e(c.get('conflict_with') or '')}</span>"
            out.append(f"<tr><td>{e(c['request_id'])}</td><td>{e(c.get('requested_by'))}<br><span class='muted'>{e(c.get('source_reference'))}</span></td>"
                       f"<td>{e(c['operation'])}</td><td>p{e(c.get('page'))} {e(c.get('region') or '')} {e(c.get('context') or '')}</td>"
                       f"<td>{_raw(c.get('before_value'))} → {_raw(c.get('after_value'))}</td>"
                       f"<td><b>{e(REQ_KO.get(c['status'], c['status']))}</b>{extra}</td><td>{ev}</td></tr>")
        out.append("</table>")
        if req["protected_checks"]:
            out.append("<p><b>유지 항목</b></p><table><tr><th>ID</th><th>값</th><th>결과</th><th>근거</th></tr>")
            for c in req["protected_checks"]:
                ev = "".join(f"<div>after p{x['page']}: {_raw(x['text'])}</div>" for x in c.get("evidence_after", []))
                out.append(f"<tr><td>{e(c['field_id'])}</td><td>{_raw(c['value'])}</td><td><b>{e(REQ_KO.get(c['status'], c['status']))}</b><br><span class='muted'>{e(c.get('reason'))}</span></td><td>{ev}</td></tr>")
            out.append("</table><p class='muted'>'원복 의심'은 이전 값이 다시 나타났다는 뜻이며, 버전 충돌을 확정하는 것이 아닙니다.</p>")
        if rep["outside_request_scope"]:
            out.append("<p><b>요청 범위 밖 변경 (확인 필요)</b></p><ul>")
            for o in rep["outside_request_scope"]:
                out.append(f"<li><code>{e(o['id'])}</code> after {e(o['page'])}쪽 — {e(o['flag'])} ({e(o['kind'])})</li>")
            out.append("</ul>")

    out.append("<h2>4. 텍스트·숫자 변경 (PDF 텍스트 레이어 기준)</h2>")
    out.append("<p class='muted'>좌표는 pt(1/72인치), 페이지 왼쪽 위 기준. ␣ 는 공백 문자. 공백·줄바꿈만 다른 항목은 보조 결과로 따로 표시합니다.</p>")
    any_text = False
    for pg in rep["pages"]:
        items = (pg.get("text") or {}).get("items", [])
        if not items:
            continue
        any_text = True
        out.append(f"<h3>{e(pg['label'])}: before {pg['before_page']}쪽 ↔ after {pg['after_page']}쪽</h3>")
        out.append("<table><tr><th>ID</th><th>종류</th><th>before</th><th>after</th><th>숫자</th><th>위치(pt)</th></tr>")
        for it in items:
            nums = ""
            if it.get("numeric_change"):
                nums = f"<b>숫자 변경</b><br>{e(it.get('numbers_before'))} → {e(it.get('numbers_after'))}"
            hints = " ".join(f"<span class='k'>{e(h)}</span>" for h in it.get("field_hints", []))
            pos = f"before {e(it.get('before_bbox_pt'))}<br>after {e(it.get('after_bbox_pt'))}"
            if it.get("move_after_canvas_shift_pt"):
                pos += f"<br>이동(보정 후) {e(it['move_after_canvas_shift_pt'])}"
            out.append(f"<tr><td>{e(it['id'])}</td><td>{e(TEXT_KIND_KO.get(it['kind'], it['kind']))} {hints}</td>"
                       f"<td>{_raw(it.get('before'))}</td><td>{_raw(it.get('after'))}</td><td>{nums}</td><td class='muted'>{pos}</td></tr>")
        out.append("</table>")
        if (pg.get("text") or {}).get("extraction_order_changes"):
            out.append(f"<p class='muted'>텍스트 추출 순서만 바뀐 줄 {pg['text']['extraction_order_changes']}개 — 내용 변경으로 보지 않음.</p>")
    if not any_text:
        out.append("<p>텍스트 레이어에서 변경을 찾지 못했습니다. 단, 텍스트 레이어가 없는 영역(아웃라인·이미지)은 이 표의 대상이 아닙니다 — 2절과 5절을 확인하세요.</p>")

    out.append("<h2>5. 시각적 변경 후보 (렌더링 비교)</h2>")
    out.append("<p class='muted'>오버레이: <b style='color:#d00'>빨강</b>=수정본에만 있는 잉크, <b style='color:#0aa'>청록</b>=이전본에만 있는 잉크, 주황 박스=변경 후보, 보라 박스=이동 후보.</p>")
    for pg in rep["pages"]:
        v = pg.get("visual") or {}
        if v.get("status") != "COMPARED_CANDIDATES_ONLY":
            continue
        out.append(f"<h3>{e(pg['label'])}: before {pg['before_page']}쪽 ↔ after {pg['after_page']}쪽 — 후보 {len(v.get('regions', []))}개 (렌더 {v['dpi']} dpi)</h3>")
        if v.get("before_ink_outside_text_lines_ratio") is not None:
            out.append(f"<p class='muted'>이전본 잉크 중 텍스트 레이어 밖 비율: {v['before_ink_outside_text_lines_ratio']:.1%} — 이 부분의 문자 내용은 텍스트 비교 대상이 아님.</p>")
        if v.get("specks_below_min_pixels"):
            out.append(f"<p class='muted'>최소 크기 미만 미세 점 {v['specks_below_min_pixels']}개는 박스에서 제외(개수만 기록).</p>")
        if not for_pdf or len(v.get("regions", [])) > 0:
            out.append(f"<p><img class='ov' src='images/{e(v['overlay'])}' alt='overlay'></p>")
        if v.get("regions"):
            out.append("<table><tr><th>ID</th><th>종류</th><th>위치(pt, before 기준)</th><th>연결된 텍스트 변경</th><th>before / after 크롭</th></tr>")
            for r in v["regions"]:
                mv = f"<br>이동 {e(r.get('move_pt'))} pt" if r.get("move_pt") else ""
                if r.get("low_contrast_edge_only"):
                    mv += "<br><span class='muted'>낮은 대비의 가장자리 차이 — 정렬 잔차·안티앨리어싱일 수 있음(제거하지 않고 표시)</span>"
                link = ", ".join(r["linked_text_change_ids"]) or ("텍스트 레이어 밖 — 그래픽/아웃라인/이미지일 수 있음" if not r["overlaps_text_layer"] else "텍스트 영역이나 대응 텍스트 변경 없음")
                out.append(f"<tr><td>{e(r['id'])}</td><td>{e(VIS_KIND_KO.get(r['kind'], r['kind']))}{mv}<br><span class='muted'>{r['diff_pixels']} px</span></td>"
                           f"<td class='muted'>{e(r['box_pt_before_frame'])}</td><td>{e(link)}</td>"
                           f"<td class='crops'><div class='muted'>before(이전본)</div><img src='images/{e(r['crops']['before'])}' alt='before'><div class='muted'>after(수정본)</div><img src='images/{e(r['crops']['after'])}' alt='after'><br><span class='muted'>{e(r['crops']['resolution'])} {e(r['crops']['dpi'])} dpi</span></td></tr>")
            out.append("</table>")

    out.append("<h2>6. 검수하지 않은 항목 (사람이 확인)</h2><ul>")
    out += [f"<li>{e(x)}</li>" for x in rep["not_checked"]]
    out.append("</ul><h2>7. 사람 확인 체크리스트</h2><ol>"
               "<li>비교 대상 pair와 해시가 맞는 파일인지</li><li>2절의 미처리·검수불가 영역을 원본에서 직접 확인했는지</li>"
               "<li>각 변경이 의도된 수정인지 (요청서가 없으면 판정하지 않음)</li><li>시각 후보 중 잡음/실제 변경 구분</li>"
               "<li>색상·별색·도련·바코드 등 인쇄 항목 별도 확인</li></ol>")
    out.append("<p class='muted'>FINAL? 로컬 비교 엔진은 외부 AI를 호출하지 않으며, 결정적인 숫자 비교는 코드가 수행했습니다. 완벽한 검수나 오류 없음을 보장하지 않습니다.</p></body></html>")
    return "".join(out)


def safe_summary(rep: dict[str, Any], run_key: str, mode: str = "LOCAL_ONLY") -> dict[str, Any]:
    cov = rep["coverage"]
    return {
        "classification": "SAFE_SUMMARY_NO_ARTWORK_CONTENT",
        "mode": mode,
        "pair_id": rep["pair"]["pair_id"],
        "category_code": rep["pair"].get("category_code"),
        "run_key": run_key,
        "overall_status": rep["overall_status"],
        "final_approval": False,
        "request_status": rep["requests"]["request_status"],
        "request_status_counts": rep["counts"]["request_statuses"],
        "text_changes_by_kind": rep["counts"]["text_changes_by_kind"],
        "numeric_text_changes": rep["counts"]["numeric_text_changes"],
        "visual_candidates_by_kind": rep["counts"]["visual_candidates_by_kind"],
        "entries_compared": cov["entries_compared"],
        "unprocessed_entries": len(cov["unprocessed"]),
        "text_unverifiable_or_partial_entries": len(cov["text_unverifiable_or_partial"]),
        "visual_skipped_entries": len(cov["visual_skipped"]),
        "canvas_shift_detected": bool(rep["canvas_shifts"]),
        "outside_request_scope_count": len(rep["outside_request_scope"]),
        "generated_at": rep["generated_at"],
        "processing_seconds": rep["processing_seconds"],
        "llm_called": False,
        "llm_tokens": "NOT_CALLED",
    }


def safe_notification(summary: dict[str, Any]) -> tuple[str, str, str]:
    subject = f"FINAL? | {summary['pair_id']} | {summary['overall_status']}"
    tc = sum(summary["text_changes_by_kind"].values())
    vc = sum(summary["visual_candidates_by_kind"].values())
    lines = [
        "FINAL? 로컬 비교 알림 (내용 없는 요약)",
        f"pair_id: {summary['pair_id']} ({summary['category_code']})",
        f"상태: {summary['overall_status']} / 최종 승인 아님",
        f"텍스트 변경 {tc}건 (숫자 포함 {summary['numeric_text_changes']}건), 시각적 변경 후보 {vc}건",
        f"미처리 {summary['unprocessed_entries']}건, 텍스트 검수불가/부분 {summary['text_unverifiable_or_partial_entries']}건",
        f"요청서: {summary['request_status']} {summary['request_status_counts'] or ''}",
        "상세 보고서는 로컬 PC의 결과 폴더에서만 확인하세요.",
    ]
    text = "\n".join(lines)
    html_body = "<div style='font-family:sans-serif'>" + "".join(f"<p>{e(l)}</p>" for l in lines) + "</div>"
    return subject, text, html_body


def write_reports(rep: dict[str, Any], report_dir: Path, run_key: str, make_pdf: bool = True) -> dict[str, Any]:
    report_dir.mkdir(parents=True, exist_ok=True)
    slim = {**rep, "pages": [{k: v for k, v in p.items() if k not in ("lines_before", "lines_after")} for p in rep["pages"]]}
    atomic_write_json(report_dir / "report.private.json", slim)
    atomic_write_text(report_dir / "report.private.html", build_html(rep))
    pdf_status = "SKIPPED"
    if make_pdf:
        pdf_status = write_pdf(rep, report_dir)
    summ = safe_summary(rep, run_key)
    summ["pdf_report"] = pdf_status
    atomic_write_json(report_dir / "summary.safe.json", summ)
    subject, text, body = safe_notification(summ)
    atomic_write_text(report_dir / "notify_safe.txt", subject + "\n\n" + text + "\n")
    atomic_write_text(report_dir / "notify_safe.html", body)
    return summ


def write_pdf(rep: dict[str, Any], report_dir: Path) -> str:
    """Multi-page PDF via PyMuPDF Story. Best effort; failure is reported, not hidden."""
    try:
        import pymupdf  # type: ignore

        html_text = build_html(rep, for_pdf=True).replace("max-width:100%", "max-width:520px")
        story = pymupdf.Story(html=html_text, user_css=CSS + " img.ov{width:520px}", archive=pymupdf.Archive(str(report_dir)))
        path = report_dir / "report.private.pdf"
        writer = pymupdf.DocumentWriter(str(path))
        mediabox = pymupdf.paper_rect("a4")
        where = mediabox + (36, 36, -36, -36)
        more = 1
        pages = 0
        while more and pages < 400:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            pages += 1
        writer.close()
        return "WRITTEN" if not more else "TRUNCATED_AT_400_PAGES"
    except Exception as err:  # noqa: BLE001
        return f"FAILED_{type(err).__name__}"
