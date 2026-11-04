#!/usr/bin/env python3
"""FINAL? APPROVED_EXTERNAL_B 비교 서비스 (외부 처리 허가 자료·비기밀 재제작 자료 전용).

이 서비스는 LOCAL_ONLY 프로그램과 완전히 분리되어 있습니다.
- 로컬 원화 폴더(root_dir)를 읽지 않습니다. 설정에 root_dir가 있으면 시작을 거부합니다.
- n8n(B안)이 보낸 before/after PDF 2개만 임시 폴더에서 비교하고, 처리 후 삭제합니다.
- 승인 기록(approved_by / approved_at / scope_note / data_classification)이 비어 있으면 시작하지 않습니다.
- 외부 AI를 호출하지 않습니다. 결과는 JSON 요약 + 이미지 포함 HTML 보고서(base64)입니다.

  python b_service/b_service.py --config config.b.json
환경변수 PORT가 있으면 그 포트를 사용합니다(Railway 등). 토큰은 FINAL_B_TOKEN 환경변수 또는 설정값.
"""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import re
import shutil
import sys
import tempfile
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from final_check import engine, report  # noqa: E402
from final_check.common import (B_MODE, DEFAULT_CONFIG, FinalError, _merge, emit, install_network_guard,  # noqa: E402
                                quiet_pdf_library, sha256_file, short_hash)

CODE_RE = re.compile(r"^[A-Z]{2,12}$")
ARTWORK_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")
CLASSIFICATIONS = {"NON_CONFIDENTIAL_RECREATED_SAMPLE", "EXTERNALLY_APPROVED_BY_COMPANY"}


def load_b_config(path: str) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise FinalError("B_CONFIG_NOT_FOUND") from None
    except json.JSONDecodeError:
        raise FinalError("B_CONFIG_JSON_SYNTAX_ERROR") from None
    if raw.get("privacy_mode") != B_MODE:
        raise FinalError("B_SERVICE_REQUIRES_PRIVACY_MODE_APPROVED_EXTERNAL_B")
    if raw.get("root_dir") or raw.get("output_dir"):
        raise FinalError("B_SERVICE_MUST_NOT_HAVE_LOCAL_ROOT_OR_OUTPUT")
    appr = raw.get("approval") or {}
    for key in ("approved_by", "approved_at", "scope_note"):
        if len(str(appr.get(key) or "").strip()) < 2:
            raise FinalError("B_APPROVAL_RECORD_INCOMPLETE")
    if appr.get("data_classification") not in CLASSIFICATIONS:
        raise FinalError("B_DATA_CLASSIFICATION_INVALID")
    if raw.get("cloud_llm_enabled"):
        raise FinalError("B_LLM_NOT_IMPLEMENTED_KEEP_FALSE")
    cfg = _merge(DEFAULT_CONFIG, {k: v for k, v in raw.items() if k in ("processing", "text", "visual")})
    cfg["processing"]["page_isolation"] = "inline"
    cfg["processing"]["pdf_report"] = False
    svc = raw.get("service") or {}
    cfg["b"] = {
        "token": os.environ.get("FINAL_B_TOKEN") or str(svc.get("token") or ""),
        "max_upload_mb": float(svc.get("max_upload_mb", 20)),
        "max_report_mb": float(svc.get("max_report_mb", 8)),
        "allowed_categories": svc.get("allowed_category_codes", ["SET", "SINGLE"]),
        "host": str(svc.get("host", "127.0.0.1")),
        "port": int(os.environ.get("PORT") or svc.get("port", 8780)),
        "approval": appr,
    }
    if len(cfg["b"]["token"]) < 24 or "CHANGE_ME" in cfg["b"]["token"]:
        raise FinalError("B_TOKEN_TOO_SHORT")
    return cfg


def inline_images(html_text: str, image_dir: Path, max_bytes: int) -> tuple[str, bool]:
    total = 0
    dropped = False

    def repl(m: re.Match[str]) -> str:
        nonlocal total, dropped
        f = image_dir / m.group(1)
        try:
            data = f.read_bytes()
        except OSError:
            return m.group(0)
        if total + len(data) > max_bytes:
            dropped = True
            return "src='' data-omitted='size-limit'"
        total += len(data)
        return "src='data:image/png;base64," + base64.b64encode(data).decode() + "'"

    return re.sub(r"src='images/([^']+)'", repl, html_text), dropped


def parse_multipart(content_type: str, body: bytes) -> dict[str, Any]:
    msg = BytesParser(policy=email_policy).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    if not msg.is_multipart():
        raise FinalError("B_MULTIPART_REQUIRED")
    out: dict[str, Any] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        if part.get_filename() is not None:
            out[name] = {"filename": part.get_filename(), "data": part.get_payload(decode=True) or b""}
        else:
            out[name] = (part.get_payload(decode=True) or b"").decode("utf-8", "replace").strip()
    return out


