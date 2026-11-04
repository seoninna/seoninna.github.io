"""FINAL? synthetic regression tests.

All PDFs are generated synthetic fixtures (tests/synthetic.py). Expected results
are asserted from what the engine extracted/rendered from those PDFs; file names
never carry the expected answer (see test_file_names_do_not_drive_results).

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from synthetic import LOGO, base_page, build_pdf, with_text  # noqa: E402

from final_check import layout, pairing  # noqa: E402
from final_check.common import FinalError, install_network_guard, validate_local_config  # noqa: E402
from final_check.local_runner import find_pending, load_manifest, record_delivery, run_pair, save_manifest  # noqa: E402

OLD = time.time() - 3600
FORBIDDEN_WITHOUT_REQUESTS = ["누락", "반영 완료", "오수정", "요청대로", "REFLECTED", "NOT_REFLECTED"]


def tree_fingerprint(root: Path) -> dict[str, tuple[str, int, float]]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[p.relative_to(root).as_posix()] = (hashlib.sha256(p.read_bytes()).hexdigest(), st.st_size, st.st_mtime)
    return out


class Base(unittest.TestCase):
    layout_kind = "A"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "원화 폴더 (테스트)"
        self.out = self.base / "검수 결과"
        for cat in ("세트", "단품"):
            for side in ("before", "after"):
                self.dir(cat, side).mkdir(parents=True, exist_ok=True)
        os.environ.pop("FINAL_TEST_FAULT", None)
        os.environ.pop("FINAL_TEST_FAULT_MODE", None)

    def tearDown(self) -> None:
        os.environ.pop("FINAL_TEST_FAULT", None)
        os.environ.pop("FINAL_TEST_FAULT_MODE", None)
        self.tmp.cleanup()

    def dir(self, cat: str, side: str) -> Path:
        return self.root / cat / side if self.layout_kind == "A" else self.root / side / cat

    def pdf(self, cat: str, side: str, name: str, pages, **kw) -> Path:
        p = build_pdf(self.dir(cat, side) / name, pages, **kw)
        os.utime(p, (OLD, OLD))
        return p

    def cfg(self, **over):
        raw = {"privacy_mode": "LOCAL_ONLY", "root_dir": str(self.root), "output_dir": str(self.out),
               "processing": {"page_isolation": "inline", "pdf_report": False}}
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(raw.get(k), dict):
                raw[k] = {**raw[k], **v}
            else:
                raw[k] = v
        return validate_local_config(raw)

    def approve_all(self, cfg):
        from pair_resolver import cmd_approve, cmd_scan

        cmd_scan(cfg)
        m = load_manifest(cfg)
        for p in m["pairs"]:
            cmd_approve(cfg, type("A", (), {"pair_id": p["pair_id"], "artwork_id": "T", "by": "tester", "note": None})())
        return {p["category_code"]: p["pair_id"] for p in load_manifest(cfg)["pairs"]}

    def report(self, cfg, res):
        d = cfg["_out"] / "reports" / res["pair_id"] / res["run_key"]
        rep = json.loads((d / "report.private.json").read_text(encoding="utf-8"))
        return rep, d

    def items(self, rep, kind=None):
        out = [i for p in rep["pages"] for i in (p.get("text") or {}).get("items", [])]
        return [i for i in out if kind is None or i["kind"] == kind]

    def regions(self, rep, kind=None):
        out = [r for p in rep["pages"] for r in (p.get("visual") or {}).get("regions", [])]
        return [r for r in out if kind is None or r["kind"] == kind]

    def one_pair(self, before_pages, after_pages, cat="세트", name="가상 원화.pdf", **kw):
        self.pdf(cat, "before", name, before_pages, **kw.get("bkw", {}))
        self.pdf(cat, "after", name, after_pages, **kw.get("akw", {}))
        cfg = self.cfg(**kw.get("cfg", {}))
        ids = self.approve_all(cfg)
        return cfg, ids["SET" if cat == "세트" else "SINGLE"]


# --------------------------------------------------------------------------- layout & pairing
class LayoutAndPairing(Base):
    def test_layout_a_and_b_supported(self):
        for kind in ("A", "B"):
            with self.subTest(layout=kind):
                self.tearDown()
                self.layout_kind = kind
                self.setUp()
                self.pdf("세트", "before", "x.pdf", [base_page()])
                self.pdf("세트", "after", "x.pdf", [base_page()])
                self.pdf("단품", "before", "x.pdf", [base_page()])
                self.pdf("단품", "after", "x.pdf", [base_page()])
                files, _, _ = layout.scan_all(self.cfg())
                self.assertEqual(len(files), 4)

    def test_custom_folder_names(self):
        for cat in ("세트", "단품"):
            (self.root / cat / "원화 수정 전 before").mkdir(parents=True)
            (self.root / cat / "원화 수정 후 after").mkdir(parents=True)
        for cat in ("세트", "단품"):
            for side in ("before", "after"):
                (self.root / cat / side).rmdir()
        build_pdf(self.root / "세트" / "원화 수정 전 before" / "a.pdf", [base_page()])
        cfg = self.cfg(groups=[
            {"category": "세트", "code": "SET", "before_dir": "세트/원화 수정 전 before", "after_dir": "세트/원화 수정 후 after"},
            {"category": "단품", "code": "SINGLE", "before_dir": "단품/원화 수정 전 before", "after_dir": "단품/원화 수정 후 after"}])
        files, _, _ = layout.scan_all(cfg)
        self.assertEqual(len(files), 1)
        # automatic detection also knows the default Korean names
        files2, _, _ = layout.scan_all(self.cfg())
        self.assertEqual(len(files2), 1)

    def test_ambiguous_layout_refused(self):
        (self.root / "before" / "세트").mkdir(parents=True)
        with self.assertRaises(FinalError) as cm:
            layout.scan_all(self.cfg())
        self.assertIn("AMBIGUOUS", cm.exception.code)

    def test_set_and_single_never_cross_matched(self):
        for cat in ("세트", "단품"):
            self.pdf(cat, "before", "동일 제품명.pdf", [base_page()])
            self.pdf(cat, "after", "동일 제품명.pdf", [base_page()])
        cfg = self.cfg()
        files, _, _ = layout.scan_all(cfg)
        res = pairing.build_candidates(files, cfg["groups"], 0.75)
        self.assertEqual(len(res["candidates"]), 2)
        for c in res["candidates"]:
            self.assertTrue(c["before_relative_path"].startswith(c["category"]) or "/" + c["category"] in c["before_relative_path"])
            self.assertEqual(c["before_relative_path"].split("/")[0], c["after_relative_path"].split("/")[0])
        # manual attempt to pair 세트 before with 단품 after is refused
        from pair_resolver import cmd_add

        args = type("A", (), {"category_code": "SET", "before": "세트/before/동일 제품명.pdf",
                              "after": "단품/after/동일 제품명.pdf"})()
        with self.assertRaises(FinalError) as cm:
            cmd_add(cfg, args)
        self.assertEqual(cm.exception.code, "SOURCE_FILE_NOT_IN_EXPECTED_CATEGORY_SIDE_FOLDER")
        # tampering the manifest is also refused at compare time
        ids = self.approve_all(cfg)
        m = load_manifest(cfg)
        for p in m["pairs"]:
            if p["pair_id"] == ids["SET"]:
                p["after_relative_path"] = "단품/after/동일 제품명.pdf"
        save_manifest(cfg, m)
        with self.assertRaises(FinalError):
            run_pair(cfg, ids["SET"])

    def test_name_rules(self):
        names_b = ["크림 GX-120 50ml_v1.pdf", "크림 GX-120 50ml 20251101.pdf", "토너 KR.pdf", "세럼 AB12.pdf",
                   "로션 단상자.pdf", "앰플.pdf", "미스트 v1.pdf"]
        names_a = ["크림 GX-120 100ml_v2.pdf", "토너 EN.pdf", "세럼 AB13.pdf", "로션 라벨.pdf", "미스트 v2.pdf", "미스트 최종.pdf",
                   "고아 파일.pdf"]
        for n in names_b:
            self.pdf("단품", "before", n, [base_page()])
        for n in names_a:
            self.pdf("단품", "after", n, [base_page()])
        cfg = self.cfg()
        files, _, _ = layout.scan_all(cfg)
        res = pairing.build_candidates(files, cfg["groups"], 0.75)
        self.assertEqual(res["candidates"], [], "no automatic unique candidate expected in this set")
        reasons = {}
        for i in res["issues"]:
            key = i.get("before_relative_path") or i.get("after_relative_path")
            reasons[Path(key).name] = i["reason"]
        self.assertEqual(reasons["미스트 v1.pdf"], "MULTIPLE_CANDIDATES")
        self.assertEqual(reasons["앰플.pdf"], "MISSING_AFTER_COUNTERPART")
        self.assertEqual(reasons["고아 파일.pdf"], "MISSING_BEFORE_COUNTERPART")
        blocked = {tuple(b["blocked_reasons"]) for b in res["blocked_similar_names"]}
        self.assertTrue(any("VOLUME_DIFFERS" in b for b in blocked))
        self.assertTrue(any("LANGUAGE_OR_COUNTRY_DIFFERS" in b for b in blocked))
        self.assertTrue(any("CODE_OR_NUMBER_DIFFERS" in b for b in blocked))
        self.assertTrue(any("PACKAGING_TYPE_DIFFERS" in b for b in blocked))
        # version/date words are stripped but codes and volumes are kept
        f = pairing.name_features("크림 GX-120 50ml 20251101_v3 최종.pdf")
        self.assertIn("50ml", f["volumes"])
        self.assertTrue(any("120" in c for c in f["codes"]))
        self.assertNotIn("20251101", f["base_key"])
        self.assertNotIn("v3", f["base_key"])

    def test_version_suffix_candidate_needs_approval(self):
        self.pdf("세트", "before", "기획세트 A100_v1.pdf", [base_page()])
        self.pdf("세트", "after", "기획세트 A100_v2.pdf", [base_page()])
        cfg = self.cfg()
        from pair_resolver import cmd_scan

        cmd_scan(cfg)
        pair = load_manifest(cfg)["pairs"][0]
        self.assertEqual(pair["matching_basis"], "SAME_NAME_AFTER_VERSION_DATE_WORDS_REMOVED")
        self.assertFalse(pair["approved_for_comparison"])
        with self.assertRaises(FinalError) as cm:
            run_pair(cfg, pair["pair_id"])
        self.assertEqual(cm.exception.code, "PAIR_NOT_APPROVED_RUN_PAIR_RESOLVER_APPROVE")


# --------------------------------------------------------------------------- comparison
class Comparison(Base):
    def test_no_requests_reports_changes_only(self):
        b = base_page()
        a = with_text(with_text(b, "내용량 50ml", "내용량 60ml"), "피부 보습에 도움을 줍니다", None)
        cfg, pid = self.one_pair([b], [a], cfg={"processing": {"pdf_report": True}})
        res = run_pair(cfg, pid)
        rep, d = self.report(cfg, res)
        self.assertEqual(rep["requests"]["request_status"], "NOT_PROVIDED")
        self.assertEqual(rep["requests"]["request_checks"], [])
        changed = self.items(rep, "TEXT_CHANGED")
        self.assertEqual([(i["before"], i["after"]) for i in changed], [("내용량 50ml", "내용량 60ml")])
        self.assertTrue(changed[0]["numeric_change"])
        self.assertEqual([i["before"] for i in self.items(rep, "TEXT_REMOVED")], ["피부 보습에 도움을 줍니다"])
        html_text = (d / "report.private.html").read_text(encoding="utf-8")
        safe = (d / "summary.safe.json").read_text(encoding="utf-8") + (d / "notify_safe.txt").read_text(encoding="utf-8")
        for word in FORBIDDEN_WITHOUT_REQUESTS:
            self.assertNotIn(word, html_text)
            self.assertNotIn(word, safe)
        self.assertTrue((d / "report.private.pdf").exists())
        self.assertEqual(json.loads((d / "summary.safe.json").read_text())["pdf_report"], "WRITTEN")
        # safe files contain no artwork text, names or paths
        for leak in ("가상크림", "50ml", "60ml", "가상 원화", str(self.root), "T"):
            if leak == "T":
                continue
            self.assertNotIn(leak, safe)

    def write_requests(self, cfg, pid, data):
        d = cfg["_requests_dir"]
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{pid}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_requests_three_way(self):
        b = base_page(texts=base_page()["texts"] + [(250, 200, "패널B 내용량 50ml", 9)])
        a = with_text(b, "피부 보습에 도움을 줍니다", "피부 보습과 진정에 도움을 줍니다")  # requested replace: done
        a = with_text(a, "사용기한 2027.11.04", "사용기한 2026.11.04")                    # unrequested numeric change
        a = with_text(a, "제조번호 LOT A1234", "제조번호 LOT A1234")                      # delete requested but kept
        a = with_text(a, "내용량 50ml", "내용량 40ml")                                    # protected, previous value back
        cfg, pid = self.one_pair([b], [a])
        before_hash = load_manifest(cfg)["pairs"][0]["before_content_sha256"]
        self.write_requests(cfg, pid, {
            "pair_id": pid, "category": "세트", "baseline_content_sha256": before_hash,
            "requests": [
                {"request_id": "R1", "requested_by": "BM", "operation": "replace", "page": 1,
                 "before_value": "보습에", "after_value": "보습과 진정에"},
                {"request_id": "R2", "requested_by": "DESIGNER", "operation": "delete", "page": 1,
                 "before_value": "LOT A1234"},
                {"request_id": "R3", "requested_by": "BM", "operation": "replace", "page": 1, "region": [20, 60, 200, 90],
                 "before_value": "50ml", "after_value": "60ml"},
                {"request_id": "R4", "requested_by": "BM", "operation": "replace", "context": "모이스처",
                 "before_value": "GX-120", "after_value": "GX-121"},
                {"request_id": "R5", "requested_by": "DESIGNER", "operation": "replace", "context": "모이스처",
                 "before_value": "GX-120", "after_value": "GX-130"},
            ],
            "protected_fields": [{"field_id": "P1", "value": "50ml", "page": 1, "region": [20, 60, 200, 90],
                                  "previous_values": ["40ml"]}],
        })
        res = run_pair(cfg, pid)
        rep, _ = self.report(cfg, res)
        st = {c["request_id"]: c["status"] for c in rep["requests"]["request_checks"]}
        self.assertEqual(st["R1"], "REFLECTED")
        self.assertEqual(st["R2"], "NOT_REFLECTED")
        # R3 wants to replace a value that is also listed as protected -> human decision, no auto verdict
        self.assertEqual(st["R3"], "CONFLICT_HOLD")
        r3 = [c for c in rep["requests"]["request_checks"] if c["request_id"] == "R3"][0]
        self.assertIn("P1", r3["conflict_with"])
        self.assertEqual(st["R4"], "CONFLICT_HOLD")
        self.assertEqual(st["R5"], "CONFLICT_HOLD")
        self.assertEqual(rep["requests"]["protected_checks"][0]["status"], "REVERT_SUSPECTED")
        flags = {o["flag"] for o in rep["outside_request_scope"]}
        self.assertIn("UNREQUESTED_NUMERIC_CHANGE", flags)

    def test_same_word_in_other_panel_is_not_counted(self):
        b = base_page(texts=base_page()["texts"] + [(250, 200, "패널B 60ml", 9)])
        a = b  # nothing changed in panel A
        a = with_text(a, "제조번호 LOT A1234", "제조번호 LOT A1235")
        cfg, pid = self.one_pair([b], [a])
        self.write_requests(cfg, pid, {"requests": [
            {"request_id": "R1", "requested_by": "BM", "operation": "replace", "page": 1, "region": [20, 60, 200, 90],
             "before_value": "50ml", "after_value": "60ml"}]})
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        chk = rep["requests"]["request_checks"][0]
        self.assertEqual(chk["status"], "NOT_REFLECTED")
        self.assertEqual(chk.get("note"), "AFTER_VALUE_FOUND_OUTSIDE_REQUEST_SCOPE_NOT_COUNTED")
        self.assertIn("BASELINE_HASH_NOT_PINNED", " ".join(rep["requests"]["notes"]))

    def test_requests_for_other_baseline_are_held(self):
        b = base_page()
        a = with_text(b, "내용량 50ml", "내용량 60ml")
        cfg, pid = self.one_pair([b], [a])
        self.write_requests(cfg, pid, {"baseline_content_sha256": "0" * 64, "requests": [
            {"request_id": "R1", "operation": "replace", "before_value": "50ml", "after_value": "60ml"}]})
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(rep["requests"]["request_checks"][0]["status"], "HOLD")
        self.assertEqual(rep["requests"]["request_checks"][0]["reason"], "REQUESTS_BASELINE_HASH_MISMATCH")

    def test_outlined_digits_small_change_is_visual_candidate(self):
        b = {"size": (300, 200), "seg_digits": [(40, 60, "50", 18)], "rects": [LOGO]}
        a = {"size": (300, 200), "seg_digits": [(40, 60, "60", 18)], "rects": [LOGO]}
        cfg, pid = self.one_pair([b], [a])
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        page = rep["pages"][0]
        self.assertEqual(page["text"]["status"], "UNVERIFIABLE_NO_TEXT_LAYER")
        self.assertEqual(rep["overall_status"], "PARTIAL_COVERAGE")
        regs = self.regions(rep)
        self.assertEqual(len(regs), 1)
        self.assertTrue(regs[0]["visual_only"])
        x0, y0, x1, y1 = regs[0]["box_pt_before_frame"]
        self.assertTrue(x0 >= 30 and x1 <= 70 and y0 >= 50 and y1 <= 85, regs[0]["box_pt_before_frame"])

    def test_one_side_outlined_text_is_unverifiable_not_deleted(self):
        b = {"size": (300, 200), "texts": [(40, 60, "50", 18)]}
        a = {"size": (300, 200), "seg_digits": [(40, 46, "50", 16)]}
        cfg, pid = self.one_pair([b], [a])
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(rep["pages"][0]["text"]["status"], "UNVERIFIABLE_TEXT_LAYER_ONLY_ONE_SIDE")
        self.assertEqual(self.items(rep, "TEXT_REMOVED"), [])

    def test_image_and_mixed_pdf_profiles(self):
        img = {"size": (300, 200), "image_texts": [(20, 40, "이미지 문구 50ml", 14)]}
        mixed = {"size": (300, 200), "texts": [(20, 30, "텍스트 문구", 12)], "image_texts": [(20, 60, "이미지 문구", 30)]}
        self.pdf("단품", "before", "img.pdf", [img])
        self.pdf("단품", "before", "mixed.pdf", [mixed])
        out = subprocess.run([sys.executable, str(ROOT / "local_preflight.py"), "--config", self._write_cfg()],
                             capture_output=True, text=True, timeout=120)
        summ = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertTrue(summ["ok"], summ)
        self.assertEqual(summ["content_classes"].get("IMAGE_ONLY"), 1)
        self.assertEqual(summ["content_classes"].get("MIXED_TEXT_AND_GRAPHICS"), 1)

    def _write_cfg(self, **over) -> str:
        p = self.base / "config.local.json"
        raw = {"privacy_mode": "LOCAL_ONLY", "root_dir": str(self.root), "output_dir": str(self.out),
               "processing": {"page_isolation": "inline"}}
        raw.update(over)
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def test_text_order_change_is_not_content_change(self):
        b = base_page()
        a = {**b, "texts": list(reversed(b["texts"]))}  # same text/positions, different content-stream order
        cfg, pid = self.one_pair([b], [a])
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(self.items(rep), [])
        self.assertGreater(rep["pages"][0]["text"]["extraction_order_changes"], 0)
        self.assertEqual(self.regions(rep), [])

    def test_canvas_shift_vs_logo_move(self):
        b = base_page()
        moved_logo = {**b, "rects": [((300, 100, 380, 140), LOGO[1])]}
        cases = {
            "shift_only": ([b], [b], {"akw": {"shift": (14, 9)}}),
            "logo_only": ([b], [moved_logo], {}),
            "shift_and_logo": ([b], [moved_logo], {"akw": {"shift": (14, 9)}}),
        }
        for name, (bp, ap, kw) in cases.items():
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                cfg, pid = self.one_pair(bp, ap, **kw)
                rep, _ = self.report(cfg, run_pair(cfg, pid))
                shifted = bool(rep["canvas_shifts"])
                moves = self.regions(rep, "MOVE_CANDIDATE")
                others = [r for r in self.regions(rep) if r["kind"] != "MOVE_CANDIDATE"]
                self.assertEqual(self.items(rep, "TEXT_MOVED"), [])
                if name == "shift_only":
                    self.assertTrue(shifted)
                    self.assertEqual(self.regions(rep), [])
                else:
                    self.assertEqual(shifted, name == "shift_and_logo")
                    self.assertEqual(len(moves), 2, self.regions(rep))
                    self.assertEqual(others, [])
                    self.assertAlmostEqual(moves[0]["move_pt"][1], 70, delta=2)

    def test_small_number_and_whitespace(self):
        b = base_page()
        a = with_text(with_text(b, "사용기한 2027.11.04", "사용기한 2027.11.05"), "내용량 50ml", "내용량  50ml")
        cfg, pid = self.one_pair([b], [a])
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        ch = {i["kind"]: i for i in self.items(rep)}
        self.assertTrue(ch["TEXT_CHANGED"]["numeric_change"])
        self.assertIn("EXPIRY_OR_DATE", ch["TEXT_CHANGED"]["field_hints"])
        self.assertEqual(ch["WHITESPACE_ONLY_CHANGE"]["after"], "내용량  50ml")
        self.assertTrue(any("M001-T" in t for r in self.regions(rep) for t in r["linked_text_change_ids"]))

    def test_page_added_reordered_resized_and_page_map(self):
        p1 = base_page()
        p2 = base_page(texts=[(30, 50, "두번째 패널 성분 안내", 12), (30, 80, "정제수 글리세린", 10)])
        p3 = base_page(texts=[(30, 50, "세번째 패널 주의사항", 12)])
        cfg, pid = self.one_pair([p1, p2], [p2, p1, p3])
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(rep["overall_status"], "UNVERIFIABLE_NOTHING_COMPARED")
        self.assertTrue(all(u["reason"] == "PAGE_MAP_REQUIRED_PAGE_COUNT_CHANGED" for u in rep["coverage"]["unprocessed"]))
        sugg = {(s["before_page"], s["after_page"]) for s in rep["page_mapping"]["suggested_page_map"]}
        self.assertEqual(sugg, {(1, 2), (2, 1)})
        from pair_resolver import cmd_page_map

        cmd_page_map(cfg, type("A", (), {"pair_id": pid, "map": "1:2,2:1,-:3", "by": "tester"})())
        rep2, _ = self.report(cfg, run_pair(cfg, pid, force=True))
        self.assertEqual(rep2["coverage"]["entries_compared"], 2)
        self.assertEqual(self.items(rep2), [])
        self.assertEqual([u["after_page"] for u in rep2["coverage"]["unprocessed"]], [3])
        self.assertEqual(rep2["overall_status"], "PARTIAL_COVERAGE")

    def test_page_size_change_requires_map(self):
        cfg, pid = self.one_pair([base_page()], [base_page(size=(440, 300))])
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(rep["coverage"]["unprocessed"][0]["reason"], "PAGE_MAP_REQUIRED_SIZE_OR_ROTATION_CHANGED")

    def test_multi_artboard_clip_map(self):
        left = [(30, 50, "아트보드1 내용량 50ml", 12)]
        right = [(330, 50, "아트보드2 내용량 30ml", 12)]
        b = {"size": (600, 200), "texts": left + right}
        a = {"size": (600, 200), "texts": [(30, 50, "아트보드1 내용량 50ml", 12), (330, 50, "아트보드2 내용량 35ml", 12)]}
        cfg, pid = self.one_pair([b], [a])
        m = load_manifest(cfg)
        m["pairs"][0]["page_map"] = [
            {"before_page": 1, "after_page": 1, "before_clip": [0, 0, 300, 200], "after_clip": [0, 0, 300, 200]},
            {"before_page": 1, "after_page": 1, "before_clip": [300, 0, 600, 200], "after_clip": [300, 0, 600, 200]}]
        save_manifest(cfg, m)
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        by_label = {p["label"]: p for p in rep["pages"]}
        self.assertEqual(by_label["M001"]["text"]["items"], [])
        self.assertEqual([(i["before"], i["after"]) for i in by_label["M002"]["text"]["items"]],
                         [("아트보드2 내용량 30ml", "아트보드2 내용량 35ml")])
        self.assertEqual(len(by_label["M001"]["visual"]["regions"]), 0)


# --------------------------------------------------------------------------- robustness
class Robustness(Base):
    def test_large_page_is_downscaled_and_page_limit_reported(self):
        big = base_page(size=(5000, 4000))
        pages_b = [big] + [base_page()] * 3
        pages_a = [with_text(big, "내용량 50ml", "내용량 70ml")] + [base_page()] * 3
        cfg, pid = self.one_pair(pages_b, pages_a, cfg={"processing": {"max_page_pixels": 2_000_000, "max_pages_per_file": 3, "min_visual_dpi": 15}})
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        p1 = rep["pages"][0]
        w, h = p1["visual"]["canvas_px"]
        self.assertLessEqual(w * h, 2_000_000)
        self.assertEqual([u["reason"] for u in rep["coverage"]["unprocessed"]], ["UNPROCESSED_PAGE_LIMIT"])
        self.assertEqual(rep["overall_status"], "PARTIAL_COVERAGE")
        self.assertEqual(len(self.items(rep, "TEXT_CHANGED")), 1)

    def test_pixel_limit_skip_is_reported(self):
        cfg, pid = self.one_pair([base_page(size=(5000, 5000))], [base_page(size=(5000, 5000))],
                                 cfg={"processing": {"max_page_pixels": 200_000, "min_visual_dpi": 40}})
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(rep["pages"][0]["visual"]["status"], "SKIPPED_PIXEL_LIMIT_PAGE_TOO_LARGE")
        self.assertEqual(rep["overall_status"], "PARTIAL_COVERAGE")

    def test_retry_after_failure_and_resume(self):
        b = [base_page(), base_page()]
        a = [base_page(), with_text(base_page(), "내용량 50ml", "내용량 60ml")]
        cfg, pid = self.one_pair(b, a)
        os.environ["FINAL_TEST_FAULT"] = "M002:1"  # TEST-ONLY fault, one failure
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual({x["label"]: x["attempts"] for x in rep["attempts"]}["M002"], 2)
        self.assertEqual(rep["overall_status"], "COMPARED_WITH_LIMITATIONS")
        # persistent failure beyond retries -> partial, never "no change"
        self.tearDown()
        self.setUp()
        cfg, pid = self.one_pair(b, a)
        os.environ["FINAL_TEST_FAULT"] = "M002:99"
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(rep["overall_status"], "PARTIAL_COVERAGE")
        self.assertEqual(rep["coverage"]["unprocessed"][0]["reason"], "PAGE_PROCESSING_ERROR")
        # automatic retry on the next run: cached M001 reused, failed M002 processed again
        os.environ.pop("FINAL_TEST_FAULT")
        self.assertEqual(len(find_pending(cfg)["pending"]), 1)
        rep2, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(rep2["overall_status"], "COMPARED_WITH_LIMITATIONS")
        self.assertEqual({p["label"]: bool(p.get("from_cache")) for p in rep2["pages"]}, {"M001": True, "M002": False})
        self.assertEqual(find_pending(cfg)["pending"], [])

    def test_interrupted_run_resumes_from_cache(self):
        b = [base_page(), base_page()]
        a = [base_page(), with_text(base_page(), "내용량 50ml", "내용량 60ml")]
        cfg, pid = self.one_pair(b, a)
        os.environ["FINAL_TEST_FAULT"] = "M002:99"
        run_pair(cfg, pid)
        os.environ.pop("FINAL_TEST_FAULT")
        # simulate a crash: ledger says RUNNING
        from final_check.local_runner import load_ledger, save_ledger

        led = load_ledger(cfg)
        for r in led["runs"].values():
            r["compare_status"] = "RUNNING"
        save_ledger(cfg, led)
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(rep["overall_status"], "COMPARED_WITH_LIMITATIONS")
        cache = {p["label"]: p.get("from_cache", False) for p in rep["pages"]}
        self.assertTrue(cache["M001"])
        self.assertFalse(cache["M002"])

    def test_process_isolation_timeout(self):
        cfg, pid = self.one_pair([base_page()], [base_page()],
                                 cfg={"processing": {"page_isolation": "process", "page_timeout_seconds": 4, "max_retries": 0}})
        os.environ["FINAL_TEST_FAULT"] = "M001:1"
        os.environ["FINAL_TEST_FAULT_MODE"] = "hang"
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(rep["coverage"]["unprocessed"][0]["reason"], "PAGE_TIMEOUT")
        self.assertEqual(rep["overall_status"], "UNVERIFIABLE_NOTHING_COMPARED")

    def test_process_isolation_success(self):
        cfg, pid = self.one_pair([base_page()], [with_text(base_page(), "내용량 50ml", "내용량 60ml")],
                                 cfg={"processing": {"page_isolation": "process"}})
        rep, _ = self.report(cfg, run_pair(cfg, pid))
        self.assertEqual(len(self.items(rep, "TEXT_CHANGED")), 1)

    def test_copying_and_temporary_files(self):
        cfg, pid = self.one_pair([base_page()], [base_page()])
        after = self.dir("세트", "after") / "가상 원화.pdf"
        build_pdf(after, [with_text(base_page(), "내용량 50ml", "내용량 60ml")])  # just written -> not stable
        res = run_pair(cfg, pid)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error_code"], "AFTER_FILE_NOT_STABLE_RECENTLY_MODIFIED")
        self.assertEqual(find_pending(cfg)["waiting_not_stable"], 1)
        (self.dir("세트", "after") / "~$임시.pdf").write_bytes(b"x")
        (self.dir("세트", "after") / "복사중.pdf.part").write_bytes(b"x")
        _, skipped, _ = layout.scan_all(cfg)
        self.assertEqual(skipped["temporary_or_hidden"], 2)

    def test_duplicates_overwrite_and_baseline_change(self):
        b = base_page()
        cfg, pid = self.one_pair([b], [with_text(b, "내용량 50ml", "내용량 60ml")])
        r1 = run_pair(cfg, pid, event_id="gmail-1")
        self.assertEqual(r1["status"], "COMPARED")
        self.assertEqual(run_pair(cfg, pid, event_id="gmail-1")["status"], "DUPLICATE_EVENT_IGNORED")
        self.assertEqual(run_pair(cfg, pid, event_id="gmail-2")["status"], "ALREADY_PROCESSED_SAME_CONTENT")
        self.assertEqual(find_pending(cfg)["pending"], [])
        # the after file is overwritten under the same name -> new content hash, new run
        after = self.dir("세트", "after") / "가상 원화.pdf"
        build_pdf(after, [with_text(b, "내용량 50ml", "내용량 70ml")])
        os.utime(after, (OLD + 10, OLD + 10))
        pend = find_pending(cfg)["pending"]
        self.assertEqual(len(pend), 1)
        r2 = run_pair(cfg, pid, event_id=pend[0]["event_id"])
        self.assertEqual(r2["status"], "COMPARED")
        self.assertNotEqual(r1["run_key"], r2["run_key"])
        rep, _ = self.report(cfg, r2)
        self.assertTrue(rep["approval_snapshot"]["after_differs_from_approval_snapshot"])
        # delivery is recorded separately; DONE only after a send/receipt record
        d = record_delivery(cfg, r2["run_key"], "LOCAL_ONLY_NOT_SENT")
        self.assertFalse(d["done"])
        self.assertTrue(record_delivery(cfg, r2["run_key"], "SENT_ACCEPTED_BY_PROVIDER", "msg-1")["done"])
        # baseline overwritten -> refuse until re-approved
        before = self.dir("세트", "before") / "가상 원화.pdf"
        build_pdf(before, [with_text(b, "사용기한 2027.11.04", "사용기한 2028.01.01")])
        os.utime(before, (OLD, OLD))
        with self.assertRaises(FinalError) as cm:
            run_pair(cfg, pid)
        self.assertEqual(cm.exception.code, "BASELINE_CONTENT_CHANGED_SINCE_APPROVAL_REAPPROVE_PAIR")

    def test_encrypted_and_damaged(self):
        self.pdf("세트", "before", "x.pdf", [base_page()])
        p = self.dir("세트", "after") / "x.pdf"
        build_pdf(p, [base_page()], encrypt=True)
        os.utime(p, (OLD, OLD))
        bad = self.dir("단품", "before") / "broken.pdf"
        bad.write_bytes(b"%PDF-1.4 broken")
        os.utime(bad, (OLD, OLD))
        cfg = self.cfg()
        ids = self.approve_all(cfg)
        with self.assertRaises(FinalError) as cm:
            run_pair(cfg, ids["SET"])
        self.assertEqual(cm.exception.code, "PDF_ENCRYPTED_UNVERIFIABLE")

    def test_file_names_do_not_drive_results(self):
        # misleading names: "변경없음" file actually changed; result must follow content
        self.pdf("세트", "before", "변경없음_정답.pdf", [base_page()])
        self.pdf("세트", "after", "변경없음_정답.pdf", [with_text(base_page(), "내용량 50ml", "내용량 55ml")])
        cfg = self.cfg()
        ids = self.approve_all(cfg)
        rep, _ = self.report(cfg, run_pair(cfg, ids["SET"]))
        self.assertEqual([(i["before"], i["after"]) for i in self.items(rep, "TEXT_CHANGED")], [("내용량 50ml", "내용량 55ml")])


# --------------------------------------------------------------------------- safety
class Safety(Base):
    def test_source_untouched_and_output_separate(self):
        b = base_page()
        cfg, pid = self.one_pair([b], [with_text(b, "내용량 50ml", "내용량 60ml")])
        before = tree_fingerprint(self.root)
        run_pair(cfg, pid)
        subprocess.run([sys.executable, str(ROOT / "local_preflight.py"), "--config", self._cfgfile()],
                       capture_output=True, timeout=120)
        self.assertEqual(before, tree_fingerprint(self.root))
        for bad in (self.root / "out", self.root):
            with self.assertRaises(FinalError) as cm:
                validate_local_config({"privacy_mode": "LOCAL_ONLY", "root_dir": str(self.root), "output_dir": str(bad)})
            self.assertEqual(cm.exception.code, "SOURCE_AND_OUTPUT_MUST_BE_SEPARATE")

    def _cfgfile(self) -> str:
        p = self.base / "config.local.json"
        p.write_text(json.dumps({"privacy_mode": "LOCAL_ONLY", "root_dir": str(self.root), "output_dir": str(self.out)},
                                ensure_ascii=False), encoding="utf-8")
        return str(p)

    def test_config_guards(self):
        base = {"privacy_mode": "LOCAL_ONLY", "root_dir": str(self.root), "output_dir": str(self.out)}
        bad = [({"matching": {"cross_category": True}}, "CROSS_CATEGORY_MATCHING_NOT_ALLOWED"),
               ({"matching": {"auto_select_latest": True}}, "AUTO_SELECT_LATEST_NOT_ALLOWED"),
               ({"external": {"cloud_llm_enabled": True}}, "EXTERNAL_TRANSFER_NOT_ALLOWED_IN_LOCAL_ONLY"),
               ({"external": {"external_email_enabled": True}}, "EXTERNAL_TRANSFER_NOT_ALLOWED_IN_LOCAL_ONLY"),
               ({"privacy_mode": "APPROVED_EXTERNAL_B"}, "LOCAL_PROGRAMS_REQUIRE_PRIVACY_MODE_LOCAL_ONLY"),
               ({"processing": {"ocr_enabled": True}}, "OCR_NOT_IMPLEMENTED_KEEP_FALSE"),
               ({"notification": {"safe_email_enabled": True}}, "SAFE_EMAIL_REQUIRES_APPROVAL_NOTE"),
               ({"root_dir": "REPLACE_WITH_YOUR_LOCAL_ARTWORK_ROOT"}, "CONFIGURE_ROOT_AND_OUTPUT_DIRECTORIES")]
        for over, code in bad:
            with self.subTest(code=code):
                with self.assertRaises(FinalError) as cm:
                    validate_local_config({**base, **over})
                self.assertEqual(cm.exception.code, code)

    def test_symlink_source_refused(self):
        target = self.base / "outside"
        target.mkdir()
        build_pdf(target / "x.pdf", [base_page()])
        try:
            (self.dir("세트", "before") / "link.pdf").symlink_to(target / "x.pdf")
        except OSError:
            self.skipTest("symlinks not permitted")
        _, skipped, _ = layout.scan_all(self.cfg())
        self.assertEqual(skipped["symlinks"], 1)

    def test_console_output_has_no_sensitive_text(self):
        b = base_page()
        self.pdf("세트", "before", "비밀제품명 GX-120.pdf", [b])
        self.pdf("세트", "after", "비밀제품명 GX-120.pdf", [with_text(b, "내용량 50ml", "내용량 60ml")])
        cfgp = self._cfgfile()
        outs = []
        for args in (["local_preflight.py", "--config", cfgp], ["pair_resolver.py", "scan", "--config", cfgp]):
            outs.append(subprocess.run([sys.executable, str(ROOT / args[0])] + args[1:], capture_output=True, text=True, timeout=120))
        pid = json.loads(Path(self.out / "pair_manifest.local.json").read_text())["pairs"][0]["pair_id"]
        outs.append(subprocess.run([sys.executable, str(ROOT / "pair_resolver.py"), "approve", "--config", cfgp, "--pair-id", pid,
                                    "--artwork-id", "비밀ID", "--by", "tester"], capture_output=True, text=True, timeout=120))
        outs.append(subprocess.run([sys.executable, str(ROOT / "compare_engine.py"), "--config", cfgp, "--pair-id", pid],
                                   capture_output=True, text=True, timeout=300))
        outs.append(subprocess.run([sys.executable, str(ROOT / "compare_engine.py"), "--config", cfgp, "--pair-id", "BAD"],
                                   capture_output=True, text=True, timeout=120))
        joined = "".join(o.stdout + o.stderr for o in outs)
        for leak in ("비밀제품명", "GX-120", "50ml", "60ml", "가상크림", str(self.root), str(self.base), "비밀ID", "Traceback"):
            self.assertNotIn(leak, joined)
        self.assertIn('"status": "COMPARED"', outs[3].stdout)
        self.assertIn("PAIR_ID_FORMAT_INVALID", outs[4].stdout)

    def test_network_guard_blocks_external_allows_loopback(self):
        code = (
            "import sys,socket,urllib.request;sys.path.insert(0,%r);"
            "from final_check.common import install_network_guard,FinalError;install_network_guard()\n"
            "try:\n urllib.request.urlopen('https://example.com',timeout=3);print('LEAK')\n"
            "except FinalError as e: print(e.code)\n"
            "except Exception as e: print('OTHER',type(e).__name__)\n"
            "s=socket.socket();s.bind(('127.0.0.1',0));s.listen(1);c=socket.socket();c.connect(s.getsockname());print('LOOPBACK_OK')"
        ) % str(ROOT)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30).stdout
        self.assertIn("NETWORK_BLOCKED_LOCAL_ONLY", out)
        self.assertIn("LOOPBACK_OK", out)
        self.assertNotIn("LEAK", out)

    def test_local_code_has_no_outbound_client_imports(self):
        import re

        files = list((ROOT / "final_check").glob("*.py")) + [ROOT / n for n in
                                                              ("local_preflight.py", "pair_resolver.py", "compare_engine.py", "local_api.py")]
        pattern = re.compile(r"^\s*(import|from)\s+(requests|httpx|urllib\.request|http\.client|smtplib|ftplib|aiohttp|openai|anthropic)\b", re.M)
        for f in files:
            self.assertIsNone(pattern.search(f.read_text(encoding="utf-8")), f.name)

    def test_local_api(self):
        import local_api

        b = base_page()
        cfg, pid = self.one_pair([b], [with_text(b, "내용량 50ml", "내용량 60ml")],
                                 cfg={"local_api": {"port": 0, "token": "x" * 32}})
        with self.assertRaises(FinalError):
            local_api.check_bind({**cfg, "local_api": {"host": "0.0.0.0", "port": 0, "token": "x" * 32,
                                                       "allow_non_loopback_bind": True}})
        with self.assertRaises(FinalError):
            local_api.check_bind({**cfg, "local_api": {"host": "127.0.0.1", "port": 0, "token": "CHANGE_ME"}})
        srv = local_api.build_server(cfg)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"

        def call(path, body=None, token="x" * 32):
            req = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={"X-FINAL-Token": token, "Content-Type": "application/json"},
                                         method="GET" if body is None else "POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            self.assertEqual(call("/health")[0], 200)
            self.assertEqual(call("/health", token="wrong")[0], 401)
            self.assertEqual(call("/compare", {"pair_id": pid, "path": "/etc/passwd"})[1]["error_code"],
                             "UNKNOWN_FIELDS_PATHS_AND_URLS_NOT_ACCEPTED")
            scan = call("/scan", {})[1]
            self.assertEqual(scan["pending"][0]["pair_id"], pid)
            st, res = call("/compare", {"pair_id": pid, "event_id": scan["pending"][0]["event_id"]})
            self.assertEqual(res["status"], "COMPARED")
            body = json.dumps(res, ensure_ascii=False)
            for leak in ("50ml", "60ml", "가상크림", str(self.root)):
                self.assertNotIn(leak, body)
            self.assertEqual(call("/compare", {"pair_id": pid, "event_id": scan["pending"][0]["event_id"]})[1]["status"],
                             "DUPLICATE_EVENT_IGNORED")
            self.assertTrue(call("/delivery", {"run_key": res["run_key"], "status": "SENT_ACCEPTED_BY_PROVIDER",
                                               "message_id": "m1"})[1]["done"])
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- APPROVED_EXTERNAL_B service (synthetic only)
class ApprovedExternalB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        sys.path.insert(0, str(ROOT / "b_service"))

    def tearDown(self):
        self.tmp.cleanup()

    def cfg_file(self, **over):
        raw = {"privacy_mode": "APPROVED_EXTERNAL_B",
               "approval": {"approved_by": "tester", "approved_at": "2026-11-04", "scope_note": "synthetic test only",
                            "data_classification": "NON_CONFIDENTIAL_RECREATED_SAMPLE"},
               "service": {"token": "b" * 32, "port": 0, "max_upload_mb": 5}}
        raw.update(over)
        p = self.base / "config.b.json"
        p.write_text(json.dumps(raw), encoding="utf-8")
        return str(p)

    def test_b_config_gates(self):
        import b_service

        for over, code in (({"privacy_mode": "LOCAL_ONLY"}, "B_SERVICE_REQUIRES_PRIVACY_MODE_APPROVED_EXTERNAL_B"),
                           ({"root_dir": "/x"}, "B_SERVICE_MUST_NOT_HAVE_LOCAL_ROOT_OR_OUTPUT"),
                           ({"approval": {}}, "B_APPROVAL_RECORD_INCOMPLETE")):
            with self.subTest(code=code):
                with self.assertRaises(FinalError) as cm:
                    b_service.load_b_config(self.cfg_file(**over))
                self.assertEqual(cm.exception.code, code)

    def test_b_compare_over_http(self):
        import b_service
        from http.server import HTTPServer

        cfg = b_service.load_b_config(self.cfg_file())
        srv = HTTPServer(("127.0.0.1", 0), b_service.make_handler(cfg))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        bpath = build_pdf(self.base / "b.pdf", [base_page()])
        apath = build_pdf(self.base / "a.pdf", [with_text(base_page(), "내용량 50ml", "내용량 60ml")])
        boundary = "----finaltest"
        parts = []
        for name, value in (("category_code", "SET"), ("artwork_id", "DEMO01")):
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        for name, path in (("before", bpath), ("after", apath)):
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{name}.pdf\"\r\n"
                         f"Content-Type: application/pdf\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/b/compare", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-FINAL-Token": "b" * 32})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                res = json.loads(r.read())
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["summary"]["text_changes_by_kind"].get("TEXT_CHANGED"), 1)
        import base64

        html_text = base64.b64decode(res["report_html_b64"]).decode()
        self.assertIn("내용량␣60ml", html_text)
        self.assertIn("data:image/png;base64,", html_text)
