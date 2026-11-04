"""before/after pair candidates per category, from file names only.

Rules:
- Never across categories (세트 <-> 단품): candidates are built inside one
  category's file list only, and approve/compare re-check folder membership.
- Version/date/final words may be stripped for a *candidate key*, but codes,
  numbers and volumes are never stripped, and conflicts in volume, codes,
  language/country or packaging words block a candidate.
- Nothing is confirmed automatically. Unique candidates are
  CANDIDATE_UNCONFIRMED; anything ambiguous is PAIR_NEEDS_CONFIRMATION.
- mtime and "latest file" are never used to choose.
"""
from __future__ import annotations

import difflib
import re
from pathlib import PurePosixPath
from typing import Any

from .common import nfc, short_hash

VOLUME_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|g|kg|l|oz|매입|매|ea|개입|개|pcs|p)(?![a-z])")
DATE_RES = [
    re.compile(r"(?<!\d)20\d{2}[.\-_]?(?:0[1-9]|1[0-2])[.\-_]?(?:0[1-9]|[12]\d|3[01])(?!\d)"),
    re.compile(r"(?<!\d)\d{2}[.\-](?:0[1-9]|1[0-2])[.\-](?:0[1-9]|[12]\d|3[01])(?!\d)"),
]
VERSION_TOKEN = re.compile(
    r"^(v\d+(?:\.\d+)?|ver\.?\d*|rev\.?\d*|r\d{1,2}|\d+차|수정\d*차?|수정본|최최종|최종\d*|final\d*|fin|컨펌|confirm(?:ed)?|"
    r"before|after|수정전|수정후|copy|복사본|사본|old|new|확정)$"
)
LANG_TOKENS = {"kr", "ko", "kor", "en", "eng", "us", "usa", "cn", "chn", "zh", "jp", "jpn", "ja", "eu", "uk", "global", "gl",
               "국문", "영문", "중문", "일문", "수출", "내수", "면세", "dfs", "tw", "hk", "vn", "th", "sg", "my", "id"}
PACK_TOKENS = {"단상자", "케이스", "case", "carton", "라벨", "label", "튜브", "tube", "용기", "bottle", "병", "파우치", "pouch",
               "쇼핑백", "리필", "refill", "기획", "증정", "샘플", "sample", "틴", "tin", "캡", "cap", "스티커", "sticker",
               "띠지", "슬리브", "sleeve", "트레이", "tray", "패키지", "pkg", "본품", "미니", "mini"}
SPLIT_RE = re.compile(r"[\s_\-.()\[\]{}+,&/]+")


def name_features(group_relative_path: str) -> dict[str, Any]:
    p = PurePosixPath(nfc(group_relative_path))
    stem = p.stem.casefold()
    volumes = sorted({m.group(1).replace(",", ".") + m.group(2) for m in VOLUME_RE.finditer(stem)})
    work = VOLUME_RE.sub(lambda m: " " + m.group(1).replace(",", ".") + m.group(2) + " ", stem)
    stripped: list[str] = []
    for rx in DATE_RES:
        stripped += rx.findall(work)
        work = rx.sub(" ", work)
    toks = [t for t in SPLIT_RE.split(work) if t]
    kept = []
    for t in toks:
        if VERSION_TOKEN.match(t):
            stripped.append(t)
        else:
            kept.append(t)
    codes = sorted({t for t in kept if (re.search(r"\d", t) and re.search(r"[a-z가-힣]", t) and t not in volumes)
                    or (t.isdigit() and len(t) >= 3)})
    critical = set(volumes) | set(codes) | LANG_TOKENS | PACK_TOKENS
    return {
        "parent": str(p.parent) if str(p.parent) != "." else "",
        "core_key": " ".join(t for t in kept if t not in critical),
        "base_key": " ".join(kept),
        "volumes": volumes,
        "codes": codes,
        "langs": sorted(t for t in kept if t in LANG_TOKENS),
        "packs": sorted(t for t in kept if t in PACK_TOKENS),
        "stripped_tokens": stripped,
    }


def conflicts(fa: dict[str, Any], fb: dict[str, Any]) -> list[str]:
    out = []
    for key, code in (("volumes", "VOLUME_DIFFERS"), ("codes", "CODE_OR_NUMBER_DIFFERS"),
                      ("langs", "LANGUAGE_OR_COUNTRY_DIFFERS"), ("packs", "PACKAGING_TYPE_DIFFERS")):
        if fa[key] != fb[key]:
            out.append(code)
    return out


