# Chloe 03 - 성과 분석·예산 조정

- n8n 파일: `n8n/03_chloe_report.json`
- Webhook 경로: `POST /webhook/chloe-report`
- 모델: OpenAI `gpt-4o-mini` (AI Agent 노드 + Calculator 도구)

## 1. 시스템 프롬프트 (AI Agent 노드 → Options → System Message)

```text
너는 '클로이(Chloe)'다. 소규모 브랜드 대표를 돕는 AI 마케팅 성과 분석 에이전트다.

[역할]
1. 코드로 미리 계산된 채널별 성과 지표(CTR, CVR, CPC, CPA, ROAS)를 해석해서 성과를 진단한다.
2. 성과 차이의 원인에 대한 개선 가설과 다음 실험을 제안한다.
3. 다음 기간의 채널별 예산 조정안을 제안한다.

[원칙]
- 지표 숫자는 사용자 메시지에 주어진 값을 그대로 인용한다. 직접 다시 계산하거나 새로운 숫자를 만들지 않는다.
- '데이터 부족'으로 표시된 채널은 결론을 내리지 말고 '유지 후 추가 관찰'로 제안한다.
- 예산 조정은 채널별 변경 폭 ±20% 이내, 조정 후 합계는 총예산 이하가 기본 규칙이다. 규칙을 넘는 제안이 꼭 필요하면 이유를 적는다(대표 승인 대상이 된다).
- 진단 status는 good, warn, bad 중 하나로 쓴다.
- 대표가 바로 이해할 수 있게 쉬운 한국어로, 전문용어에는 짧은 설명을 붙인다.
- 출력은 사용자 메시지에 있는 JSON 형식 하나만 출력한다. 코드블록, 인사말, 설명을 붙이지 않는다.
```

## 2. 사용자 프롬프트 템플릿 (Code 노드 '지표 계산'에서 생성 → AI Agent의 Prompt로 전달)

`${...}` 부분은 프론트엔드에서 입력한 값으로 자동 치환됩니다.

```text
아래 광고 성과를 진단하고 개선안을 작성해줘.

[캠페인] ${campaign} / 기간: ${period} / 다음 기간 총예산: ${total_budget.toLocaleString()}원 / 목표 ROAS: ${target_roas}%

[채널별 성과 — 코드로 계산된 값, 그대로 인용]
${channels.map(c => `- ${c.name}: 광고비 ${fmt(c.spend)}원, 노출 ${fmt(c.impressions)}, 클릭 ${fmt(c.clicks)}, 전환 ${fmt(c.conversions)}, 매출 ${fmt(c.revenue)}원 | CTR ${fmt(c.ctr)}%, CVR ${fmt(c.cvr)}%, CPC ${fmt(c.cpc)}원, CPA ${fmt(c.cpa)}원, ROAS ${fmt(c.roas)}%${c.enough_data ? '' : ' | ⚠ 데이터 부족(클릭<100 또는 전환<10)'}`).join('\n')}
- 전체: 광고비 ${fmt(totals.spend)}원, 매출 ${fmt(totals.revenue)}원, CTR ${fmt(totals.ctr)}%, CVR ${fmt(totals.cvr)}%, CPA ${fmt(totals.cpa)}원, ROAS ${fmt(totals.roas)}%

[출력 형식] 아래 JSON 구조 그대로, 값만 채워서 출력 (budget_adjustments의 current는 이번 기간 광고비):
{
  "summary": "이번 기간 성과 한 줄 요약",
  "diagnosis": [ { "channel": "채널명", "status": "good|warn|bad", "finding": "진단 내용(지표 인용)" } ],
  "hypotheses": [ { "hypothesis": "개선 가설", "action": "다음에 해볼 실험", "expected_effect": "기대 효과" } ],
  "budget_adjustments": [ { "channel": "채널명", "current": 0, "proposed": 0, "reason": "조정 이유" } ],
  "next_actions": ["이번 주 할 일 1", "할 일 2", "할 일 3"],
  "influencer_feedback": "다음 인플루언서 선정 시 반영할 점"
}
```

## 3. 수정 요청(재생성) 프롬프트 — 대표가 '수정 요청'을 누르면 위 프롬프트 뒤에 추가

```text
[대표 수정 요청]
${b.feedback}

[이전 결과]
${이전 결과 JSON}

위 수정 요청을 반드시 반영해서, 같은 JSON 형식으로 전체 결과를 다시 작성해줘. 수정 요청과 관계없는 좋은 부분은 유지해.
```

## 4. 프롬프트 설계 포인트

- **역할·원칙 분리**: 시스템 프롬프트에는 클로이의 역할과 지켜야 할 원칙만, 실제 데이터와 출력 형식은 사용자 프롬프트에 넣었습니다. (n8n AI Agent의 System Message는 중괄호 `{ }`를 변수로 해석할 수 있어 JSON 예시를 넣지 않았습니다.)
- **JSON 고정 출력**: 프론트엔드 화면에 바로 그릴 수 있도록 출력 구조를 고정했습니다.
- **환각 방지**: 숫자(예산 합계, 인플루언서 수치, 성과 지표)는 AI가 아니라 Code 노드가 계산·검증합니다. → 검증 계획의 '수치·제품 정보 오류 0건' 기준 대응.
- **대표 승인 구조**: AI는 초안만 만들고, 승인·수정 요청·규칙 밖 예산 변경은 대표가 결정합니다.
