# 클로이(Chloe) MVP — n8n + Railway 따라하기 가이드

> 인공지능 비즈니스전략 3조 · 기말 발표용
> 비전공자도 순서대로만 따라 하면 되도록 썼습니다. 막히면 맨 아래 **「막혔을 때」**를 보세요.

---

## 0. 전체 그림 (1분 이해)

```
[발표 화면: 프론트 MVP]  ──요청──▶  [Railway 위의 n8n]  ──▶  [OpenAI(GPT)]
 seoninna.github.io/chloe          Webhook → Code → AI Agent → Code → 응답
         ▲                                                          │
         └──────────────────────── 결과(JSON) ──────────────────────┘
```

- **프론트(MVP)**: 사람들에게 보여주는 웹 화면. 이 폴더의 `index.html`.
- **n8n**: 뒤에서 일하는 자동화/백엔드. 화면에서 버튼을 누르면 n8n이 요청을 받아 AI에게 일을 시키고 결과를 돌려줌.
- **Railway**: n8n을 인터넷에 24시간 켜두는 서버(이미 쓰고 계신 것).

### 폴더 구성 (제출물)

| 파일 | 설명 | 제출 |
|---|---|---|
| `n8n/01_chloe_performance.json` | 퍼포먼스 마케팅 워크플로 (타겟·트렌드·예산·광고문구·KPI) | ✅ n8n 파일 |
| `n8n/02_chloe_influencer.json` | 인플루언서 마케팅 워크플로 (추천·DM·계약초안·브리프) | ✅ n8n 파일 |
| `n8n/03_chloe_report.json` | 성과 분석 워크플로 (지표 계산·진단·예산조정) | ✅ n8n 파일 |
| `prompts/*.md` | 각 워크플로의 시스템/사용자/수정요청 프롬프트 | ✅ 프롬프트 |
| `index.html` | 발표용 프론트 MVP | 시연 |

---

## 1단계. Railway에서 n8n 주소 확인하기 (5분)

1. https://railway.com 로그인 → n8n이 들어있는 **프로젝트** 클릭
2. 보라색/회색 상자 중 **n8n 서비스**(이름에 n8n 또는 Primary) 클릭
3. 위쪽 **Deployments** 탭 → 가장 위 배포가 초록색 **Active / Success** 인지 확인
   - 빨간색(Failed/Crashed)이면 오른쪽 `⋮` → **Redeploy**
4. **Settings** 탭 → 아래로 내려 **Networking → Public Networking** 에 있는 주소를 복사
   - 예: `https://n8n-production-1a2b.up.railway.app`
   - 주소가 없으면 **Generate Domain** 클릭 (포트를 물어보면 `5678`)
   - 👉 이 주소를 메모장에 적어두세요. 이후 **"내 n8n 주소"** 라고 부릅니다.

## 2단계. Railway 환경변수 점검 (5분, 아주 중요)

n8n 서비스 → **Variables** 탭에서 아래 항목이 있는지 확인합니다. 없으면 **+ New Variable** 로 추가.

| 이름 (Name) | 값 (Value) | 왜 필요? |
|---|---|---|
| `WEBHOOK_URL` | `https://내n8n주소/` (끝에 `/` 포함) | 없으면 Webhook 주소가 `localhost`로 나와 외부에서 호출 불가 |
| `N8N_PROTOCOL` | `https` | 위와 동일 |
| `GENERIC_TIMEZONE` | `Asia/Seoul` | 한국 시간 |
| `TZ` | `Asia/Seoul` | 한국 시간 |

- 저장하면 Railway가 **자동 재배포**합니다 (1~3분). 위쪽에 **Deploy** 버튼이 뜨면 눌러주세요.
- ⚠ `N8N_ENCRYPTION_KEY` 는 **절대 바꾸거나 지우지 마세요.** 저장된 API 키를 못 읽게 됩니다.
- ⚠ 프로젝트 안에 **Postgres** 상자(또는 n8n에 **Volume**)가 있는지 확인하세요. 없으면 재배포 때 워크플로가 사라질 수 있습니다. → 불안하면 6단계 Export로 백업해 두세요.

## 3단계. OpenAI API 키 만들기 (5분)

1. https://platform.openai.com → 로그인 → 왼쪽 **Billing** 에서 $5 정도 충전 (gpt-4o-mini는 시연 수백 번에 1~2천원 수준)
2. **API keys** → **Create new secret key** → `sk-...` 로 시작하는 키 복사 (한 번만 보여줌!)
3. 내 n8n 주소로 접속 → 로그인
4. 왼쪽 메뉴 **Credentials**(또는 Overview → Credentials 탭) → **Create credential / Add credential**
5. `OpenAI` 검색 → **OpenAI API** 선택 → API Key 칸에 붙여넣기 → **Save**
   - 초록색 "Connection tested successfully" 가 뜨면 성공

