#!/usr/bin/env python3
"""Generate the two n8n workflow JSON files.

  n8n/FINAL_Local_Workflow.json        LOCAL_ONLY: schedule -> local API (pair_id only) -> local report
                                       -> optional safe notice mail (OFF until approved) -> delivery record
  n8n/FINAL_B_Approved_Workflow.json   APPROVED_EXTERNAL_B: Gmail -> Drive manifest/baseline -> B service -> result mail

Both are exported with active=false and without credentials. Node typeVersions
target n8n 1.x/2.x core nodes; re-check in your n8n version after import.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "n8n"


def nid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "final-n8n/" + name))


def node(name, type_, version, pos, params, **extra):
    n = {"parameters": params, "id": nid(name), "name": name, "type": type_, "typeVersion": version, "position": pos}
    n.update(extra)
    return n


def cond_true(expr, cid):
    return {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                           "conditions": [{"id": nid(cid), "leftValue": expr, "rightValue": "",
                                           "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                           "combinator": "and"}, "options": {}}


def assign(name, value, typ="string"):
    return {"id": nid("assign-" + name), "name": name, "value": value, "type": typ}


def sticky(name, pos, content, w=520, h=260, color=None):
    p = {"content": content, "width": w, "height": h}
    if color:
        p["color"] = color
    return node(name, "n8n-nodes-base.stickyNote", 1, pos, p)


def http_local(name, pos, path, body_expr, timeout_ms):
    return node(name, "n8n-nodes-base.httpRequest", 4.2, pos, {
        "method": "POST",
        "url": "={{ $('02 Settings').first().json.api_base }}" + path,
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": body_expr,
        "options": {"timeout": timeout_ms},
    })


def connect(conns, src, *targets_by_output):
    conns[src] = {"main": [[{"node": t, "type": "main", "index": 0} for t in outs] for outs in targets_by_output]}


def local_workflow():
    nodes = [
        node("01 Every 10 min", "n8n-nodes-base.scheduleTrigger", 1.2, [0, 300],
             {"rule": {"interval": [{"field": "minutes", "minutesInterval": 10}]}}),
        node("02 Settings", "n8n-nodes-base.set", 3.4, [220, 300], {
            "assignments": {"assignments": [
                assign("api_base", "http://127.0.0.1:8765"),
                assign("mode", "LOCAL_ONLY"),
                assign("safe_notice_to", ""),
            ]}, "includeOtherFields": False, "options": {}}),
        http_local("03 Scan Pending (local API)", [440, 300], "/scan", "={{ JSON.stringify({}) }}", 120000),
        node("04 One item per pair", "n8n-nodes-base.splitOut", 1, [660, 300],
             {"fieldToSplitOut": "pending", "options": {}}),
        http_local("05 Compare pair (local API)", [880, 300], "/compare",
                   "={{ JSON.stringify({ pair_id: $json.pair_id, event_id: $json.event_id }) }}", 3600000),
        node("06 Compared?", "n8n-nodes-base.if", 2.2, [1100, 300],
             cond_true("={{ $json.ok === true && $json.status === 'COMPARED' }}", "c-compared")),
        node("07 Safe notice approved?", "n8n-nodes-base.if", 2.2, [1320, 200],
             cond_true("={{ $json.safe_email_enabled === true && $('02 Settings').first().json.safe_notice_to !== '' }}", "c-safe")),
        node("08 Send SAFE notice (OFF)", "n8n-nodes-base.gmail", 2.1, [1540, 100], {
            "resource": "message", "operation": "send",
            "sendTo": "={{ $('02 Settings').first().json.safe_notice_to }}",
            "subject": "={{ $json.safe_notification.subject }}",
            "emailType": "html",
            "message": "={{ $json.safe_notification.html }}",
            "options": {"appendAttribution": False}}, disabled=True),
        node("09 Gmail accepted?", "n8n-nodes-base.if", 2.2, [1760, 100],
             cond_true("={{ typeof $json.id === 'string' && $json.id.length > 0 && Array.isArray($json.labelIds) }}", "c-accepted")),
        http_local("10 Record: SENT", [1980, 0], "/delivery",
                   "={{ JSON.stringify({ run_key: $('05 Compare pair (local API)').item.json.run_key, status: 'SENT_ACCEPTED_BY_PROVIDER', message_id: $json.id }) }}",
                   60000),
        http_local("11 Record: LOCAL ONLY (not sent)", [1980, 300], "/delivery",
                   "={{ JSON.stringify({ run_key: $('05 Compare pair (local API)').item.json.run_key, status: 'LOCAL_ONLY_NOT_SENT' }) }}",
                   60000),
        node("12 Not compared (codes only)", "n8n-nodes-base.code", 2, [1320, 480], {
            "mode": "runOnceForEachItem",
            "jsCode": "// Only non-sensitive codes are kept here.\nreturn { json: { ok: $json.ok === true, status: $json.status || null, error_code: $json.error_code || null, pair_id: $json.pair_id || null, retry_later: $json.retry_later === true } };\n"}),
        sticky("READ FIRST", [-40, -260],
               "## FINAL? LOCAL_ONLY\n이 워크플로는 **내 PC에서 실행하는 n8n** 전용입니다 (Railway 불가).\n"
               "n8n은 파일을 직접 읽지 않고 `local_api.py`(127.0.0.1:8765)에 **pair_id만** 보냅니다.\n"
               "상세 보고서는 PC의 output_dir에만 저장됩니다.\n자격증명: Header Auth `X-FINAL-Token` = config의 local_api.token\n"
               "03·05·10·11 노드에 같은 자격증명을 선택하세요.", 620, 250, 4),
        sticky("EXTERNAL SEND = OFF", [1480, -260],
               "## 08 메일 발송은 기본 OFF\n메일 발송도 외부 전송입니다.\n켜려면 (1) 회사 승인 확인 (2) config.local.json `notification.safe_email_enabled=true` + `approval_note` "
               "(3) 02 Settings `safe_notice_to` (4) 08 노드 Enable.\n보내는 내용은 문구·파일명 없는 **안전 요약**뿐입니다.\n"
               "로컬 저장만으로 '결과 전달' 과제 요건을 충족했다고 보지 않습니다.", 620, 250, 3),
        sticky("EVIDENCE", [640, 560],
               "## 자동 실행 증빙\nPublish/Activate 후 Schedule이 스스로 실행한 건만 '자동 실행'입니다.\n"
               "새 수정본을 after 폴더에 저장 → 10분 내 자동 비교 → Executions 캡처.\n결과가 없던 실행(대기 0건)은 결과물로 세지 마세요.", 620, 200, 5),
    ]
    conns = {}
    connect(conns, "01 Every 10 min", ["02 Settings"])
    connect(conns, "02 Settings", ["03 Scan Pending (local API)"])
    connect(conns, "03 Scan Pending (local API)", ["04 One item per pair"])
    connect(conns, "04 One item per pair", ["05 Compare pair (local API)"])
    connect(conns, "05 Compare pair (local API)", ["06 Compared?"])
    connect(conns, "06 Compared?", ["07 Safe notice approved?"], ["12 Not compared (codes only)"])
    connect(conns, "07 Safe notice approved?", ["08 Send SAFE notice (OFF)"], ["11 Record: LOCAL ONLY (not sent)"])
    connect(conns, "08 Send SAFE notice (OFF)", ["09 Gmail accepted?"])
    connect(conns, "09 Gmail accepted?", ["10 Record: SENT"], ["11 Record: LOCAL ONLY (not sent)"])
    return {"name": "FINAL? LOCAL_ONLY — 로컬 원화 자동 비교", "nodes": nodes, "connections": conns, "active": False,
            "settings": {"executionOrder": "v1", "timezone": "Asia/Seoul", "saveDataSuccessExecution": "all",
                         "saveDataErrorExecution": "all", "saveManualExecutions": True},
            "pinData": {}, "meta": {"templateCredsSetupCompleted": False}, "tags": []}


VALIDATE_JS = r"""// APPROVED_EXTERNAL_B only. Refuses to run until the approval gate is filled.
const s = $('02 Settings').first().json;
const item = $('01 Gmail: new revision').item;
const j = item.json;
const errors = [];
if (s.b_mode_enabled !== true) throw new Error('B_MODE_DISABLED: 02 Settings b_mode_enabled=true 와 approval_note 를 채우기 전에는 실행하지 않습니다.');
if (String(s.approval_note || '').trim().length < 5) throw new Error('B_APPROVAL_NOTE_REQUIRED');
if (!/^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/.test(String(s.report_to || ''))) throw new Error('SET_REPORT_TO_IN_SETTINGS');
function header(name) { const h = j.headers || {}; return String(h[name] || h[name.toLowerCase()] || j[name] || ''); }
const subject = String(j.subject || header('subject') || '').trim();
const from = String((j.from && (j.from.value?.[0]?.address || j.from.text)) || header('from') || '');
if (s.allowed_sender && !from.toLowerCase().includes(String(s.allowed_sender).toLowerCase())) errors.push('SENDER_NOT_ALLOWED');
const m = subject.match(/^FINALCHECK\s*\|\s*(SET|SINGLE)\s*\|\s*([A-Za-z0-9_.-]{1,40})\s*$/);
if (!m) errors.push('SUBJECT_FORMAT: FINALCHECK | SET 또는 SINGLE | 원화ID');
const pdfKeys = Object.keys(item.binary || {}).filter(k => /\.pdf$/i.test(item.binary[k].fileName || '') || item.binary[k].mimeType === 'application/pdf');
if (pdfKeys.length !== 1) errors.push('EXACTLY_ONE_PDF_ATTACHMENT_REQUIRED');
let size = null;
if (pdfKeys.length === 1) {
  const buf = await this.helpers.getBinaryDataBuffer($itemIndex, pdfKeys[0]);
  size = buf.length;
  if (size > Number(s.max_attachment_mb) * 1024 * 1024) errors.push('ATTACHMENT_OVER_LIMIT_NOT_TRUNCATED');
}
return { json: { valid: errors.length === 0, errors, category_code: m?.[1] || null, artwork_id: m?.[2] || null,
  attachment_key: pdfKeys[0] || null, attachment_name: pdfKeys[0] ? item.binary[pdfKeys[0]].fileName : null,
  attachment_bytes: size, source_message_id: j.id, report_to: s.report_to, started_at: new Date().toISOString(),
  execution_id: $execution.id } };
