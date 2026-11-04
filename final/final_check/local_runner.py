"""LOCAL_ONLY orchestration: manifest lookup, hashing, dedupe, ledger, delivery
records. Used by compare_engine.py (CLI) and local_api.py (n8n bridge)."""
from __future__ import annotations

import os
import re
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import engine, layout, report, requests_eval
from .common import (ENGINE_VERSION, FinalError, atomic_write_json, ensure_output_dir, now_iso, read_json,
                     settings_fingerprint, sha256_file, short_hash)

PAIR_ID_RE = re.compile(r"^[A-Z0-9]{2,12}_[0-9a-f]{10}$")
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
RUN_KEY_RE = re.compile(r"^[0-9a-f]{16}$")
MAX_RUN_ATTEMPTS = 3
RETRY_EXEMPT_REASONS = {"PAGE_MAP_REQUIRED_PAGE_COUNT_CHANGED", "PAGE_MAP_REQUIRED_SIZE_OR_ROTATION_CHANGED",
                        "NOT_IN_PAGE_MAP", "NO_COUNTERPART_PER_PAGE_MAP", "UNPROCESSED_PAGE_LIMIT"}
DELIVERY_STATES = {"SENT_ACCEPTED_BY_PROVIDER", "SEND_FAILED", "LOCAL_ONLY_NOT_SENT", "RECEIPT_CONFIRMED_BY_USER"}


# ------------------------------------------------------------------ manifest
def empty_manifest() -> dict[str, Any]:
    return {"schema_version": "3.0", "classification": "LOCAL_PRIVATE_DO_NOT_UPLOAD", "pairs": []}


def load_manifest(cfg: dict[str, Any]) -> dict[str, Any]:
    try:
        data = read_json(cfg["_manifest"], None)
    except Exception:
        raise FinalError("MANIFEST_JSON_SYNTAX_ERROR") from None
    if data is None:
        return empty_manifest()
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), list):
        raise FinalError("MANIFEST_INVALID_STRUCTURE")
    return data


def save_manifest(cfg: dict[str, Any], data: dict[str, Any]) -> None:
    ensure_output_dir(cfg)
    atomic_write_json(cfg["_manifest"], data)


def get_pair(manifest: dict[str, Any], pair_id: str) -> dict[str, Any]:
    if not PAIR_ID_RE.match(pair_id or ""):
        raise FinalError("PAIR_ID_FORMAT_INVALID")
    for p in manifest["pairs"]:
        if p.get("pair_id") == pair_id:
            return p
    raise FinalError("PAIR_ID_NOT_IN_MANIFEST")


# ------------------------------------------------------------------ state
def _state_dir(cfg: dict[str, Any]) -> Path:
    d = ensure_output_dir(cfg) / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


@contextmanager
def state_lock(cfg: dict[str, Any], wait_seconds: float = 30) -> Iterator[None]:
    lock = _state_dir(cfg) / ".lock"
    deadline = time.time() + wait_seconds
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 6 * 3600:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                raise FinalError("ANOTHER_RUN_IN_PROGRESS_TRY_LATER") from None
            time.sleep(0.5)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def load_ledger(cfg: dict[str, Any]) -> dict[str, Any]:
    return read_json(_state_dir(cfg) / "ledger.json", None) or {"runs": {}, "events": {}}


def save_ledger(cfg: dict[str, Any], ledger: dict[str, Any]) -> None:
    atomic_write_json(_state_dir(cfg) / "ledger.json", ledger)


def cached_hash(cfg: dict[str, Any], path: Path) -> str:
    cache_path = _state_dir(cfg) / "hash_cache.private.json"
    cache = read_json(cache_path, None) or {}
    st = path.stat()
    key = short_hash(str(path), 16)
    hit = cache.get(key)
    if hit and hit["size"] == st.st_size and hit["mtime_ns"] == st.st_mtime_ns:
        return hit["sha256"]
    digest = sha256_file(path)
    cache[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}
    atomic_write_json(cache_path, cache)
    return digest