> Gemini(무료 티어)를 쓰고 싶다면: 워크플로에서 `OpenAI Chat Model` 노드를 지우고 `Google Gemini Chat Model` 노드를 AI Agent의 **Chat Model** 구멍에 연결하면 됩니다.

## 4단계. 워크플로 3개 불러오기 (10분)

먼저 이 저장소에서 `n8n` 폴더의 JSON 3개를 내 컴퓨터에 다운로드합니다.
(GitHub에서 파일 클릭 → 오른쪽 위 **Download raw file** 버튼)

각 파일마다 아래를 반복:

1. n8n 홈 → 오른쪽 위 **Create workflow** (또는 `+`)
2. 빈 화면 오른쪽 위 `⋯` 메뉴 → **Import from File...** → `01_chloe_performance.json` 선택
3. 화면에 노드 6~7개가 나타납니다:
   `Webhook → 요청 정리 → AI Agent 클로이 → 결과 검증 → Respond to Webhook` + 아래쪽 `OpenAI Chat Model`, `Calculator`
4. **`OpenAI Chat Model` 노드 더블클릭** → Credential 칸에서 3단계에서 만든 OpenAI 키 선택 → 모델이 `gpt-4o-mini` 인지 확인 → 창 닫기
5. 오른쪽 위 **Save** (Ctrl+S)
6. 02, 03 파일도 똑같이 반복

> 노드에 빨간 느낌표(⚠)가 있으면 대부분 Credential 미선택입니다. 4번을 다시 해주세요.

## 5단계. 켜기(Publish) & 테스트 (5분)

### 5-1. 켜기
각 워크플로 오른쪽 위에서
- 최신 n8n(2.x): **Publish** 버튼 클릭
- 구버전 n8n(1.x): **Inactive → Active** 토글 켜기

켜야만 **운영 URL** `https://내n8n주소/webhook/chloe-...` 이 항상 동작합니다.

### 5-2. 프론트와 연결
1. 프론트 MVP 열기: `https://seoninna.github.io/chloe/` (아래 7단계 후) 또는 `index.html` 파일을 더블클릭해 브라우저로 열기
2. 위쪽 **n8n 연결 설정** 탭
3. 내 n8n 주소 붙여넣기 → 실행 방식 **운영 URL** 선택 → **저장** → **연결 테스트**
4. "✔ 연결 성공" 이 뜨면 끝! 오른쪽 위 배지가 초록색 **n8n 연결됨**으로 바뀝니다.

### 5-3. 실행 기록 보기 (발표 때 보여주면 좋음)
n8n 워크플로 화면 위쪽 **Executions** 탭 → 방금 실행된 기록 클릭 → 노드마다 어떤 데이터가 오갔는지 확인 가능

> **테스트 URL**로 연습하고 싶다면: 워크플로 화면 아래 **Execute workflow** 클릭(대기 상태) → 프론트 설정에서 **테스트 URL** 선택 → 버튼 누르기. 실행이 화면에 실시간으로 그려집니다. 테스트 URL은 한 번 호출되면 꺼지니 매번 Execute를 다시 눌러야 합니다.

## 6단계. 제출용 n8n 파일 만들기

이 폴더의 JSON을 그대로 내도 되지만, 팀에서 수정했다면 최신본을 다시 내보내세요.

1. 워크플로 열기 → 오른쪽 위 `⋯` → **Download** (또는 Export)
2. 다운로드된 `.json` 이 제출용 n8n 파일입니다.
   - API 키는 파일에 들어가지 않으니 안심하세요 (Credential 이름만 들어감).
3. 프롬프트 제출: `prompts/` 폴더의 md 3개 (시스템 프롬프트·사용자 프롬프트·수정 요청 프롬프트·설계 포인트 포함)

## 7단계. 프론트를 인터넷에 올리기 (GitHub Pages)

이 저장소(`seoninna.github.io`)는 이미 GitHub Pages 사이트라서, `chloe` 폴더가 **main 브랜치**에 들어가면 자동으로 공개됩니다.

1. GitHub 저장소 → **Pull requests** → 작업 브랜치(`claude/...`)로 PR 만들기 → **Merge**
2. 1~3분 후 `https://seoninna.github.io/chloe/` 접속
3. 연결 설정은 브라우저마다 저장되므로 **발표용 노트북에서 한 번 더** 5-2를 해주세요.

---

## 발표 시연 시나리오 (추천 5분)