"""

LOOKUP_JS = r"""// Explicit pair lookup in the approved manifest (no name search, no 'latest file').
const ctx = $('03 Validate input').item.json;
const man = $json.manifest || {};
const errors = [];
const hits = (man.pairs || []).filter(p => p.category_code === ctx.category_code && p.artwork_id === ctx.artwork_id);
if (hits.length !== 1) errors.push(`MANIFEST_MATCHES_${hits.length}_EXPECTED_1`);
const p = hits[0] || {};
if (hits.length === 1 && p.approved_for_external !== true) errors.push('PAIR_NOT_APPROVED_FOR_EXTERNAL_PROCESSING');
if (hits.length === 1 && !p.baseline_file_id) errors.push('BASELINE_FILE_ID_MISSING');
if (hits.length === 1 && p.expected_after_filename && p.expected_after_filename !== ctx.attachment_name) errors.push('ATTACHMENT_NAME_DIFFERS_FROM_MANIFEST');
return { json: { ...ctx, valid: errors.length === 0, errors: [...(ctx.errors || []), ...errors],
  baseline_file_id: p.baseline_file_id || null, requests_json: p.requests ? JSON.stringify(p.requests) : '',
  page_map_json: p.page_map ? JSON.stringify(p.page_map) : '' } };
"""

ASSEMBLE_JS = r"""const ctx = $('07 Lookup pair in manifest').item.json;
const trig = $('01 Gmail: new revision').item;
return { json: ctx, binary: { before: $input.item.binary.before, after: trig.binary[ctx.attachment_key] } };
"""

COMPOSE_JS = r"""const ctx = $('07 Lookup pair in manifest').item.json;
const r = $json;
const ok = r.ok === true;
const n = r.notification || {};
const subject = ok ? `FINALRESULT | ${ctx.category_code} | ${ctx.artwork_id} | ${r.summary.overall_status}`
                   : `FINALRESULT | ${ctx.category_code} | ${ctx.artwork_id} | NOT_COMPARED ${r.error_code || ''}`;
