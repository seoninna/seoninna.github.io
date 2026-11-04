# 기존 구현(B안 참고본) 대비 변경 내역과 한계

검토 대상: `reference/LEGACY_B_REFERENCE_ONLY.json` (모든 실행 노드 OFF 상태의 과거 Gmail+Drive 워크플로, 정적 검토만 함).
**이 참고본은 그대로 Publish하거나 완성본으로 제출하지 않습니다.**

## 1. 무엇을 왜 바꿨나

| 기존 한계 (06_LEGACY_REVIEW) | 변경 | 위치 |
|---|---|---|
| 입력이 Gmail 첨부 + Drive 동명 파일(`PKG001_BASELINE.pdf`)에 의존 | 실제 입력은 **로컬 폴더** (구조 A/B 자동 인식, 폴더명 설정 가능). Drive/Gmail은 승인 자료 전용 B안으로 분리 | `final_check/layout.py`, `config.example.json` |
| 세트/단품 구분·짝 관리 없음 | 카테고리별 스캔, **교차 매칭 3중 차단**(후보 생성·approve·compare 시 폴더 소속 재검증), 사람이 approve한 manifest(pair_id/category/artwork_id/경로/해시/page_map/승인 시각) | `pairing.py`, `pair_resolver.py`, `local_runner.py` |
| 파일명 규칙·최신 파일로 상대 결정 | 파일명은 **후보**만. 버전·날짜 단어는 후보 계산에서만 무시, 코드·숫자·용량·국가·포장 단어가 다르면 차단. 여러 후보/한쪽 없음 → `PAIR_NEEDS_CONFIRMATION`. mtime 미사용 | `pairing.py` |
| 같은 이름 덮어쓰기 구분 불가 | 비교 시 SHA-256 기록, run_key = pair+before해시+after해시+엔진·설정 버전. 기준본 내용 변경 시 재승인 요구 | `local_runner.py` |
| 8MB / 10쪽 / 30,000자 / 1,400단어 고정 제한 | 제한 삭제가 아니라 **설정화**: 페이지별 처리, 렌더 픽셀 상한(`max_page_pixels`), 페이지 수 상한(초과분은 `UNPROCESSED_PAGE_LIMIT`로 명시), 페이지별 프로세스 격리·타임아웃, 페이지 결과 캐시·재개, 실패 페이지 자동 재시도, 렌더 캐시(같은 기준본 재사용), 스트리밍 해시 | `engine.py`, `page_worker.py`, `pdfio.py` |
| 공백·줄바꿈 전부 정규화 → 띄어쓰기 검수 불가 | 원문 그대로 비교. 공백만 다른 경우 `WHITESPACE_ONLY_CHANGE`, 줄바꿈만 다른 경우 `LINE_BREAK_REFLOW_ONLY` 로 **보조 결과 분리** | `textdiff.py` |
| 단어 순서 LCS만, 위치 없음 | 줄 단위 + 좌표(pt). 추출 순서만 바뀐 것은 변경 아님(`extraction_order_changes`). 같은 단어가 다른 패널에 있어도 요청 범위(page/region/context) 밖이면 반영으로 세지 않음 | `textdiff.py`, `requests_eval.py` |
| 시각 비교 없음 (아웃라인 원화 검수 불가) | 페이지별 렌더링 비교, 변경 박스·before/after 크롭(작은 영역은 300dpi 재렌더)·오버레이. **전체 캔버스 이동**은 PDF 텍스트 좌표(가능하면) 또는 재렌더 탐색으로 정밀 보정하고 기록, **개별 요소(로고) 이동은 보정 후에도 남겨** `MOVE_CANDIDATE` 로 표시 | `visual.py`, `page_worker.py` |
| 요청서 필수 | 요청서 없으면 `NOT_PROVIDED` — 변경 사실만 보고, 반영/누락/오수정 판정 문구 없음(테스트로 확인) | `requests_eval.py`, `report.py` |
| BM/디자이너 구분·충돌 처리 없음 | `requested_by` 기록, 같은 대상에 다른 결과 요청 → `CONFLICT_HOLD`, 유지항목과 충돌도 보류. 이전 값 재등장 → `REVERT_SUSPECTED`("원복 의심", 확정 아님) | `requests_eval.py` |
| OpenAI 호출·Gmail 발송 노드가 회사 자료 반출 경로가 될 수 있음 | LOCAL_ONLY는 **외부 LLM 없음**(템플릿 보고서), 설정에서 외부 전송 플래그를 켜면 실행 거부. 메일은 안전 요약만, 기본 OFF + 승인 메모 필수 | `common.py`, `n8n/FINAL_Local_Workflow.json` |
| 발송 성공 전에 완료 처리 위험 | 비교 성공(`compare_status`)과 발송(`delivery.status`)을 **분리 기록**. `done`은 발송 접수/수신 확인 기록 후에만 | `local_runner.py` |
| Railway n8n이 PC 경로를 읽는다고 착각할 위험 | 로컬 모드는 **내 PC의 n8n + 127.0.0.1 API**(pair_id만 전달). B안은 업로드된 PDF만 처리하는 별도 서비스(로컬 root 설정 시 시작 거부) | `local_api.py`, `b_service/` |