# ------------------------------------------------------------------ helpers
def resolve_pair_paths(cfg: dict[str, Any], pair: dict[str, Any]) -> tuple[Path, Path]:
    groups_dirs = layout.resolve_all_groups(cfg)
    code = pair.get("category_code")
    if not any(g["code"] == code and g["category"] == pair.get("category") for g in cfg["groups"]):
        raise FinalError("PAIR_CATEGORY_NOT_IN_CONFIG")
    b = layout.safe_source_path(cfg, groups_dirs, code, "before", pair["before_relative_path"])
    a = layout.safe_source_path(cfg, groups_dirs, code, "after", pair["after_relative_path"])
    if b == a:
        raise FinalError("BEFORE_AND_AFTER_ARE_THE_SAME_FILE")
    return b, a


def run_key_for(cfg: dict[str, Any], pair_id: str, bh: str, ah: str) -> str:
    return short_hash(f"{pair_id}|{bh}|{ah}|{ENGINE_VERSION}|{settings_fingerprint(cfg)}", 16)


def requests_path(cfg: dict[str, Any], pair: dict[str, Any]) -> Path:
    name = pair.get("requests_file") or f"{pair['pair_id']}.json"
    p = (cfg["_requests_dir"] / name).resolve()
    if p.parent != cfg["_requests_dir"].resolve():
        raise FinalError("REQUESTS_FILE_MUST_BE_IN_REQUESTS_DIR")
    return p


# ------------------------------------------------------------------ main ops
def run_pair(cfg: dict[str, Any], pair_id: str, event_id: str | None = None, force: bool = False,
             max_pages: int | None = None) -> dict[str, Any]:
    if event_id is not None and not EVENT_ID_RE.match(event_id):
        raise FinalError("EVENT_ID_FORMAT_INVALID")
    manifest = load_manifest(cfg)
    pair = get_pair(manifest, pair_id)
    if pair.get("approved_for_comparison") is not True or not pair.get("approved_at"):
        raise FinalError("PAIR_NOT_APPROVED_RUN_PAIR_RESOLVER_APPROVE")
    before_path, after_path = resolve_pair_paths(cfg, pair)
    for side, path in (("before", before_path), ("after", after_path)):
        state = layout.file_state(cfg, path)
        if state != "STABLE":
            return {"ok": False, "error_code": f"{side.upper()}_FILE_{state}", "pair_id": pair_id, "retry_later": True}
    with state_lock(cfg):
        bh = cached_hash(cfg, before_path)
        ah = cached_hash(cfg, after_path)
        if pair.get("before_content_sha256") and bh != pair["before_content_sha256"]:
            raise FinalError("BASELINE_CONTENT_CHANGED_SINCE_APPROVAL_REAPPROVE_PAIR")
        if bh == ah:
            return {"ok": False, "error_code": "BEFORE_AND_AFTER_CONTENT_IDENTICAL_NO_REVISION", "pair_id": pair_id}
        run_key = run_key_for(cfg, pair_id, bh, ah)
        ledger = load_ledger(cfg)
        if event_id and event_id in ledger["events"]:
            prev = ledger["events"][event_id]
            return {"ok": True, "status": "DUPLICATE_EVENT_IGNORED", "pair_id": pair_id, "run_key": prev}
        prev_run = ledger["runs"].get(run_key)
        out = ensure_output_dir(cfg)
        report_dir = out / "reports" / pair_id / run_key
        retry_failed = bool(prev_run and prev_run.get("compare_status") == "COMPARED" and prev_run.get("failed_pages")
                            and int(prev_run.get("run_attempts", 1)) < MAX_RUN_ATTEMPTS)
        if prev_run and prev_run.get("compare_status") == "COMPARED" and not force and not retry_failed:
            if event_id:
                ledger["events"][event_id] = run_key
                save_ledger(cfg, ledger)
            summ = read_json(report_dir / "summary.safe.json", {}) or {}
            return {"ok": True, "status": "ALREADY_PROCESSED_SAME_CONTENT", "pair_id": pair_id, "run_key": run_key,
                    "delivery_status": prev_run.get("delivery", {}).get("status"), "summary": summ}
        job_dir = out / "jobs" / pair_id / run_key
        if force and job_dir.exists():
            shutil.rmtree(job_dir)
        attempts = int(prev_run.get("run_attempts", 0)) + 1 if prev_run and not force else 1
        ledger["runs"][run_key] = {"pair_id": pair_id, "before_sha256": bh, "after_sha256": ah,
                                   "compare_status": "RUNNING", "started_at": now_iso(), "run_attempts": attempts,
                                   "delivery": {"status": "NOT_SENT"}}
        if event_id:
            ledger["events"][event_id] = run_key
        save_ledger(cfg, ledger)
    req_data = requests_eval.load_requests(requests_path(cfg, pair))
    try:
        rep = engine.compare_files(before_path=before_path, after_path=after_path, before_hash=bh, after_hash=ah,
                                   pair=pair, requests_data=req_data, cfg=cfg, job_dir=job_dir, report_dir=report_dir,
                                   cache_dir=out / "cache", max_pages=max_pages)
    except FinalError as err:
        with state_lock(cfg):
            ledger = load_ledger(cfg)
            ledger["runs"][run_key].update(compare_status="FAILED", error_code=err.code, finished_at=now_iso())
            save_ledger(cfg, ledger)
        raise
    rep["approval_snapshot"] = {
        "after_differs_from_approval_snapshot": bool(pair.get("after_content_sha256_at_approval")) and
        pair.get("after_content_sha256_at_approval") != ah,
        "approved_at": pair.get("approved_at"),
    }
    summ = report.write_reports(rep, report_dir, run_key, make_pdf=bool(cfg["processing"].get("pdf_report", True)))
    with state_lock(cfg):
        ledger = load_ledger(cfg)
        failed = sum(1 for u in rep["coverage"]["unprocessed"]
                     if u["reason"] not in RETRY_EXEMPT_REASONS)
        ledger["runs"][run_key].update(compare_status="COMPARED", finished_at=now_iso(),
                                       overall_status=rep["overall_status"], failed_pages=failed)
        save_ledger(cfg, ledger)
    subject, text, html_body = report.safe_notification(summ)
    return {"ok": True, "status": "COMPARED", "pair_id": pair_id, "run_key": run_key, "summary": summ,
            "delivery_status": "NOT_SENT",
            "safe_email_enabled": bool(cfg["notification"].get("safe_email_enabled")),
            "safe_notification": {"subject": subject, "text": text, "html": html_body}}