def pair_id_for(code: str, before_rel: str, after_rel: str) -> str:
    return f"{code}_{short_hash(code + chr(0) + nfc(before_rel) + chr(0) + nfc(after_rel), 10)}"


def build_candidates(files: list[dict[str, Any]], groups: list[dict[str, Any]], weak_threshold: float) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for group in groups:
        code = group["code"]
        befores = [f for f in files if f["category_code"] == code and f["side"] == "before"]
        afters = [f for f in files if f["category_code"] == code and f["side"] == "after"]
        feat = {f["file_id"]: name_features(f["group_relative_path"]) for f in befores + afters}
        links: dict[str, list[tuple[str, str]]] = {b["file_id"]: [] for b in befores}
        rev: dict[str, list[tuple[str, str]]] = {a["file_id"]: [] for a in afters}
        for b in befores:
            fb = feat[b["file_id"]]
            for a in afters:
                fa = feat[a["file_id"]]
                if nfc(b["group_relative_path"]) == nfc(a["group_relative_path"]):
                    basis = "EXACT_GROUP_RELATIVE_PATH"
                elif fb["base_key"] and fb["base_key"] == fa["base_key"] and fb["parent"] == fa["parent"]:
                    basis = "SAME_NAME_AFTER_VERSION_DATE_WORDS_REMOVED"
                else:
                    # similarity of the name without codes/volumes/language/packaging words;
                    # those words are then compared strictly and block the candidate if they differ
                    ratio = difflib.SequenceMatcher(a=fb["core_key"], b=fa["core_key"], autojunk=False).ratio()
                    if ratio < weak_threshold:
                        continue
                    reasons = conflicts(fb, fa)
                    if reasons:
                        blocked.append({"category_code": code, "before_file_id": b["file_id"], "after_file_id": a["file_id"],
                                        "name_similarity": round(ratio, 3), "blocked_reasons": reasons})
                        continue
                    basis = "WEAK_NAME_SIMILARITY"
                links[b["file_id"]].append((a["file_id"], basis))
                rev[a["file_id"]].append((b["file_id"], basis))
        by_id = {f["file_id"]: f for f in befores + afters}
        handled_after: set[str] = set()
        for b in befores:
            opts = links[b["file_id"]]
            if len(opts) == 1 and opts[0][1] != "WEAK_NAME_SIMILARITY" and len(rev[opts[0][0]]) == 1:
                a = by_id[opts[0][0]]
                handled_after.add(a["file_id"])
                candidates.append({
                    "pair_id": pair_id_for(code, b["root_relative_path"], a["root_relative_path"]),
                    "category": group["category"], "category_code": code,
                    "artwork_id": None,
                    "before_relative_path": b["root_relative_path"],
                    "after_relative_path": a["root_relative_path"],
                    "matching_basis": opts[0][1],
                    "stripped_words_for_candidate_only": sorted(set(feat[b["file_id"]]["stripped_tokens"] + feat[a["file_id"]]["stripped_tokens"])),
                    "before_file_state": b["file_state"], "after_file_state": a["file_state"],
                    "status": "CANDIDATE_UNCONFIRMED",
                    "approved_for_comparison": False,
                })
            else:
                reason = "MISSING_AFTER_COUNTERPART" if not opts else (
                    "WEAK_NAME_SIMILARITY_ONLY" if all(o[1] == "WEAK_NAME_SIMILARITY" for o in opts) and len(opts) == 1
                    and len(rev[opts[0][0]]) == 1 else "MULTIPLE_CANDIDATES")
                for a_id, _ in opts:
                    handled_after.add(a_id)
                issues.append({
                    "issue_id": f"ISSUE_{code}_{short_hash(b['file_id'], 8)}",
                    "status": "PAIR_NEEDS_CONFIRMATION", "reason": reason, "category_code": code,
                    "before_relative_path": b["root_relative_path"],
                    "after_candidates": [{"after_relative_path": by_id[a_id]["root_relative_path"], "basis": basis}
                                         for a_id, basis in opts],
                })
        for a in afters:
            if a["file_id"] not in handled_after and not rev[a["file_id"]]:
                issues.append({
                    "issue_id": f"ISSUE_{code}_{short_hash(a['file_id'], 8)}",
                    "status": "PAIR_NEEDS_CONFIRMATION", "reason": "MISSING_BEFORE_COUNTERPART", "category_code": code,
                    "after_relative_path": a["root_relative_path"], "after_candidates": [],
                })
    return {"candidates": candidates, "issues": issues, "blocked_similar_names": blocked}