## 2. 판정 용어 (보고서)
- 텍스트: `TEXT_CHANGED` / `TEXT_ADDED` / `TEXT_REMOVED` / `TEXT_MOVED` / `TEXT_SIZE_CHANGED` / 보조 `WHITESPACE_ONLY_CHANGE`, `LINE_BREAK_REFLOW_ONLY`
- 시각: `CONTENT_ADDED_CANDIDATE` / `CONTENT_REMOVED_CANDIDATE` / `CONTENT_MODIFIED_CANDIDATE` / `MOVE_CANDIDATE` (모두 **후보**)
- 요청(요청서 있을 때만): `REFLECTED`(반영 근거 있음, 사람 확인 필요) / `NOT_REFLECTED`(미반영 의심) / `HOLD` / `CONFLICT_HOLD` / `UNVERIFIABLE` / `HOLD_HUMAN_VISUAL_CHECK` / 유지항목 `KEPT`, `PROTECTED_CHANGED`, `REVERT_SUSPECTED`
- 전체: `COMPARED_WITH_LIMITATIONS` / `PARTIAL_COVERAGE` / `UNVERIFIABLE_NOTHING_COMPARED`. `final_approval`은 항상 `false`.

## 3. 다중 아트보드 page_map 예시 (`pair_manifest.local.json`)
```json
"page_map": [
  {"before_page": 1, "after_page": 1, "before_clip": [0, 0, 300, 200], "after_clip": [0, 0, 300, 200]},
  {"before_page": 1, "after_page": 1, "before_clip": [300, 0, 600, 200], "after_clip": [300, 0, 600, 200]}
]
```
좌표는 pt(1pt=0.3528mm), 페이지 왼쪽 위 기준. 사전점검의 `artboard_hint` 는 힌트일 뿐 자동 분할하지 않습니다.

## 4. 알려진 한계 (중요)
1. **실제 회사 원화로 검증하지 않았습니다.** 모든 임계값(dpi 100, 픽셀 임계 48, 최소 영역 6px 등)은 합성 자료 기준 제안값입니다.
2. 텍스트 비교는 **PDF 텍스트 레이어**만 대상입니다. 아웃라인·이미지 문자는 시각 후보로만 표시되며 문자 내용은 판정하지 않습니다(OCR 미구현, 기본 OFF).
3. 글꼴 인코딩이 깨진 PDF는 추출 문자가 실제 글자와 다를 수 있습니다. U+FFFD/사용자정의영역 문자가 있으면 `PARTIAL_FONT_ENCODING_SUSPECT` 로 표시하지만, 그 외의 잘못된 매핑(ToUnicode 오류)은 탐지하지 못할 수 있습니다.
4. 시각 비교는 그레이스케일 렌더 기준입니다. **색상·CMYK·별색·오버프린트·재단/도련·바코드 스캔/인쇄 품질은 검사하지 않습니다.** 같은 명도의 색 변경은 놓칠 수 있습니다.
5. 캔버스 이동 보정은 **평행 이동**만 다룹니다. 확대/축소·회전·페이지 크기 변경은 page_map/clip으로 사람이 대응 영역을 정해야 합니다.
6. 이미지 전용 페이지에서 소수점 픽셀 단위의 이동은 재렌더 탐색(0.125px 단위)으로 보정하지만, 잔차가 남으면 `low_contrast_edge_only` 표시와 함께 후보로 남깁니다(제거하지 않음).
7. 요청 대조는 값 문자열 일치(경계 고려) + 범위(page/region/context) 기준입니다. 의미가 같은 다른 표현은 `NOT_REFLECTED` 또는 `HOLD` 로 나올 수 있습니다.
8. 프로세스 격리(`page_isolation: process`)는 매 페이지 새 파이썬 프로세스를 띄우므로 페이지가 많으면 느립니다. 속도가 중요하면 `inline` (대신 한 페이지 오류가 전체에 영향 가능).
9. 네트워크 차단은 프로그램 내부 장치입니다(OS 방화벽 아님).
