# 검증 결과 — 수행한 것과 하지 않은 것

작성일 2026-11-04. 실행 환경: Claude Code 클라우드 샌드박스(Linux, Python 3.13, PyMuPDF 2.1, numpy 2.5.3).
**모든 테스트는 합성(가상) PDF로만 수행했습니다. 실제 회사 원화·실제 경로는 사용하지 않았고 접근하지도 않았습니다.**

## 검증 수준별 요약

| # | 검증 수준 | 결과 | 비고 |
|---|---|---|---|
| 1 | 정적 검사 (Python 컴파일, JSON 파싱, 워크플로 노드 연결·이름 검증, 자격증명/pinData 없음, active=false) | **통과** | `tools/build_workflows.py` 내장 검증 |
| 2 | 합성 자료 로컬 테스트 (`python -m unittest discover -s tests`) | **38/38 통과** | 아래 목록 |
| 3 | n8n 노드 존재 확인 — 두 워크플로의 33개 노드 type@typeVersion이 n8n 2.46.5에 존재 | **통과** | 샌드박스에 n8n 2.46.5 설치 후 확인 |
| 4 | n8n import — `FINAL_Local_Workflow.json`, `FINAL_B_Approved_Workflow.json` | **통과** (import만) | n8n 2.46.5 CLI `import:workflow` |
| 5 | n8n 실행 (LOCAL 워크플로, 합성 자료, 샌드박스) | **통과** | 1분 주기로 바꾼 **테스트 사본**을 publish → Schedule Trigger 자동 실행 5회(mode=trigger, 모두 success). 1~4회차: 새 합성 수정본 각 1건 비교 → `COMPARED_WITH_LIMITATIONS` → `LOCAL_ONLY_NOT_SENT` 기록. 5회차: 대기 0건으로 정상 종료. n8n 실행 기록에 합성 원화 문구·파일명 없음 확인 |
| 6 | **실제 회사 원화 로컬 테스트** | **미검증** | 사용자가 본인 PC에서 실행해야 함 |
| 7 | **사용자 환경의 n8n 실행** | **미검증** | 위 5번은 샌드박스·테스트 사본(1분 주기, 테스트 토큰). 배포본은 10분 주기 |
| 8 | **메일 발송·수신** (안전 요약 메일, B안 결과 메일) | **미검증** | Gmail 자격증명 없음. 메일 노드는 실행하지 않음 |
| 9 | **자동 실행 4회 (과제 증빙)** | **미검증** | 5번의 샌드박스 자동 실행은 과제 증빙이 아님. 사용자 환경에서 다시 확보 필요 |
| 10 | B안 Gmail·Drive 연동, Railway 배포 | **미검증** | B 비교 서비스 자체는 로컬 HTTP로 합성 PDF 테스트만 통과 |
| 11 | Windows / macOS 실행 | **미검증** | Linux에서만 실행. 경로·권한 처리 코드는 OS 독립적으로 작성 |

## 합성 테스트 목록 (38건, 모두 통과)

