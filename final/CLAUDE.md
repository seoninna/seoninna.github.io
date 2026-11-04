# FINAL? — rules for AI coding sessions
- Development material only. Never open, read, list or print real company artwork, `config.local.json`, `config.b.json`,
  anything under the user's output_dir, `*.private.*`, or `pair_manifest.local.json` from a real run.
- Default mode LOCAL_ONLY. Do not add network clients, LLM calls, uploads, tunnels, auto-push or share links to local code.
  `tests/test_final.py::test_local_code_has_no_outbound_client_imports` enforces part of this.
- Test only with synthetic fixtures (`tests/synthetic.py`). Never derive expected results from file names.
- Never claim real artwork was inspected unless the user ran it locally and reported only codes/counts.
- Before/after-only input = change detection, never proof of a missed or wrong revision.
- `reference/LEGACY_B_REFERENCE_ONLY.json` is reference only: do not run or publish it.
- Regenerate n8n JSON with `python tools/build_workflows.py`; run `python -m unittest discover -s tests` before committing.