const html = ok ? (n.html + '<p>첨부 HTML 보고서를 브라우저로 여세요. 최종 승인이 아닙니다.</p>')
                : `<p>비교하지 못했습니다: ${r.error_code || 'UNKNOWN'}. 결과를 '변경 없음'으로 해석하지 마세요.</p>`;
const fallback = Buffer.from(`<!doctype html><meta charset="utf-8"><p>NOT_COMPARED: ${r.error_code || 'UNKNOWN'}</p>`).toString('base64');
return { json: { ...ctx, subject, html, compare_ok: ok, overall_status: r.summary?.overall_status || null,
  summary: r.summary || null, compare_error: r.error_code || null },
  binary: { audit_report: { data: (ok && r.report_html_b64) ? r.report_html_b64 : fallback, mimeType: 'text/html',
  fileName: `FINAL_${ctx.category_code}_${ctx.artwork_id}.html` } } };
"""

DIAG_JS = r"""const j = $json;
const list = (j.errors || []).map(e => `<li>${String(e).replace(/[<>&]/g, '')}</li>`).join('');
const html = `<p>입력 확인이 필요합니다 (비교하지 않음 — '변경 없음'이 아닙니다):</p><ul>${list}</ul>`;
return { json: { ...j, subject: `FINALRESULT | INPUT CHECK | ${j.category_code || '-'} | ${j.artwork_id || '-'}`, html,
  compare_ok: false, overall_status: null },
  binary: { audit_report: { data: Buffer.from('<!doctype html><meta charset="utf-8">' + html).toString('base64'),
  mimeType: 'text/html', fileName: 'FINAL_INPUT_CHECK.html' } } };