1. **홈**: "대표님의 하루" 문제 → 제품 정보 1번만 입력 → 저니맵 5단계 설명
2. **① 퍼포먼스**: `클로이에게 맡기기` → 위쪽 n8n 노드가 하나씩 켜지는 것 보여주기 → 타겟/트렌드/예산/광고문구 → **수정 요청**("문구를 더 짧게") → 재생성 → **승인**
3. **② 인플루언서**: 후보 추천(적합도 점수는 코드 계산, 수치는 DB 원본) → 첫 DM(대표가 직접 발송) → 계약 초안 → 승인
4. **승인·협업 이력**: 1순위 인플루언서를 "성과 좋음 + 광고 소재 사용 허가" 체크 → **연결 ①②** 설명 (다시 ①/②를 돌리면 반영됨)
5. **③ 성과 분석**: 숫자 입력 → 지표는 코드가 정확히 계산 → ±20% 넘는 예산 변경은 "대표 승인 필요" 표시
6. 홈의 **아낀 시간 / 평균 단축률** → 검증 계획의 "업무 시간 50% 이상 단축" 기준과 연결
7. n8n **Executions** 화면을 띄워 실제 백엔드 흐름 증명

> 🛟 **발표 백업**: 와이파이·Railway가 불안하면 설정에서 **데모 모드**로 바꾸면 n8n 없이도 같은 화면이 나옵니다. 결과 위 배지가 `n8n 실시간` / `데모 결과`로 구분돼서 정직하게 표시됩니다.

---

## 워크플로 설계 요약 (보고서용)

| 단계 | 노드 | 하는 일 |
|---|---|---|
| 입력 | Webhook | 프론트에서 보낸 제품·예산·성과 데이터 받기 (POST, CORS 허용) |
| 자료 조회·정리 | Code | 프롬프트 생성 / 인플루언서 후보 DB에서 적합도 점수 계산 / 성과 지표(CTR·CVR·CPC·CPA·ROAS) 계산 |
| AI Agent | AI Agent + OpenAI Chat Model + Calculator | 분석·글쓰기·진단 (JSON으로 출력) |
| 검증 | Code | 예산 합계 보정, 과장 표현 탐지, DB와 수치 대조, ±20% 예산 규칙 → 대표 승인 플래그 |
| 응답 | Respond to Webhook | 결과를 프론트로 전송 |
| 대표 검토·승인 | 프론트 | 승인 / 수정 요청(피드백을 다시 n8n으로 → 재생성) |
| 저장·다음 단계 | 프론트(브라우저 저장소) | 승인 이력·협업 성과 저장 → 다음 추천/소재에 반영 |

**왜 이렇게 나눴나?** 숫자는 AI가 틀릴 수 있으니 코드가 계산·검증하고(검증 기준 "수치 오류 0건"), AI는 해석·글쓰기를 맡습니다. 최종 결정은 언제나 대표가 합니다.

**확장 아이디어** (발표 Q&A용): 협업 이력을 Google Sheets 노드로 저장, Gmail 노드로 승인된 DM 발송, Meta/네이버 광고 API로 성과 자동 수집, Schedule Trigger로 매일 아침 성과 리포트.

---

## 막혔을 때

| 증상 | 원인 | 해결 |
|---|---|---|
| 연결 테스트 `404` | 워크플로가 안 켜짐 / 경로 오타 | 5-1 Publish(Active) 확인, 테스트 URL이면 Execute workflow 누르기 |
| `500` 오류 | AI 호출 실패 | n8n **Executions**에서 빨간 노드 확인 → 대부분 OpenAI Credential 미선택 또는 크레딧 부족 |
| `Failed to fetch` | 주소 오타·서버 꺼짐·CORS | 주소가 `https://`로 시작하는지, Railway Deployments가 Active인지, Webhook 노드 → Options → **Allowed Origins (CORS)** 가 `*` 인지 |
| Webhook 주소가 `localhost:5678` 로 보임 | `WEBHOOK_URL` 미설정 | 2단계 환경변수 추가 후 재배포 |
| Import 시 "Could not find property option" 등 오류 | n8n 버전이 너무 오래됨 | Railway에서 n8n 이미지 최신으로 Redeploy (먼저 6단계로 백업) |
| AI 원문만 나오고 카드가 안 보임 | AI가 JSON 형식을 어김 | 다시 실행하거나 OpenAI Chat Model의 Temperature를 0.3으로 낮추기 |
| 첫 요청만 아주 느림 | Railway 서버가 잠들어 있었음 | 발표 5분 전에 연결 테스트 한 번 눌러 깨워두기 |
| 재배포 후 워크플로가 사라짐 | 저장소(Postgres/Volume) 없음 | 4단계 다시 Import (JSON이 있으니 금방 복구) |