| 요구사항 | 테스트 |
|---|---|
| 구조 A/B, 폴더명 설정, 모호한 구조 거부 | `test_layout_a_and_b_supported`, `test_custom_folder_names`, `test_ambiguous_layout_refused` |
| 세트/단품 분리·교차 매칭 차단(후보·수동 add·manifest 변조) | `test_set_and_single_never_cross_matched` |
| 동일 파일명, 다른 코드/용량/국가/포장, 버전 접미사, 중복 후보, 한쪽 없음 | `test_name_rules`, `test_version_suffix_candidate_needs_approval` |
| 요청서 없음 → 변경만, 판정 문구 없음, 안전 요약에 원문 없음, PDF 보고서 생성 | `test_no_requests_reports_changes_only` |
| 문구 정상 변경(REFLECTED), 삭제 미반영(NOT_REFLECTED), 요청 없는 숫자 변경, 유지 항목 원복 의심, BM/디자이너 충돌 | `test_requests_three_way` |
| 같은 단어가 다른 패널에 있음 → 반영으로 세지 않음 | `test_same_word_in_other_panel_is_not_counted` |
| 다른 기준본용 요청서 → 보류 | `test_requests_for_other_baseline_are_held` |
| 아웃라인 숫자의 작은 변경 → 시각 후보, 텍스트는 검수불가 | `test_outlined_digits_small_change_is_visual_candidate` |
| 한쪽만 아웃라인 → '전부 삭제'로 오판하지 않음 | `test_one_side_outlined_text_is_unverifiable_not_deleted` |
| 이미지/혼합 PDF 분류 | `test_image_and_mixed_pdf_profiles` |
| 텍스트 추출 순서 변화 ≠ 내용 변경 | `test_text_order_change_is_not_content_change` |
| 전체 캔버스 이동 vs 실제 로고 이동 (+ 둘 다) | `test_canvas_shift_vs_logo_move` |
| 작은 숫자 변경(2027.11.04→05), 공백만 변경 | `test_small_number_and_whitespace` |
| 페이지 추가·재배열 → page_map 필요 + 제안, 확정 후 비교 | `test_page_added_reordered_resized_and_page_map` |
| 페이지 크기 변경 → page_map 필요 | `test_page_size_change_requires_map` |
| 한 페이지 여러 아트보드 (clip) | `test_multi_artboard_clip_map` |
| 매우 큰 페이지 → 픽셀 상한 내 렌더, 페이지 수 상한 → 미처리 명시 | `test_large_page_is_downscaled_and_page_limit_reported`, `test_pixel_limit_skip_is_reported` |
| 처리 실패·재시도·재개(캐시), 타임아웃(프로세스 격리) | `test_retry_after_failure_and_resume`, `test_interrupted_run_resumes_from_cache`, `test_process_isolation_timeout`, `test_process_isolation_success` |
| 복사 중 파일·임시 파일 | `test_copying_and_temporary_files` |
| 중복 이벤트, 같은 이름 덮어쓰기(해시), 기준본 변경 → 재승인, 발송 기록 분리 | `test_duplicates_overwrite_and_baseline_change` |
| 암호화 PDF | `test_encrypted_and_damaged` |
| 파일명이 결과를 정하지 않음 | `test_file_names_do_not_drive_results` |
| 원본 불변(해시·mtime), 출력 폴더 분리 | `test_source_untouched_and_output_separate` |
| 설정 안전장치(교차매칭·최신자동·외부전송·OCR 켜기 거부 등) | `test_config_guards` |
| 심볼릭 링크 제외 | `test_symlink_source_refused` |
| 콘솔에 파일명·문구·경로·Traceback 없음 | `test_console_output_has_no_sensitive_text` |
| LOCAL_ONLY 외부 접속 차단·루프백 허용 / 외부 통신 라이브러리 import 없음 | `test_network_guard_blocks_external_allows_loopback`, `test_local_code_has_no_outbound_client_imports` |
| 로컬 API: 토큰, 경로 필드 거부, 0.0.0.0 거부, 안전 응답, 중복, 발송 기록 | `test_local_api` |
| B 서비스: 승인 기록·모드 게이트, multipart 비교 | `test_b_config_gates`, `test_b_compare_over_http` |

## 개발 중 발견·수정한 문제 (합성 테스트로 재검증)
1. PyMuPDF가 소수 dpi를 받지 않아 모든 페이지 처리 실패 → 보고서는 올바르게 `UNVERIFIABLE_NOTHING_COMPARED`(‘변경 없음’ 아님)로 표시됨. 확대 행렬 방식으로 수정.
2. 1px 허용오차가 작은 숫자 획 변경(5→6, 33px→4px)을 지움 → 기본 허용오차 0. 캔버스 이동 시에는 PDF 렌더러가 소수점 이동을 직접 그리도록 재렌더링(잔차 1,039px → 0px).
3. 캔버스 이동 + 로고 이동이 함께 있으면 이동 보정이 거부됨 → PDF 텍스트 좌표로 확인된 이동은 별도 기준 적용.
4. 짧은 파일명(예: "토너 KR"/"토너 EN")은 유사도가 낮아 차단 사유가 안 보임 → 코드·용량·국가·포장 단어를 뺀 핵심 이름으로 유사도 계산 후 엄격 비교.
5. 루프백 프록시를 통한 외부 전송 가능성 → LOCAL_ONLY 프로세스에서 프록시 환경변수 제거.

## 샌드박스에서 확인한 n8n 관련 사실
- n8n 2.46.5는 **Node.js 24 이상** 필요 (Node 22에서 실행 거부).
- 텔레메트리 관련 변수를 꺼도 n8n 서버가 `api.n8n.io` 접속을 시도함(샌드박스 프록시가 403 차단).
- "컨테이너 밖 실행은 향후 지원 중단 예정" 경고가 출력됨 — 현재 버전에서는 동작.
