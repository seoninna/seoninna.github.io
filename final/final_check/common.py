"""Shared helpers for FINAL? local artwork comparison.

Design rules (enforced in code where possible):
- Source PDFs are opened read-only and never written, moved or renamed.
- Console output is a single JSON line with non-sensitive codes and counts.
- Exceptions are converted to error codes; tracebacks are never printed
  (they can contain file paths or text fragments).
- In LOCAL_ONLY mode a process-level socket guard refuses outbound
  connections to non-loopback addresses. This is a programming safeguard,
  NOT an operating-system firewall. See docs/SECURITY_AND_PERMISSIONS_KO.md.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import socket
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ENGINE_VERSION = "3.0.0"
LOCAL_MODE = "LOCAL_ONLY"
B_MODE = "APPROVED_EXTERNAL_B"


class FinalError(Exception):
    """Error carrying only a non-sensitive code (never paths or PDF text)."""

    def __init__(self, code: str, **safe_fields: Any) -> None:
        super().__init__(code)
        self.code = code
        self.safe_fields = safe_fields


# --------------------------------------------------------------------------
# Console / error handling
# --------------------------------------------------------------------------

def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _silent_excepthook(exc_type, exc, tb):  # pragma: no cover - last resort
    emit({"ok": False, "error_code": "UNHANDLED_ERROR", "error_type": exc_type.__name__})


def quiet_pdf_library() -> None:
    """Stop MuPDF from printing warnings that may echo document fragments."""
    try:
        import pymupdf  # type: ignore

        pymupdf.TOOLS.mupdf_display_errors(False)
        pymupdf.TOOLS.mupdf_display_warnings(False)
    except Exception:
        pass


def run_cli(main: Callable[[], dict[str, Any]], local_only: bool = True) -> int:
    """Run a CLI entry point with safe output. Returns process exit code."""
    sys.excepthook = _silent_excepthook
    if local_only:
        install_network_guard()
    quiet_pdf_library()
    try:
        result = main()
        result.setdefault("ok", True)
        emit(result)
        return 0 if result.get("ok") else 2
    except FinalError as err:
        emit({"ok": False, "error_code": err.code, **err.safe_fields})
        return 2
    except KeyboardInterrupt:
        emit({"ok": False, "error_code": "INTERRUPTED_BY_USER"})
        return 130
    except MemoryError:
        emit({"ok": False, "error_code": "OUT_OF_MEMORY_LOWER_DPI_OR_PIXELS"})
        return 2
    except Exception as err:  # noqa: BLE001 - never print message/traceback
        emit({"ok": False, "error_code": "UNEXPECTED_ERROR", "error_type": type(err).__name__})
        return 2


# --------------------------------------------------------------------------
# Network guard (LOCAL_ONLY)
# --------------------------------------------------------------------------

_GUARD_INSTALLED = False
_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "ip6-localhost"}


def _is_loopback(host: Any) -> bool:
    if host is None:
        return True
    h = str(host).strip("[]").lower()
    return h in _LOOPBACK_NAMES or h.startswith("127.")


def install_network_guard() -> None:
    """Refuse outbound non-loopback socket connections in this process."""
    global _GUARD_INSTALLED
    if _GUARD_INSTALLED:
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    original_create_connection = socket.create_connection

    def check(sock: socket.socket, address: Any) -> None:
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0] if isinstance(address, tuple) else address
            if not _is_loopback(host):
                raise FinalError("NETWORK_BLOCKED_LOCAL_ONLY")

    def guarded_connect(self, address):  # type: ignore[no-untyped-def]
        check(self, address)
        return original_connect(self, address)

    def guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
        check(self, address)
        return original_connect_ex(self, address)

    def guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not _is_loopback(host):
            raise FinalError("NETWORK_BLOCKED_LOCAL_ONLY")
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not _is_loopback(address[0]):
            raise FinalError("NETWORK_BLOCKED_LOCAL_ONLY")
        return original_create_connection(address, *args, **kwargs)

    # A loopback proxy could forward traffic outside, so proxy settings are
    # removed for this process (LOCAL_ONLY programs never need a proxy).
    for var in list(os.environ):
        if var.lower() in ("http_proxy", "https_proxy", "all_proxy", "ftp_proxy", "ws_proxy", "wss_proxy"):
            os.environ.pop(var, None)
    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]
    os.environ["FINAL_NETWORK_GUARD"] = "ON"
    _GUARD_INSTALLED = True


def network_guard_active() -> bool:
    return _GUARD_INSTALLED


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def norm_name(value: str) -> str:
    return nfc(value).casefold().strip()


def inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    """Streaming hash; never loads the whole PDF into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def short_hash(text: str, n: int = 10) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def _private_chmod(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("wb") as handle:
        handle.write(data)
    _private_chmod(temp)
    temp.replace(path)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def matches_ignore(name: str, patterns: list[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, p.lower()) for p in patterns)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": "3.0",
    "privacy_mode": LOCAL_MODE,
    "root_dir": "",
    "output_dir": "",
    "folder_names": {
        "before": ["before", "원화 수정 전 before", "원화 수정 전", "수정 전", "수정전"],
        "after": ["after", "원화 수정 후 after", "원화 수정 후", "수정 후", "수정후"],
    },
    "groups": [
        {"category": "세트", "code": "SET", "folder_names": ["세트"], "before_dir": "", "after_dir": ""},
        {"category": "단품", "code": "SINGLE", "folder_names": ["단품"], "before_dir": "", "after_dir": ""},
    ],
    "manifest_path": "",
    "requests_dir": "",
    "matching": {
        "cross_category": False,
        "auto_select_latest": False,
        "human_confirmation_required": True,
        "weak_similarity_threshold": 0.75,
    },
    "file_rules": {
        "stable_seconds": 120,
        "ignore_patterns": ["~$*", ".*", "*.tmp", "*.part", "*.crdownload", "*.download", "*.partial"],
        "file_size_warning_mb": 300,
        "max_file_size_mb": 4096,
    },
    "processing": {
        "preview_dpi": 100,
        "min_visual_dpi": 40,
        "fine_crop_dpi": 300,
        "max_page_pixels": 12_000_000,
        "max_fine_crop_pixels": 4_000_000,
        "max_pages_per_file": 400,
        "page_timeout_seconds": 240,
        "max_retries": 2,
        "page_isolation": "process",
        "ocr_enabled": False,
        "artboard_hint": True,
        "pdf_report": True,
    },
    "text": {
        "position_tolerance_pt": 3.0,
        "line_match_ratio": 0.5,
        "max_match_distance_pt": 150.0,
    },
    "visual": {
        "pixel_threshold": 48,
        "tolerance_px": 0,
        "pixel_threshold_after_shift": 64,
        "tolerance_px_after_shift": 0,
        "cell_px": 6,
        "merge_gap_cells": 2,
        "min_region_pixels": 6,
        "max_regions_per_page": 150,
        "canvas_shift_max_fraction": 0.25,
        "move_match_score": 0.85,
        "fine_crop_max_region_fraction": 0.05,
    },
    "external": {
        "cloud_llm_enabled": False,
        "external_storage_enabled": False,
        "external_email_enabled": False,
    },
    "notification": {
        "safe_email_enabled": False,
        "approval_note": "",
    },
    "local_api": {
        "host": "127.0.0.1",
        "port": 8765,
        "token": "CHANGE_ME_TO_A_LONG_RANDOM_STRING",
        "allow_non_loopback_bind": False,
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            out[key] = _merge(base[key], value)
        else:
            out[key] = value
    return out


def validate_local_config(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FinalError("CONFIG_MUST_BE_OBJECT")
    cfg = _merge(DEFAULT_CONFIG, raw)
    if cfg.get("privacy_mode") != LOCAL_MODE:
        raise FinalError("LOCAL_PROGRAMS_REQUIRE_PRIVACY_MODE_LOCAL_ONLY")
    for key in ("root_dir", "output_dir"):
        value = cfg.get(key)
        if not isinstance(value, str) or not value.strip() or "REPLACE_" in value:
            raise FinalError("CONFIGURE_ROOT_AND_OUTPUT_DIRECTORIES")
    m = cfg["matching"]
    if m.get("cross_category") is not False:
        raise FinalError("CROSS_CATEGORY_MATCHING_NOT_ALLOWED")
    if m.get("auto_select_latest") is not False:
        raise FinalError("AUTO_SELECT_LATEST_NOT_ALLOWED")
    if m.get("human_confirmation_required") is not True:
        raise FinalError("HUMAN_CONFIRMATION_CANNOT_BE_DISABLED")
    ext = cfg["external"]
    if any(bool(ext.get(k)) for k in ("cloud_llm_enabled", "external_storage_enabled", "external_email_enabled")):
        # Local mode never uploads data or calls an LLM. External use lives in
        # the separate APPROVED_EXTERNAL_B service with its own config file.
        raise FinalError("EXTERNAL_TRANSFER_NOT_ALLOWED_IN_LOCAL_ONLY")
    if cfg["processing"].get("ocr_enabled"):
        raise FinalError("OCR_NOT_IMPLEMENTED_KEEP_FALSE")
    note = cfg["notification"]
    if note.get("safe_email_enabled") and len(str(note.get("approval_note") or "").strip()) < 5:
        raise FinalError("SAFE_EMAIL_REQUIRES_APPROVAL_NOTE")
    groups = cfg.get("groups")
    if not isinstance(groups, list) or len(groups) < 2:
        raise FinalError("EXPECTED_SET_AND_SINGLE_GROUPS")
    cats = [g.get("category") for g in groups if isinstance(g, dict)]
    codes = [g.get("code") for g in groups if isinstance(g, dict)]
    if len(set(cats)) != len(groups) or len(set(codes)) != len(groups) or not all(cats) or not all(codes):
        raise FinalError("GROUP_CATEGORY_AND_CODE_MUST_BE_UNIQUE")
    for code in codes:
        if not str(code).isalnum() or not str(code).isupper():
            raise FinalError("GROUP_CODE_MUST_BE_UPPERCASE_ALNUM")
    proc = cfg["processing"]
    if proc.get("page_isolation") not in ("process", "inline"):
        raise FinalError("PAGE_ISOLATION_MUST_BE_PROCESS_OR_INLINE")
    root = Path(cfg["root_dir"]).expanduser()
    out_raw = Path(cfg["output_dir"]).expanduser()
    if not root.exists() or not root.is_dir():
        raise FinalError("ROOT_DIR_NOT_FOUND_OR_NOT_DIRECTORY")
    if root.is_symlink():
        raise FinalError("ROOT_SYMLINK_NOT_ALLOWED")
    if out_raw.is_symlink():
        raise FinalError("OUTPUT_SYMLINK_NOT_ALLOWED")
    root_r = root.resolve(strict=True)
    out_r = out_raw.resolve()
    if inside(out_r, root_r) or inside(root_r, out_r):
        raise FinalError("SOURCE_AND_OUTPUT_MUST_BE_SEPARATE")
    cfg["_root"] = root_r
    cfg["_out"] = out_r
    cfg["_manifest"] = Path(cfg["manifest_path"]).expanduser().resolve() if cfg.get("manifest_path") else out_r / "pair_manifest.local.json"
    cfg["_requests_dir"] = Path(cfg["requests_dir"]).expanduser().resolve() if cfg.get("requests_dir") else out_r / "requests"
    for key in ("_manifest", "_requests_dir"):
        if inside(cfg[key], root_r):
            raise FinalError("MANIFEST_AND_REQUESTS_MUST_BE_OUTSIDE_SOURCE")
    return cfg


def load_local_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FinalError("CONFIG_FILE_NOT_FOUND")
    try:
        with p.open(encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as err:
        raise FinalError("CONFIG_JSON_SYNTAX_ERROR", line=err.lineno, column=err.colno) from None
    return validate_local_config(raw)


def ensure_output_dir(cfg: dict[str, Any]) -> Path:
    out: Path = cfg["_out"]
    out.mkdir(parents=True, exist_ok=True)
    try:
        out.chmod(0o700)
    except OSError:
        pass
    return out


def settings_fingerprint(cfg: dict[str, Any]) -> str:
    relevant = {k: cfg.get(k) for k in ("processing", "text", "visual")}
    return short_hash(json.dumps(relevant, sort_keys=True, ensure_ascii=False), 12)
