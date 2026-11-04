# FINAL? — 로컬 원화 자동 비교 설치·실행 안내 (비전공자용)

> **Is this really the final version?**
> 원화사에서 받은 수정본(after) PDF를 이전본(before)과 비교해 **무엇이 바뀌었는지**를 근거와 함께 보여 주고,
> 수정 요청서가 있을 때만 **요청이 반영됐는지**를 추가로 대조합니다. 최종 승인과 인쇄 적합성 판단은 사람이 합니다.

이 안내서는 **명령어(복사해서 실행)** 와 **바꿀 값(직접 수정)** 을 구분해서 적었습니다.

---

## 0. 지금 상태 (정직한 현황)

| 항목 | 상태 |
|---|---|
| 비교 프로그램 코드 (사전점검·짝 매칭·텍스트/숫자/시각 비교·보고서) | 작성 완료 |
| 합성(가상) PDF 자동 테스트 38건 | 통과 — `docs/TEST_RESULTS.md` |
| **실제 회사 원화로 실행** | **아직 안 함** (본인 PC에서 직접 실행해야 함) |
| n8n 워크플로 | JSON 작성 완료. 실행 검증 범위는 `docs/TEST_RESULTS.md` 참고 |
| 메일 발송·자동 실행 4회 | **미검증** (본인 환경에서 해야 함) |

> 실제 원화를 아직 아무도 읽지 않았습니다. 따라서 "실제 원화 반영 완료"가 아니라 "**로컬 입력을 받도록 준비됨**" 상태입니다.

---

## 1. 꼭 지킬 것 (보안)

1. 이 프로그램 폴더와 **원화 폴더는 분리**합니다. 원화 PDF를 이 폴더로 옮기지 마세요.
2. `config.local.json`, `output_dir`(결과 폴더)의 파일은 **채팅·메일·Git·ZIP에 올리지 마세요.** Claude에게 보여주지도 마세요.
3. 문제가 생기면 화면에 나온 **오류 코드(`error_code`)와 건수만** 공유하세요.
4. 실제 원화 처리는 **Claude Code가 아닌 별도 터미널**에서 실행합니다. (Claude Code는 외부 AI 모델을 사용합니다.)
5. 자세한 권한·네트워크 설정: `docs/SECURITY_AND_PERMISSIONS_KO.md`

---

## 2. 설치 (처음 한 번)

준비물: Python 3.9 이상 (권장 3.11~3.13). 회사 PC라면 설치 허용 여부를 먼저 확인하세요.

설치에는 인터넷이 필요합니다(패키지 다운로드). **설치는 실제 원화 처리 전에 끝내고**, 실제 처리할 때는 네트워크를 끊거나 차단하는 것을 권장합니다.

### Mac
터미널을 열고, 압축을 푼 `final` 폴더로 이동합니다 (경로는 본인 위치로 바꾸세요).
```bash
cd ~/Documents/FINAL_Ready_To_Setup/final
```
```bash
python3 -m venv .venv
```
```bash
source .venv/bin/activate
```
```bash
pip install -r requirements.txt
```

### Windows (PowerShell)
```powershell
cd C:\Work\FINAL_Ready_To_Setup\final
```
```powershell
py -3 -m venv .venv
```
```powershell
.\.venv\Scripts\Activate.ps1
```
```powershell
pip install -r requirements.txt
```
> 이후 안내의 `python3`은 Windows에서는 `python`으로 입력하세요 (가상환경을 켠 상태).
> 새 터미널을 열 때마다 `source .venv/bin/activate`(Mac) 또는 `.\.venv\Scripts\Activate.ps1`(Windows)을 다시 실행합니다.

### 설치 확인 (원화 폴더에 접근하지 않음)
```bash
python3 local_preflight.py --env-only
```
`"ok": true` 가 나오면 됩니다.

```bash
python3 -m unittest discover -s tests
```
마지막 줄에 `OK` 가 나오면 됩니다.

```bash
python3 demo_synthetic.py --where demo
```
`demo/synthetic_results/reports/…/report.private.html` 을 더블클릭해서 브라우저로 열어 보세요. **가상 자료로 만든 예시 보고서**입니다.

---

## 3. 설정 파일 만들기 — 바꿀 값 3개

```bash
cp config.example.json config.local.json
```
(Windows: `copy config.example.json config.local.json`)

`config.local.json` 을 메모장/텍스트편집기로 열고 **아래 3개 값만** 바꿉니다.

| 바꿀 값 | 예시 (Mac) | 예시 (Windows) | 설명 |
|---|---|---|---|
| `root_dir` | `/Users/내이름/Work/원화` | `C:/Work/원화` | 세트·단품, before·after가 모두 들어 있는 **가장 가까운 공통 상위 폴더** |
| `output_dir` | `/Users/내이름/Work/FINAL_결과` | `C:/Work/FINAL_결과` | 결과 저장 폴더. **원화 폴더 바깥**이어야 함 (안쪽이면 실행 거부) |
| `local_api.token` | 아래 명령으로 만든 긴 문자열 | 동일 | n8n 연결용 비밀번호 (24자 이상) |

