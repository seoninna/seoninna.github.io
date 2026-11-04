#!/usr/bin/env python3
"""FINAL? 로컬 비교 API (n8n ↔ 로컬 비교 엔진 연결용, LOCAL_ONLY).

  python local_api.py --config config.local.json

- 기본 127.0.0.1(이 PC 내부)에서만 열립니다. 공개 터널·외부 공개를 만들지 않습니다.
- 경로·URL은 받지 않습니다. manifest의 pair_id만 받습니다.
- 응답에는 원화 문구·파일명·경로가 없는 '안전 요약'만 들어갑니다.
- 요청 로그(접속 기록)를 화면에 출력하지 않습니다.

Endpoints (header X-FINAL-Token 필수):
  GET  /health
  POST /scan      {}                                  -> 비교 대기 pair_id 목록
  POST /compare   {"pair_id": "...", "event_id": "..."}
  POST /delivery  {"run_key": "...", "status": "...", "message_id": "..."}
"""
from __future__ import annotations

import argparse
import hmac
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from final_check.common import (FinalError, emit, install_network_guard, load_local_config,  # noqa: E402
                                quiet_pdf_library)
from final_check.local_runner import find_pending, record_delivery, run_pair  # noqa: E402

MAX_BODY = 4096
ALLOWED = {
    "/scan": set(),
    "/compare": {"pair_id", "event_id"},
    "/delivery": {"run_key", "status", "message_id"},
}


def check_bind(cfg: dict[str, Any]) -> tuple[str, int, str]:
    api = cfg["local_api"]
    host = str(api.get("host", "127.0.0.1"))
    port = int(api.get("port", 8765))
    token = str(api.get("token") or "")
    if host not in ("127.0.0.1", "localhost", "::1") and not api.get("allow_non_loopback_bind"):
        raise FinalError("LOCAL_API_HOST_MUST_BE_LOOPBACK")
    if host in ("0.0.0.0", "::"):
        raise FinalError("LOCAL_API_REFUSES_ALL_INTERFACES_BIND")
    if len(token) < 24 or "CHANGE_ME" in token:
        raise FinalError("LOCAL_API_TOKEN_TOO_SHORT_SET_24_PLUS_RANDOM_CHARS")
    return host, port, token


def make_handler(cfg: dict[str, Any], token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FINAL-local"
        sys_version = ""

        def log_message(self, *args: Any) -> None:  # no access logs
            return

        def _send(self, code: int, obj: dict[str, Any]) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _auth(self) -> bool:
            got = self.headers.get("X-FINAL-Token", "")
            return hmac.compare_digest(got.encode(), token.encode())

        def do_GET(self) -> None:  # noqa: N802
            if not self._auth():
                return self._send(401, {"ok": False, "error_code": "UNAUTHORIZED"})
            if self.path == "/health":
                return self._send(200, {"ok": True, "mode": "LOCAL_ONLY",
                                        "safe_email_enabled": bool(cfg["notification"].get("safe_email_enabled"))})
            return self._send(404, {"ok": False, "error_code": "NOT_FOUND"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._auth():
                return self._send(401, {"ok": False, "error_code": "UNAUTHORIZED"})
            if self.path not in ALLOWED:
                return self._send(404, {"ok": False, "error_code": "NOT_FOUND"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"ok": False, "error_code": "BAD_CONTENT_LENGTH"})
            if length > MAX_BODY:
                return self._send(413, {"ok": False, "error_code": "BODY_TOO_LARGE_SEND_PAIR_ID_ONLY"})
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._send(400, {"ok": False, "error_code": "BODY_MUST_BE_JSON_OBJECT"})
            extra = set(body) - ALLOWED[self.path]
            if extra:
                return self._send(400, {"ok": False, "error_code": "UNKNOWN_FIELDS_PATHS_AND_URLS_NOT_ACCEPTED"})
            try:
                if self.path == "/scan":
                    res = find_pending(cfg)
                elif self.path == "/compare":
                    res = run_pair(cfg, str(body.get("pair_id", "")),
                                   event_id=str(body["event_id"]) if body.get("event_id") else None)
                else:
                    res = record_delivery(cfg, str(body.get("run_key", "")), str(body.get("status", "")),
                                          str(body["message_id"]) if body.get("message_id") else None)
                return self._send(200, res)
            except FinalError as err:
                return self._send(200, {"ok": False, "error_code": err.code, **err.safe_fields})
            except Exception as err:  # noqa: BLE001
                return self._send(500, {"ok": False, "error_code": "UNEXPECTED_ERROR", "error_type": type(err).__name__})

    return Handler


def build_server(cfg: dict[str, Any]) -> HTTPServer:
    host, port, token = check_bind(cfg)
    return HTTPServer((host, port), make_handler(cfg, token))


def main() -> int:
    ap = argparse.ArgumentParser(description="FINAL? local API for n8n")
    ap.add_argument("--config", default="config.local.json")
    args = ap.parse_args()
    install_network_guard()
    quiet_pdf_library()
    try:
        cfg = load_local_config(args.config)
        server = build_server(cfg)
    except FinalError as err:
        emit({"ok": False, "error_code": err.code})
        return 2
    except OSError:
        emit({"ok": False, "error_code": "PORT_IN_USE_OR_BIND_FAILED"})
        return 2
    emit({"ok": True, "listening": f"{server.server_address[0]}:{server.server_address[1]}",
          "stop": "Ctrl+C"})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    emit({"ok": True, "stopped": True})
    return 0


if __name__ == "__main__":
    sys.exit(main())
