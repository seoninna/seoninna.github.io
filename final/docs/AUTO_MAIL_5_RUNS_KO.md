# 자동 결과 메일 5통 받기 (과제 증빙용, 비기밀 자료 전용)

교수님 요건: **n8n이 스스로 실행한(수동 제외) 성공 4회 이상 + 결과 전달.**
아래 순서대로 하면 n8n이 약 1시간 동안 5번 자동 실행되고, 실행마다 결과 메일이 1통씩 옵니다.

> 메일은 Claude가 보내는 것이 아니라 **선인님 PC의 n8n이 선인님 Gmail로** 보냅니다. 그래야 실제 자동 실행 증빙이 됩니다.
> 이 방법은 **합성(가상) 데모 자료** 또는 **회사 파일이 아닌 테스트 자료**에만 쓰세요. 보고서가 메일에 첨부됩니다.

## 준비 (한 번)
`final` 폴더에서 가상환경을 켠 상태로 실행합니다.

1. 데모 자료 + 메일용 설정 만들기 (`홍길동` 자리에 본인 이름)
```bash
python3 demo_synthetic.py --where demo_mail --mail-declared-by 홍길동
```
   `demo_mail/config.demo.json`이 생깁니다. 그 안의 `local_api.token` 값을 복사해 두세요.

2. 터미널 B: 로컬 비교 API 켜기 (창을 켜 둡니다)
```bash
python3 local_api.py --config demo_mail/config.demo.json
```

3. 터미널 A: n8n 켜기 (Node.js 24 이상)
```bash
N8N_DIAGNOSTICS_ENABLED=false N8N_VERSION_NOTIFICATIONS_ENABLED=false N8N_TEMPLATES_ENABLED=false npx n8n
```

4. n8n 화면(`http://localhost:5678`)에서
   - `n8n/FINAL_Local_Workflow.json` Import
   - Credentials → **Header Auth**: Name `X-FINAL-Token`, Value = 1번에서 복사한 토큰 → 노드 03·05·10·11에 선택
   - Credentials → **Gmail OAuth2** 연결 → 노드 08에 선택
   - 노드 **02 Settings**의 `safe_notice_to` = 본인 Gmail 주소
   - 노드 **08 Send result mail (OFF)** 우클릭 → **Activate**(Enable)
   - 오른쪽 위 **Publish**(또는 Active) 켜기

## 5번 자동 실행시키기
터미널 C에서 (11분 간격으로 새 가상 수정본 5개를 저장):
```bash
python3 tools/feed_test_revisions.py --where demo_mail --count 5 --every-min 11
```
- n8n은 10분마다 실행되므로 약 55~65분 동안 메일 5통이 옵니다.
- 이 도구는 `demo_mail/synthetic_artwork` 안에만 씁니다. 다른 폴더(실제 원화)는 거부합니다.
- 노트북이 잠자기에 들어가면 실행이 멈춥니다. 전원 연결·잠자기 끄기를 확인하세요.

## 증빙 남기기
- n8n **Executions** 화면 캡처: Mode가 *Trigger*(자동)인 성공 실행 4회 이상 (수동 Test 실행은 제외)
- Gmail 수신함 캡처: `FINAL? | SET_… | …` 제목 메일 5통, 첨부 보고서 1~2개 열어서 캡처
- `docs/RUN_LOG_TEMPLATE.md`에 실행 ID·시각·메일 수신 여부 기록
- 보고서·발표에는 **"합성(가상) 자료로 수행한 자동 실행"**이라고 표기 (실제 원화 결과처럼 쓰지 않기)

## 끝나면
- n8n에서 Publish 끄기, 터미널 A·B는 Ctrl+C
- 실제 회사 원화를 처리할 때는 `config.local.json`의 `email_detail`을 `SAFE_SUMMARY`(기본)로 두세요. 회사 승인 없이 보고서를 메일로 보내지 마세요.

## 확인된 것 / 안 된 것
- 개발 샌드박스에서 n8n 2.46.5 + 이 워크플로가 1분 주기 자동 실행으로 매번 비교 → 첨부 보고서 생성까지 동작함을 확인 (Gmail 계정이 없어 08 노드는 꺼진 상태 → `LOCAL_ONLY_NOT_SENT`로 정확히 기록됨).
- **실제 Gmail 발송·수신은 아직 아무도 확인하지 않았습니다.** 선인님 PC에서 첫 메일이 오는지 먼저 확인하세요.