- Windows 경로는 `\` 대신 `/` 를 쓰면 JSON 오류를 피할 수 있습니다.
- 토큰 만들기:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```
- 나머지 값(dpi, 픽셀 한도 등)은 처음에는 그대로 두세요. 모든 수치는 **제안값**이며 실제 원화로 검증되지 않았습니다.

### 폴더 구조
아래 두 구조를 자동 인식합니다. 폴더를 옮길 필요 없습니다.
```text
A) 원화/세트/before   원화/세트/after   원화/단품/before   원화/단품/after
B) 원화/before/세트   원화/before/단품   원화/after/세트   원화/after/단품
```
`원화 수정 전 before`, `원화 수정 후 after`, `수정 전`, `수정 후` 같은 이름도 인식합니다.
이름이 전혀 다르면 `groups` 의 `before_dir` / `after_dir` 에 `root_dir` 기준 상대경로를 적습니다.
```json
{"category": "세트", "code": "SET", "folder_names": ["세트"], "before_dir": "세트/원화 수정 전 before", "after_dir": "세트/원화 수정 후 after"}
```
before/after 폴더 안의 하위 폴더(제품별 폴더 등)도 함께 읽습니다.

---

## 4. 사전 점검 (원본은 읽기만 함)
```bash
python3 local_preflight.py --config config.local.json
```
화면에는 **건수와 코드만** 나옵니다. 예:
`{"ok": true, "pdf_files": 12, "by_category_side": {"SET/before": 3, ...}, "content_classes": {"MIXED_TEXT_AND_GRAPHICS": 20, "NO_TEXT_LAYER_OUTLINE_OR_GRAPHICS": 4}, ...}`

- 상세(파일명 포함)는 `output_dir/preflight/preflight.private.json` — 본인만 보세요.
- `NO_TEXT_LAYER_OUTLINE_OR_GRAPHICS` / `IMAGE_ONLY` 가 많으면 글자가 아웃라인·이미지라 **문자 비교가 안 되고 시각 후보만** 나옵니다.
- 파일이 너무 많아 오래 걸리면 `--max-files 5` 로 일부만 열어 보거나 `--no-pdf-open` 으로 목록만 확인할 수 있습니다.

---

## 5. before/after 짝 확인 (사람이 확정)
```bash
python3 pair_resolver.py scan --config config.local.json
```
그다음 `output_dir/pairs/pair_candidates.private.html` 을 브라우저로 엽니다.

- **1. 후보**: 파일명으로 찾은 후보입니다. 같은 원화(코드·용량·구성·포장·국가)가 맞는지 직접 확인한 뒤, 표에 적힌 명령에서 괄호 부분을 바꿔 실행합니다.
```bash
python3 pair_resolver.py approve --config config.local.json --pair-id SET_0123456789 --artwork-id 내가정한ID --by 홍길동
```
  - `--pair-id`: 표의 pair_id 그대로 / `--artwork-id`: 본인이 알아볼 이름(영문·숫자 권장) / `--by`: 확인한 사람
  - 승인 = "이 두 파일을 비교한다"는 확인일 뿐, **원화 최종 승인이 아닙니다.**
- **2. PAIR_NEEDS_CONFIRMATION**: 후보가 여러 개이거나 한쪽이 없음. 자동으로 정하지 않습니다. 맞는 짝을 직접 지정합니다.
```bash
python3 pair_resolver.py add --config config.local.json --category-code SET --before "세트/before/파일A.pdf" --after "세트/after/파일A_수정.pdf"
```
  (경로는 `root_dir` 기준. 세트 before와 단품 after처럼 **다른 구분끼리는 거부**됩니다.) 그다음 위 `approve` 를 실행합니다.
- **페이지 수·순서가 바뀐 경우**: 보고서가 `PAGE_MAP_REQUIRED` 와 제안을 보여 줍니다. 확인 후:
```bash
python3 pair_resolver.py set-page-map --config config.local.json --pair-id SET_0123456789 --map "1:2,2:1,-:3" --by 홍길동
```
  (`before쪽:after쪽`, `-` 는 대응 없음)
- **한 페이지에 아트보드 여러 개**: `pair_manifest.local.json` 의 해당 pair `page_map` 에 `before_clip` / `after_clip` ([x0,y0,x1,y1] pt)을 적습니다. 예시는 `docs/README_VALIDATION.md`.

---