def find_pending(cfg: dict[str, Any]) -> dict[str, Any]:
    manifest = load_manifest(cfg)
    ledger = load_ledger(cfg)
    pending, waiting, errors, done = [], 0, {}, 0
    for pair in manifest["pairs"]:
        if pair.get("approved_for_comparison") is not True:
            continue
        try:
            b, a = resolve_pair_paths(cfg, pair)
            if layout.file_state(cfg, a) != "STABLE" or layout.file_state(cfg, b) != "STABLE":
                waiting += 1
                continue
            bh, ah = cached_hash(cfg, b), cached_hash(cfg, a)
            if bh == ah:
                done += 1
                continue
            rk = run_key_for(cfg, pair["pair_id"], bh, ah)
            run = ledger["runs"].get(rk)
            if run and run.get("compare_status") == "COMPARED" and not (
                    run.get("failed_pages") and int(run.get("run_attempts", 1)) < MAX_RUN_ATTEMPTS):
                done += 1
                continue
            pending.append({"pair_id": pair["pair_id"], "run_key": rk, "event_id": f"file-{rk}"})
        except FinalError as err:
            errors[err.code] = errors.get(err.code, 0) + 1
    return {"ok": True, "pending": pending, "waiting_not_stable": waiting, "already_compared": done, "errors": errors}


def record_delivery(cfg: dict[str, Any], run_key: str, status: str, message_id: str | None = None) -> dict[str, Any]:
    if not RUN_KEY_RE.match(run_key or ""):
        raise FinalError("RUN_KEY_FORMAT_INVALID")
    if status not in DELIVERY_STATES:
        raise FinalError("DELIVERY_STATUS_INVALID")
    if message_id is not None and not EVENT_ID_RE.match(message_id):
        raise FinalError("MESSAGE_ID_FORMAT_INVALID")
    with state_lock(cfg):
        ledger = load_ledger(cfg)
        run = ledger["runs"].get(run_key)
        if not run:
            raise FinalError("RUN_KEY_NOT_FOUND")
        if run.get("compare_status") != "COMPARED":
            raise FinalError("CANNOT_RECORD_DELIVERY_BEFORE_COMPARE_SUCCESS")
        run["delivery"] = {"status": status, "message_id": message_id, "recorded_at": now_iso()}
        run["done"] = status in ("SENT_ACCEPTED_BY_PROVIDER", "RECEIPT_CONFIRMED_BY_USER")
        save_ledger(cfg, ledger)
    return {"ok": True, "run_key": run_key, "delivery_status": status, "done": run["done"]}
