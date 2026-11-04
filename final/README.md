# FINAL? — Is this really the final version?

화장품 원화 before/after PDF를 **로컬에서** 비교해 텍스트·숫자·시각적 변경 후보를 근거와 함께 보여 주고,
수정 요청서가 있을 때만 반영 여부를 대조하는 n8n 백엔드 자동화입니다. 최종 승인·인쇄 적합성 판단은 사람이 합니다.

- **시작하기:** [START_HERE_KO.md](START_HERE_KO.md)
- 보안·권한·네트워크: [docs/SECURITY_AND_PERMISSIONS_KO.md](docs/SECURITY_AND_PERMISSIONS_KO.md)
- 검증 범위(무엇을 했고 무엇을 안 했는지): [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md)
- 기존 B안 대비 변경과 한계: [docs/README_VALIDATION.md](docs/README_VALIDATION.md)

| 파일 | 역할 |
|---|---|
| `local_preflight.py` | 원본을 변경하지 않는 구조·크기·페이지·텍스트 레이어 진단 |
| `pair_resolver.py` | 세트·단품별 before/after 후보 → 사람이 approve → `pair_manifest.local.json` |
| `compare_engine.py` | 승인된 짝의 텍스트+시각 비교, 로컬 보고서(HTML/PDF/JSON) + 안전 요약 |
| `local_api.py` | 같은 PC의 n8n용 127.0.0.1 API (pair_id만 받음) |
| `n8n/FINAL_Local_Workflow.json` | LOCAL_ONLY 자동화 (Schedule → 로컬 API → 기록, 안전 요약 메일은 기본 OFF) |
| `n8n/FINAL_B_Approved_Workflow.json` + `b_service/` | APPROVED_EXTERNAL_B: 허가·비기밀 재제작 자료 전용 Gmail+Drive 흐름 (기본 OFF) |
| `demo_synthetic.py`, `tests/` | 합성(가상) 자료 데모와 회귀 테스트 |
| `reference/LEGACY_B_REFERENCE_ONLY.json` | 과거 참고본 (모든 노드 OFF, 제출·Publish 금지) |

기본 모드는 **LOCAL_ONLY**입니다. 실제 회사 원화는 이 저장소에 넣지 않으며, 본인 PC의 별도 터미널에서 처리합니다.