## 6. 실제 파일 한 쌍 비교
```bash
python3 compare_engine.py --config config.local.json --pair-id SET_0123456789
```
- 화면: `"status": "COMPARED"` + 변경 건수 + 상태 코드
- 보고서: `output_dir/reports/<pair_id>/<run_key>/report.private.html` (PDF: `report.private.pdf`)
- 보고서 읽는 법
  - **상태** `COMPARED_WITH_LIMITATIONS`: 대응된 페이지를 모두 비교함 (인쇄 항목 등은 여전히 사람이 확인)
  - `PARTIAL_COVERAGE`: **일부만 비교됨** — 2절의 미처리·검수불가 목록을 원본에서 직접 확인
  - `UNVERIFIABLE_NOTHING_COMPARED`: 비교 못 함. **'변경 없음'이 아닙니다.**
  - 4절 텍스트·숫자 변경: before/after 원문(␣=공백), 좌표, 숫자 변경 표시
  - 5절 시각적 변경 후보: 오버레이(빨강=수정본에만, 청록=이전본에만), 박스, before/after 확대 이미지. **후보일 뿐 오류 확정 아님**
- 같은 파일을 다시 실행하면 `ALREADY_PROCESSED_SAME_CONTENT` (중복 방지). 다시 돌리려면 `--force`.
- 수정본이 같은 이름으로 덮어써지면 내용 해시가 달라져 새 비교로 처리됩니다.
- before 파일 내용이 승인 이후 바뀌면 `BASELINE_CONTENT_CHANGED_SINCE_APPROVAL_REAPPROVE_PAIR` — 다시 approve 하세요.

### (선택) 수정 요청서로 반영 여부 대조
`templates/revision_requests.example.json` 을 복사해 `output_dir/requests/<pair_id>.json` 으로 저장하고 실제 요청만 적습니다.
- BM과 디자이너 요청이 같은 대상을 다르게 바꾸면 `CONFLICT_HOLD` (사람이 결정)
- 요청서가 없으면 반영/미반영을 **판정하지 않습니다.**

---

## 7. n8n 자동화 (LOCAL_ONLY, 내 PC)

**Railway의 n8n은 내 PC 폴더를 읽을 수 없습니다.** 실제 회사 파일 자동화는 내 PC에서 n8n을 실행합니다.
n8n은 파일을 직접 읽지 않고, 로컬 비교 API에 `pair_id`만 보냅니다.

1. **Node.js 24 이상** 설치 (n8n 2.x는 Node 24 이상 필요 — 2026-11-04 n8n 2.46.5로 확인. 회사 허용 확인). 터미널 A에서 n8n 실행 (텔레메트리 끄기 포함):
   - Mac
```bash
N8N_DIAGNOSTICS_ENABLED=false N8N_VERSION_NOTIFICATIONS_ENABLED=false N8N_TEMPLATES_ENABLED=false npx n8n
```
   - Windows (PowerShell)
```powershell
$env:N8N_DIAGNOSTICS_ENABLED="false"; $env:N8N_VERSION_NOTIFICATIONS_ENABLED="false"; $env:N8N_TEMPLATES_ENABLED="false"; npx n8n
```
2. 터미널 B에서 로컬 비교 API 실행 (이 창은 켜 둡니다):
```bash
python3 local_api.py --config config.local.json
```
   `{"ok": true, "listening": "127.0.0.1:8765"}` 가 나오면 됩니다.
3. 브라우저에서 `http://localhost:5678` → 계정 생성 → **Import from File** → `n8n/FINAL_Local_Workflow.json`
4. 자격증명 만들기: **Credentials → New → Header Auth** — Name: `X-FINAL-Token`, Value: config의 `local_api.token`
   → 노드 03·05·10·11 에서 이 자격증명 선택
5. 노드를 한 번 수동 실행(Test)해 보고, 정상이면 **Publish(또는 Active)** 를 켭니다.
6. 이후 원화사 수정본을 after 폴더에 저장하면(저장 완료 후 `stable_seconds`=120초 경과), 10분 이내에 자동 비교됩니다.
   - 복사 중·임시 파일(`~$`, `.part` 등)은 건너뜁니다.

> n8n 자체도 인터넷에 접속을 시도합니다(테스트 중 `api.n8n.io` 접속 시도 확인). 위 환경변수로 줄일 수 있지만 모두 막히지는 않습니다. n8n에는 원화 내용이 들어가지 않도록 설계했지만, 회사 정책상 필요하면 OS·네트워크 차원에서 n8n의 외부 접속을 차단하세요.

> Docker로 n8n을 실행하면 컨테이너 안의 `localhost`는 **컨테이너 자신**입니다. 이 경우 02 Settings의 `api_base` 를 `http://host.docker.internal:8765` 로 바꾸고, `local_api.host` 설정과 방화벽을 따로 검토해야 합니다(`docs/SECURITY_AND_PERMISSIONS_KO.md`). 처음에는 `npx n8n` 방식을 권장합니다. n8n에 원화 폴더를 마운트할 필요는 없습니다(마운트한다면 읽기 전용 `:ro`).

