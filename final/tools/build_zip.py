#!/usr/bin/env python3
"""Build dist/FINAL_Ready_To_Setup.zip with code, synthetic-fixture generator,
templates and docs only. Refuses to include PDFs, images, real configs,
private outputs, keys, or files that look like they contain local paths/tokens."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
ZIP = DIST / "FINAL_Ready_To_Setup.zip"
ALLOWED_SUFFIX = {".py", ".md", ".json", ".txt", ".csv", ""}
ALLOWED_NAMES = {"Dockerfile", ".gitignore"}
EXCLUDE_DIRS = {"__pycache__", "dist", "demo", ".venv", "venv", ".git", "private_output", "real_artwork"}
EXCLUDE_NAMES = {"config.local.json", "config.b.json", "pair_manifest.local.json", "ledger.json"}
SUSPICIOUS = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"), re.compile(r"[A-Za-z]:[\\/]+Users[\\/]"), re.compile(r"/home/[a-z0-9_-]+/(?!user/seoninna)"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"), re.compile(r"AIza[0-9A-Za-z_-]{30,}"), re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def wanted(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    if p.name in EXCLUDE_NAMES or ".private." in p.name or p.name.endswith((".pyc", ".log", ".tmp")):
        return False
    return p.suffix.lower() in ALLOWED_SUFFIX and (p.suffix or p.name in ALLOWED_NAMES)


def main() -> int:
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and wanted(p))
    problems = []
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for rx in SUSPICIOUS:
            if rx.search(text) and p.name != "build_zip.py":
                problems.append({"file": p.relative_to(ROOT).as_posix(), "pattern": rx.pattern})
    if problems:
        print(json.dumps({"ok": False, "error_code": "SUSPICIOUS_CONTENT", "problems": problems}, ensure_ascii=False))
        return 2
    DIST.mkdir(exist_ok=True)
    manifest = {"package": "FINAL_Ready_To_Setup", "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "contains_company_artwork": False, "contains_pdf_or_images": False,
                "contains_real_paths_or_keys": "checked by pattern scan (not a guarantee)", "files": []}
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            data = p.read_bytes()
            arc = "final/" + p.relative_to(ROOT).as_posix()
            z.writestr(arc, data)
            manifest["files"].append({"path": arc, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        z.writestr("final/ZIP_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({"ok": True, "zip": str(ZIP.relative_to(ROOT)), "files": len(files) + 1,
                      "bytes": ZIP.stat().st_size}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