"""

LOG_JS = r"""let prep;
try { prep = $('12 Compose result mail').item.json; } catch (e) { prep = $('E Input/pair problem mail').item.json; }
const sent = $('13 Send result to me').item.json;
return { json: { execution_id: prep.execution_id, mode: 'APPROVED_EXTERNAL_B', category_code: prep.category_code,
  artwork_id: prep.artwork_id, compare_ok: prep.compare_ok, overall_status: prep.overall_status,
  delivery: { status: sent.id ? 'SENT_ACCEPTED_BY_GMAIL' : 'DELIVERY_RESPONSE_REQUIRES_CHECK', gmail_id: sent.id || null },
  receipt_confirmed: 'CHECK_INBOX_MANUALLY', llm_tokens: 'NOT_CALLED', finished_at: new Date().toISOString() } };
"""


def b_workflow():
    nodes = [
        node("01 Gmail: new revision", "n8n-nodes-base.gmailTrigger", 1.2, [0, 300], {
            "pollTimes": {"item": [{"mode": "everyMinute"}]}, "simple": False,
            "filters": {"q": "in:inbox subject:FINALCHECK has:attachment filename:pdf -subject:FINALRESULT -label:FINAL_DONE",
                        "readStatus": "both"},
            "options": {"downloadAttachments": True, "dataPropertyAttachmentsPrefixName": "attachment_"}}),
        node("02 Settings", "n8n-nodes-base.set", 3.4, [220, 300], {
            "assignments": {"assignments": [
                assign("b_mode_enabled", False, "boolean"),
                assign("approval_note", ""),
                assign("report_to", ""),
                assign("allowed_sender", ""),
                assign("manifest_file_id", ""),
                assign("b_service_url", "https://REPLACE-WITH-YOUR-B-SERVICE/b/compare"),
                assign("max_attachment_mb", 20, "number"),
            ]}, "includeOtherFields": True, "options": {}}),
        node("03 Validate input", "n8n-nodes-base.code", 2, [440, 300], {"mode": "runOnceForEachItem", "jsCode": VALIDATE_JS}),
        node("04 Input OK?", "n8n-nodes-base.if", 2.2, [660, 300], cond_true("={{ $json.valid }}", "b-valid")),
        node("05 Download approved manifest", "n8n-nodes-base.googleDrive", 3, [880, 200], {
            "operation": "download", "fileId": {"__rl": True, "value": "={{ $('02 Settings').first().json.manifest_file_id }}", "mode": "id"},
            "options": {"binaryPropertyName": "manifest"}}),
        node("06 Read manifest JSON", "n8n-nodes-base.extractFromFile", 1, [1100, 200], {
            "operation": "fromJson", "binaryPropertyName": "manifest", "destinationKey": "manifest", "options": {}}),
        node("07 Lookup pair in manifest", "n8n-nodes-base.code", 2, [1320, 200], {"mode": "runOnceForEachItem", "jsCode": LOOKUP_JS}),
        node("08 Pair OK?", "n8n-nodes-base.if", 2.2, [1540, 200], cond_true("={{ $json.valid }}", "b-pair")),
        node("09 Download baseline (before)", "n8n-nodes-base.googleDrive", 3, [1760, 100], {
            "operation": "download", "fileId": {"__rl": True, "value": "={{ $json.baseline_file_id }}", "mode": "id"},
            "options": {"binaryPropertyName": "before"}}),
        node("10 Attach before + after", "n8n-nodes-base.code", 2, [1980, 100], {"mode": "runOnceForEachItem", "jsCode": ASSEMBLE_JS}),
        node("11 B compare service", "n8n-nodes-base.httpRequest", 4.2, [2200, 100], {
            "method": "POST", "url": "={{ $('02 Settings').first().json.b_service_url }}",
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
            "sendBody": True, "contentType": "multipart-form-data",
            "bodyParameters": {"parameters": [
                {"parameterType": "formBinaryData", "name": "before", "inputDataFieldName": "before"},
                {"parameterType": "formBinaryData", "name": "after", "inputDataFieldName": "after"},
                {"name": "category_code", "value": "={{ $json.category_code }}"},
                {"name": "artwork_id", "value": "={{ $json.artwork_id }}"},
                {"name": "requests_json", "value": "={{ $json.requests_json }}"},
                {"name": "page_map_json", "value": "={{ $json.page_map_json }}"},
            ]},
            "options": {"timeout": 900000, "response": {"response": {"responseFormat": "json", "neverError": True}}}}),
        node("12 Compose result mail", "n8n-nodes-base.code", 2, [2420, 100], {"mode": "runOnceForEachItem", "jsCode": COMPOSE_JS}),
        node("13 Send result to me", "n8n-nodes-base.gmail", 2.1, [2640, 300], {
            "resource": "message", "operation": "send",
            "sendTo": "={{ $('02 Settings').first().json.report_to }}",
            "subject": "={{ $json.subject }}", "emailType": "html", "message": "={{ $json.html }}",
            "options": {"appendAttribution": False, "senderName": "FINAL? 원화 검수",
                        "attachmentsUi": {"attachmentsBinary": [{"property": "audit_report"}]}}}),
        node("14 Mark processed (label)", "n8n-nodes-base.gmail", 2.1, [2860, 300], {
            "resource": "message", "operation": "addLabels",
            "messageId": "={{ $('03 Validate input').item.json.source_message_id }}", "labelIds": []}),
        node("15 Execution log", "n8n-nodes-base.code", 2, [3080, 300], {"mode": "runOnceForEachItem", "jsCode": LOG_JS}),
        node("E Input/pair problem mail", "n8n-nodes-base.code", 2, [1760, 500], {"mode": "runOnceForEachItem", "jsCode": DIAG_JS}),
        sticky("READ FIRST (B)", [-40, -300],
               "## APPROVED_EXTERNAL_B — 기본 OFF\n**외부 처리 허가를 받은 자료 또는 비기밀 재제작 자료만** 사용합니다.\n"
               "회사 원화를 개인 Gmail/Drive/Railway로 보내지 마세요. 로컬 워크플로와 섞지 마세요.\n"
               "02 Settings: b_mode_enabled=true, approval_note(승인 근거), report_to, allowed_sender, manifest_file_id, b_service_url\n"
               "자격증명: Gmail(01·13·14), Google Drive(05·09), Header Auth X-FINAL-Token(11)\n14 노드에서 FINAL_DONE 라벨 선택.", 760, 280, 3),
        sticky("MANIFEST (B)", [860, -300],
               "## Drive의 manifest_b.json (승인 자료 전용)\n`{\"pairs\":[{\"category_code\":\"SET\",\"artwork_id\":\"DEMO01\",\"approved_for_external\":true,"
               "\"baseline_file_id\":\"<Drive 파일 ID>\",\"expected_after_filename\":\"DEMO01_after.pdf\"}]}`\n"
               "메일 제목: `FINALCHECK | SET | DEMO01` + PDF 1개 첨부.\n제목만 믿지 않고 manifest의 짝·파일명과 대조합니다.", 760, 280, 6),
    ]
    conns = {}
    connect(conns, "01 Gmail: new revision", ["02 Settings"])
    connect(conns, "02 Settings", ["03 Validate input"])
    connect(conns, "03 Validate input", ["04 Input OK?"])
    connect(conns, "04 Input OK?", ["05 Download approved manifest"], ["E Input/pair problem mail"])
    connect(conns, "05 Download approved manifest", ["06 Read manifest JSON"])
    connect(conns, "06 Read manifest JSON", ["07 Lookup pair in manifest"])
    connect(conns, "07 Lookup pair in manifest", ["08 Pair OK?"])
    connect(conns, "08 Pair OK?", ["09 Download baseline (before)"], ["E Input/pair problem mail"])
    connect(conns, "09 Download baseline (before)", ["10 Attach before + after"])
    connect(conns, "10 Attach before + after", ["11 B compare service"])
    connect(conns, "11 B compare service", ["12 Compose result mail"])
    connect(conns, "12 Compose result mail", ["13 Send result to me"])
    connect(conns, "E Input/pair problem mail", ["13 Send result to me"])
    connect(conns, "13 Send result to me", ["14 Mark processed (label)"])
    connect(conns, "14 Mark processed (label)", ["15 Execution log"])
    return {"name": "FINAL? APPROVED_EXTERNAL_B — 승인 자료 전용 Gmail+Drive", "nodes": nodes, "connections": conns,
            "active": False,
            "settings": {"executionOrder": "v1", "timezone": "Asia/Seoul", "saveDataSuccessExecution": "all",
                         "saveDataErrorExecution": "all"},
            "pinData": {}, "meta": {"templateCredsSetupCompleted": False}, "tags": []}


def validate(wf):
    names = {n["name"] for n in wf["nodes"]}
    assert len(names) == len(wf["nodes"]), "duplicate node names"
    for src, c in wf["connections"].items():
        assert src in names, src
        for outs in c["main"]:
            for t in outs:
                assert t["node"] in names, t["node"]
    assert wf["active"] is False and wf["pinData"] == {}
    for n in wf["nodes"]:
        assert "credentials" not in n


def main():
    OUT.mkdir(exist_ok=True)
    for fname, wf in (("FINAL_Local_Workflow.json", local_workflow()), ("FINAL_B_Approved_Workflow.json", b_workflow())):
        validate(wf)
        (OUT / fname).write_text(json.dumps(wf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "file": fname, "nodes": len(wf["nodes"])}))


if __name__ == "__main__":
    main()