### 결과 전달 (과제 요건과 관계)
- 기본: 결과는 **PC의 로컬 보고서**로만 남습니다. 이것만으로는 과제의 "메일 등 결과 전달" 요건을 **충족했다고 볼 수 없습니다.**
- 선택 1 — **안전 요약 메일** (문구·파일명·경로 없음, pair_id와 건수만): 메일도 외부 전송이므로 **승인 확인 후** ① `config.local.json` 의 `notification.safe_email_enabled: true`, `approval_note`(승인 근거) ② n8n 02 Settings `safe_notice_to` ③ 08 노드 Enable + Gmail 자격증명.
- 선택 2 — **B안 (APPROVED_EXTERNAL_B)**: 외부 처리 허가 자료 또는 **비기밀 재제작 자료**만 Gmail+Drive+비교 서비스로 처리 → `n8n/FINAL_B_Approved_Workflow.json`, `b_service/README_B_KO.md`. 회사 원화를 이 경로로 보내지 마세요.

---

## 8. 기록 남기기 (과제 증빙)
- 실행할 때마다 `docs/RUN_LOG_TEMPLATE.md` (또는 `docs/run_log_template.csv`)에 기록합니다.
- 비교 성공과 메일 수신 성공은 **따로** 기록합니다. 메일 발송 결과를 확인한 뒤:
```bash
python3 compare_engine.py --config config.local.json --record-delivery RUN_KEY --delivery-status RECEIPT_CONFIRMED_BY_USER
```
- 보고서 초안: `docs/REPORT_DRAFT.md`

---

## 9. 자주 나오는 오류 코드

| 코드 | 뜻 | 할 일 |
|---|---|---|
| `CONFIG_FILE_NOT_FOUND` | 설정 파일 없음 | 3장 `cp` 명령 실행, `--config` 경로 확인 |
| `CONFIG_JSON_SYNTAX_ERROR` (line, column) | JSON 문법 오류 | 해당 줄의 쉼표·따옴표·`\` 확인 (`/` 사용 권장) |
| `CONFIGURE_ROOT_AND_OUTPUT_DIRECTORIES` | 경로를 안 바꿈 | `root_dir`, `output_dir` 수정 |
| `ROOT_DIR_NOT_FOUND_OR_NOT_DIRECTORY` | 원화 폴더 경로 틀림/권한 없음 | 경로 확인. Mac은 터미널에 '파일 및 폴더' 접근 권한 허용 필요할 수 있음 |
| `SOURCE_AND_OUTPUT_MUST_BE_SEPARATE` | 결과 폴더가 원화 폴더 안/위 | 별도 위치로 변경 |
| `GROUP_DIRECTORY_NOT_FOUND_SET_BEFORE_DIR_AFTER_DIR` | 세트/단품 before/after 폴더를 못 찾음 | 3장의 `before_dir`/`after_dir` 지정 |
| `GROUP_DIRECTORY_AMBIGUOUS_…` | 후보 폴더가 여러 개 | `before_dir`/`after_dir` 로 명시 |
| `PAIR_NOT_APPROVED_RUN_PAIR_RESOLVER_APPROVE` | 짝 미승인 | 5장 approve |
| `SOURCE_FILE_NOT_IN_EXPECTED_CATEGORY_SIDE_FOLDER` | 세트↔단품 교차 또는 before/after 뒤바뀜 | 짝을 다시 지정 |
| `AFTER_FILE_NOT_STABLE_RECENTLY_MODIFIED` | 방금 저장·복사 중 | 2분 뒤 다시 |
| `PDF_ENCRYPTED_UNVERIFIABLE` | 암호 PDF | 암호 없는 검수용 PDF 요청 |
| `PDF_OPEN_FAILED_DAMAGED_OR_NOT_PDF` | 손상/PDF 아님 | 원화사에 재전달 요청 |
| `BASELINE_CONTENT_CHANGED_SINCE_APPROVAL_REAPPROVE_PAIR` | before 내용이 바뀜 | 확인 후 다시 approve |
| `OUT_OF_MEMORY_LOWER_DPI_OR_PIXELS` | 메모리 부족 | `preview_dpi` 또는 `max_page_pixels` 낮추기 |
| `NETWORK_BLOCKED_LOCAL_ONLY` | 프로그램이 외부 접속을 막음 | 정상 동작. 외부 접속이 필요한 기능은 없음 |
| `LOCAL_API_TOKEN_TOO_SHORT_…` | 토큰 미설정 | 3장 토큰 만들기 |
| `PORT_IN_USE_OR_BIND_FAILED` | 8765 포트 사용 중 | 다른 창의 local_api 종료 또는 `local_api.port` 변경(n8n `api_base`도 함께) |