def compare_upload(cfg: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    code = str(fields.get("category_code") or "")
    artwork = str(fields.get("artwork_id") or "")
    if not CODE_RE.match(code) or code not in cfg["b"]["allowed_categories"]:
        raise FinalError("B_CATEGORY_CODE_INVALID")
    if not ARTWORK_RE.match(artwork):
        raise FinalError("B_ARTWORK_ID_INVALID")
    for side in ("before", "after"):
        f = fields.get(side)
        if not isinstance(f, dict) or not f["data"].startswith(b"%PDF"):
            raise FinalError(f"B_{side.upper()}_PDF_MISSING_OR_NOT_PDF")
    req_data = None
    if fields.get("requests_json"):
        try:
            req_data = json.loads(fields["requests_json"])
        except json.JSONDecodeError:
            raise FinalError("B_REQUESTS_JSON_INVALID") from None
        if not (req_data.get("requests") or req_data.get("protected_fields")):
            req_data = None
    page_map = []
    if fields.get("page_map_json"):
        try:
            page_map = json.loads(fields["page_map_json"])
        except json.JSONDecodeError:
            raise FinalError("B_PAGE_MAP_JSON_INVALID") from None
    work = Path(tempfile.mkdtemp(prefix="final_b_"))
    try:
        bp, ap = work / "before.pdf", work / "after.pdf"
        bp.write_bytes(fields["before"]["data"])
        ap.write_bytes(fields["after"]["data"])
        bh, ah = sha256_file(bp), sha256_file(ap)
        pair = {"pair_id": f"B{code}_{short_hash(artwork + bh + ah, 10)}", "category": code, "category_code": code,
                "artwork_id": artwork, "before_relative_path": "upload:before.pdf", "after_relative_path": "upload:after.pdf",
                "page_map": page_map}
        if req_data is not None:
            req_data.setdefault("pair_id", pair["pair_id"])
        rep = engine.compare_files(before_path=bp, after_path=ap, before_hash=bh, after_hash=ah, pair=pair,
                                   requests_data=req_data, cfg=cfg, job_dir=work / "job", report_dir=work / "report",
                                   cache_dir=None)
        run_key = short_hash(pair["pair_id"], 16)
        summ = report.safe_summary(rep, run_key, mode=B_MODE)
        html_text, dropped = inline_images(report.build_html(rep), work / "report" / "images",
                                           int(cfg["b"]["max_report_mb"] * 1024 * 1024))
        subject, text, body = report.safe_notification(summ)
        return {"ok": True, "mode": B_MODE, "pair_id": pair["pair_id"], "summary": summ,
                "hashes": rep["hashes"], "report_images_omitted_for_size": dropped,
                "report_html_b64": base64.b64encode(html_text.encode("utf-8")).decode(),
                "notification": {"subject": subject, "text": text, "html": body},
                "approval": {k: cfg["b"]["approval"].get(k) for k in ("data_classification", "scope_note")}}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def make_handler(cfg: dict[str, Any]):
    token = cfg["b"]["token"]
    max_body = int(cfg["b"]["max_upload_mb"] * 2 * 1024 * 1024 + 65536)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            return

        def _send(self, code: int, obj: dict[str, Any]) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                return self._send(200, {"ok": True, "mode": B_MODE})
            return self._send(404, {"ok": False, "error_code": "NOT_FOUND"})

        def do_POST(self) -> None:  # noqa: N802
            if not hmac.compare_digest(self.headers.get("X-FINAL-Token", "").encode(), token.encode()):
                return self._send(401, {"ok": False, "error_code": "UNAUTHORIZED"})
            if self.path != "/b/compare":
                return self._send(404, {"ok": False, "error_code": "NOT_FOUND"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > max_body:
                # Never truncate silently: refuse oversize uploads.
                return self._send(413, {"ok": False, "error_code": "B_UPLOAD_TOO_LARGE_NOT_TRUNCATED"})
            body = self.rfile.read(length)
            try:
                fields = parse_multipart(self.headers.get("Content-Type", ""), body)
                for side in ("before", "after"):
                    f = fields.get(side)
                    if isinstance(f, dict) and len(f["data"]) > cfg["b"]["max_upload_mb"] * 1024 * 1024:
                        raise FinalError("B_FILE_OVER_MAX_UPLOAD_MB_NOT_TRUNCATED")
                return self._send(200, compare_upload(cfg, fields))
            except FinalError as err:
                return self._send(200, {"ok": False, "error_code": err.code})
            except Exception as err:  # noqa: BLE001
                return self._send(500, {"ok": False, "error_code": "UNEXPECTED_ERROR", "error_type": type(err).__name__})

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.b.json")
    args = ap.parse_args()
    install_network_guard()  # the service itself never needs outbound connections
    quiet_pdf_library()
    try:
        cfg = load_b_config(args.config)
        server = HTTPServer((cfg["b"]["host"], cfg["b"]["port"]), make_handler(cfg))
    except FinalError as err:
        emit({"ok": False, "error_code": err.code})
        return 2
    except OSError:
        emit({"ok": False, "error_code": "PORT_IN_USE_OR_BIND_FAILED"})
        return 2
    emit({"ok": True, "mode": B_MODE, "listening": f"{cfg['b']['host']}:{cfg['b']['port']}"})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
