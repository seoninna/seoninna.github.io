"""Folder layout resolution and file listing (metadata only, no PDF content).

Supported layouts (folder names configurable):
  A) ROOT/<category>/<before|after>
  B) ROOT/<before|after>/<category>
  C) explicit before_dir/after_dir per category (relative to ROOT)
Sub-folders below each of the four group directories are scanned.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .common import FinalError, inside, matches_ignore, nfc, norm_name, short_hash


def _child_dirs(path: Path) -> list[Path]:
    try:
        return [p for p in path.iterdir() if p.is_dir() and not p.is_symlink()]
    except OSError:
        raise FinalError("SOURCE_DIRECTORY_NOT_READABLE") from None


def _check_no_symlink_components(root: Path, candidate: Path) -> None:
    current = root
    for segment in candidate.relative_to(root).parts:
        current = current / segment
        if current.is_symlink():
            raise FinalError("SOURCE_SYMLINK_NOT_ALLOWED")


def resolve_group_dir(cfg: dict[str, Any], group: dict[str, Any], side: str) -> Path:
    root: Path = cfg["_root"]
    explicit = str(group.get(f"{side}_dir") or "").strip()
    if explicit:
        value = Path(explicit).expanduser()
        candidate = value if value.is_absolute() else root / value
        if not candidate.exists():
            raise FinalError("CONFIGURED_GROUP_DIRECTORY_NOT_FOUND", category_code=group["code"], side=side)
        absolute = Path(os.path.abspath(candidate))
        if not inside(absolute, root):
            raise FinalError("SOURCE_DIRECTORY_OUTSIDE_ROOT", category_code=group["code"], side=side)
        _check_no_symlink_components(root, absolute)
        resolved = absolute.resolve(strict=True)
        if not resolved.is_dir() or not inside(resolved, root):
            raise FinalError("SOURCE_DIRECTORY_OUTSIDE_ROOT", category_code=group["code"], side=side)
        return resolved
    side_names = {norm_name(x) for x in cfg["folder_names"][side]}
    cat_names = {norm_name(x) for x in (group.get("folder_names") or [group["category"]])}
    matches: set[Path] = set()
    for first in _child_dirs(root):
        first_name = norm_name(first.name)
        if first_name in cat_names:
            for second in _child_dirs(first):
                if norm_name(second.name) in side_names:
                    matches.add(second.resolve())
        if first_name in side_names:
            for second in _child_dirs(first):
                if norm_name(second.name) in cat_names:
                    matches.add(second.resolve())
    if not matches:
        raise FinalError("GROUP_DIRECTORY_NOT_FOUND_SET_BEFORE_DIR_AFTER_DIR", category_code=group["code"], side=side)
    if len(matches) > 1:
        raise FinalError("GROUP_DIRECTORY_AMBIGUOUS_SET_BEFORE_DIR_AFTER_DIR", category_code=group["code"], side=side)
    return next(iter(matches))


def resolve_all_groups(cfg: dict[str, Any]) -> dict[str, dict[str, Path]]:
    """Return {category_code: {"before": Path, "after": Path}} with overlap checks."""
    resolved: dict[str, dict[str, Path]] = {}
    seen: list[Path] = []
    for group in cfg["groups"]:
        entry: dict[str, Path] = {}
        for side in ("before", "after"):
            folder = resolve_group_dir(cfg, group, side)
            for previous in seen:
                if inside(folder, previous) or inside(previous, folder):
                    raise FinalError("SOURCE_GROUP_DIRECTORIES_OVERLAP", category_code=group["code"], side=side)
            seen.append(folder)
            entry[side] = folder
        resolved[group["code"]] = entry
    return resolved


def file_id_for(category_code: str, side: str, root_relative: str) -> str:
    return short_hash(f"{category_code}\0{side}\0{nfc(root_relative)}", 16)


def scan_group(cfg: dict[str, Any], group: dict[str, Any], side: str, folder: Path,
               now: float | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    root: Path = cfg["_root"]
    rules = cfg["file_rules"]
    patterns = list(rules.get("ignore_patterns") or [])
    stable_seconds = float(rules.get("stable_seconds", 120))
    now = time.time() if now is None else now
    records: list[dict[str, Any]] = []
    skipped = {"symlinks": 0, "non_pdf_files": 0, "unreadable": 0, "temporary_or_hidden": 0}

    def onerror(_err: OSError) -> None:
        skipped["unreadable"] += 1

    for current, dirs, files in os.walk(folder, followlinks=False, onerror=onerror):
        base = Path(current)
        kept = []
        for name in sorted(dirs):
            if (base / name).is_symlink():
                skipped["symlinks"] += 1
            elif matches_ignore(name, patterns):
                skipped["temporary_or_hidden"] += 1
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            path = base / name
            if path.is_symlink():
                skipped["symlinks"] += 1
                continue
            if matches_ignore(name, patterns):
                skipped["temporary_or_hidden"] += 1
                continue
            if path.suffix.lower() != ".pdf":
                skipped["non_pdf_files"] += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                skipped["unreadable"] += 1
                continue
            root_rel = nfc(path.relative_to(root).as_posix())
            group_rel = nfc(path.relative_to(folder).as_posix())
            age = now - stat.st_mtime
            if stat.st_size == 0:
                state = "ZERO_LENGTH"
            elif age < stable_seconds:
                state = "NOT_STABLE_RECENTLY_MODIFIED"
            else:
                state = "STABLE"
            records.append({
                "file_id": file_id_for(group["code"], side, root_rel),
                "category": group["category"],
                "category_code": group["code"],
                "side": side,
                "root_relative_path": root_rel,
                "group_relative_path": group_rel,
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
                "file_state": state,
            })
    return records, skipped


def scan_all(cfg: dict[str, Any], now: float | None = None) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, dict[str, Path]]]:
    groups_dirs = resolve_all_groups(cfg)
    files: list[dict[str, Any]] = []
    skipped_total = {"symlinks": 0, "non_pdf_files": 0, "unreadable": 0, "temporary_or_hidden": 0}
    for group in cfg["groups"]:
        for side in ("before", "after"):
            recs, skipped = scan_group(cfg, group, side, groups_dirs[group["code"]][side], now)
            files.extend(recs)
            for key, value in skipped.items():
                skipped_total[key] += value
    return files, skipped_total, groups_dirs


def safe_source_path(cfg: dict[str, Any], groups_dirs: dict[str, dict[str, Path]],
                     category_code: str, side: str, root_relative: str) -> Path:
    """Resolve a manifest path and prove it lives in the right category/side folder."""
    root: Path = cfg["_root"]
    if category_code not in groups_dirs:
        raise FinalError("UNKNOWN_CATEGORY_CODE")
    rel = Path(root_relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise FinalError("MANIFEST_PATH_MUST_BE_ROOT_RELATIVE")
    candidate = root / rel
    if not candidate.exists():
        raise FinalError("SOURCE_FILE_MISSING", side=side)
    _check_no_symlink_components(root, Path(os.path.abspath(candidate)))
    resolved = candidate.resolve(strict=True)
    if not inside(resolved, groups_dirs[category_code][side]):
        # Blocks set<->single cross matching and before/after swaps.
        raise FinalError("SOURCE_FILE_NOT_IN_EXPECTED_CATEGORY_SIDE_FOLDER", side=side)
    if resolved.suffix.lower() != ".pdf":
        raise FinalError("SOURCE_FILE_NOT_PDF", side=side)
    return resolved


def file_state(cfg: dict[str, Any], path: Path, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if matches_ignore(path.name, list(cfg["file_rules"].get("ignore_patterns") or [])):
        return "TEMPORARY_OR_HIDDEN"
    stat = path.stat()
    if stat.st_size == 0:
        return "ZERO_LENGTH"
    if now - stat.st_mtime < float(cfg["file_rules"].get("stable_seconds", 120)):
        return "NOT_STABLE_RECENTLY_MODIFIED"
    if stat.st_size > float(cfg["file_rules"].get("max_file_size_mb", 4096)) * 1024 * 1024:
        return "OVER_MAX_FILE_SIZE"
    return "STABLE"
