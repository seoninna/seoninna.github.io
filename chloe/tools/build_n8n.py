# -*- coding: utf-8 -*-
"""클로이 n8n 워크플로(JSON)와 프롬프트 문서를 만드는 스크립트.
사용법: python3 chloe/tools/build_n8n.py   (engine/influencer-engine.js 를 수정했다면 다시 실행)
"""
import json, os, sys, uuid

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(f"{OUT}/n8n", exist_ok=True)
os.makedirs(f"{OUT}/prompts", exist_ok=True)

def nid():
    return str(uuid.uuid4())

# ---------------------------------------------------------------- common JS
READ_BODY = r"""// 프론트엔드(MVP)가 보낸 요청 본문 읽기
const raw = $input.first().json;
let b = raw.body ?? raw;
if (typeof b === 'string') { try { b = JSON.parse(b); } catch (e) { b = {}; } }
const v = (x, d) => (x === undefined || x === null || x === '' ? d : x);
"""

PARSE_FN = r"""// AI 응답에서 JSON만 안전하게 꺼내기
function parseJson(t) {
  t = String(t || '').replace(/```json/gi, '').replace(/```/g, '');
  const s = t.indexOf('{'), e = t.lastIndexOf('}');
  if (s < 0 || e < 0) throw new Error('JSON not found');
  return JSON.parse(t.slice(s, e + 1));
}
"""

FEEDBACK_JS = r"""
// 대표의 수정 요청이 있으면 이전 결과와 함께 전달 (승인 → 수정 → 재승인 왕복 흐름)
if (b.feedback) {
  prompt += `\n\n[대표 수정 요청]\n${b.feedback}\n\n[이전 결과]\n${JSON.stringify(b.previous || {}).slice(0, 8000)}\n\n위 수정 요청을 반드시 반영해서, 같은 JSON 형식으로 전체 결과를 다시 작성해줘. 수정 요청과 관계없는 좋은 부분은 유지해.`;
}
"""

# ======================================================== 01 PERFORMANCE
PERF_SYSTEM = """너는 '클로이(Chloe)'다. 전담 마케터가 없는 소규모 브랜드 대표를 돕는 AI 퍼포먼스 마케팅 에이전트다.

[역할]
1. 제품 특성에 맞는 마케팅 타겟을 분석하고 트렌드 인사이트를 도출한다.
2. 대표가 정한 예산 안에서 효율적인 매체별 예산 배분안을 제안한다.
3. 매체별 광고 소재(헤드라인, 본문, CTA, 이미지 컨셉)를 만든다.
4. 집행 후 무엇을 보고 언제 조정할지 KPI와 운영 규칙을 정한다.

[원칙]
- 대표가 입력한 제품 정보만 사실로 사용한다. 입력에 없는 효능, 수치, 수상 이력, 인증을 지어내지 않는다.
- '최고', '1위', '100%', '완치', '부작용 없음'처럼 과장되거나 광고 심의에 걸리는 표현을 쓰지 않는다. 검수한 내용은 checklist에 남긴다.
- 매체별 예산 합계는 입력된 총예산과 정확히 같아야 한다.
- 트렌드는 실시간 검색 결과가 아니라 일반적으로 알려진 시장 경향에 근거한 '가설'이다. 그렇게 표현한다.
- 인플루언서 협업 콘텐츠(사용 허가된 것)가 주어지면 광고 소재에 활용하는 안을 최소 1개 포함한다.
- 대표가 바로 실행할 수 있게 구체적이고 짧게, 한국어로 쓴다.
- 출력은 사용자 메시지에 있는 JSON 형식 하나만 출력한다. 코드블록, 인사말, 설명을 붙이지 않는다."""

PERF_SCHEMA = """{
  "summary": "한 줄 전략 요약",
  "target_analysis": {
    "primary_persona": "핵심 타겟 페르소나 설명",
    "secondary_persona": "확장 타겟 페르소나 설명",
    "pain_points": ["타겟의 고민 1", "고민 2", "고민 3"],
    "insights": ["마케팅 인사이트 1", "인사이트 2", "인사이트 3"]
  },
  "trends": [ { "title": "트렌드 이름", "description": "제품과 연결되는 이유와 활용법" } ],
  "budget_plan": [ { "channel": "매체명", "amount": 0, "ratio": 0, "reason": "배분 이유" } ],
  "ad_copies": [ { "channel": "매체명", "headline": "헤드라인", "body": "본문", "cta": "행동 유도 문구", "image_prompt": "이미지/영상 컨셉 설명" } ],
  "kpi_rules": [ { "metric": "지표명(CTR 등)", "target": "목표값", "rule": "이 조건이면 이렇게 조정" } ],
  "checklist": ["표현·규격 검수 결과 1", "검수 결과 2"]
}"""

PERF_PREP = READ_BODY + r"""
const p = {
  product: v(b.product, '이름 미입력 제품'),
  category: v(b.category, '기타'),
  price: Number(v(b.price, 0)),
  features: v(b.features, ''),
  target: v(b.target, ''),
  budget: Number(v(b.budget, 1000000)),
  goal: v(b.goal, '매출 증대'),
  channels: Array.isArray(b.channels) && b.channels.length ? b.channels : ['인스타그램 광고', '네이버 검색광고'],
  tone: v(b.tone, '친근하고 신뢰감 있게'),
  influencer_assets: Array.isArray(b.influencer_assets) ? b.influencer_assets : [],
};

let prompt = `아래 제품의 퍼포먼스 마케팅 계획을 작성해줘.

[제품 정보]
- 제품명: ${p.product}
- 카테고리: ${p.category}
- 판매가: ${p.price.toLocaleString()}원
- 특징: ${p.features}
- 대표가 생각하는 타겟: ${p.target}
- 이번 달 광고 총예산: ${p.budget.toLocaleString()}원 (budget_plan의 amount 합계가 정확히 ${p.budget}이어야 함, ratio는 % 정수)
- 목표: ${p.goal}
- 사용할 매체: ${p.channels.join(', ')} (budget_plan과 ad_copies는 이 매체들만 사용)
- 브랜드 톤: ${p.tone}
- 사용 허가된 인플루언서 콘텐츠: ${p.influencer_assets.length ? p.influencer_assets.join(' / ') : '없음'}

[출력 형식] 아래 JSON 구조 그대로, 값만 채워서 출력:
${SCHEMA}

trends는 3개, ad_copies는 매체별 1개 이상, kpi_rules는 4개 이상, checklist는 3개 이상.`;
""".replace("${SCHEMA}", PERF_SCHEMA.replace("`", "")) + FEEDBACK_JS + r"""
return [{ json: { prompt, request: p, startedAt: Date.now() } }];
"""

PERF_VERIFY = PARSE_FN + r"""
const out = $input.first().json.output;
const req = $('요청 정리').first().json;
let data, checks = [];
try { data = parseJson(out); } catch (e) { data = { raw: String(out || '') }; checks.push({ ok: false, label: 'AI 응답 JSON 변환 실패 → 원문 표시' }); }

// 검증 1: 예산 합계가 총예산과 같은지 확인하고, 다르면 비율대로 자동 보정
if (Array.isArray(data.budget_plan) && data.budget_plan.length) {
  const sum = data.budget_plan.reduce((a, c) => a + Number(c.amount || 0), 0);
  if (sum !== req.request.budget && sum > 0) {
    let acc = 0;
    data.budget_plan.forEach((c, i) => {
      if (i === data.budget_plan.length - 1) c.amount = req.request.budget - acc;
      else { c.amount = Math.round(Number(c.amount) / sum * req.request.budget / 1000) * 1000; acc += c.amount; }
    });
    checks.push({ ok: false, label: `예산 합계 불일치(${sum.toLocaleString()}원) → 총예산에 맞게 자동 보정` });
  } else checks.push({ ok: true, label: '예산 합계 = 총예산 일치' });
  data.budget_plan.forEach(c => { c.ratio = Math.round(Number(c.amount) / req.request.budget * 100); });
}

// 검증 2: 금지/과장 표현 탐지
const banned = ['최고', '1위', '100%', '완치', '부작용 없', '무조건', '기적'];
const text = JSON.stringify(data.ad_copies || []);
const hit = banned.filter(w => text.includes(w));
checks.push(hit.length ? { ok: false, label: `과장 의심 표현 발견: ${hit.join(', ')} → 대표 검토 필요` } : { ok: true, label: '과장·금지 표현 없음' });

return [{ json: { ok: true, type: 'performance', generated_at: new Date().toISOString(), elapsed_ms: Date.now() - req.startedAt, checks, data } }];
"""

# ======================================================== 03 REPORT
REP_SYSTEM = """너는 '클로이(Chloe)'다. 소규모 브랜드 대표를 돕는 AI 마케팅 성과 분석 에이전트다.

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
- 출력은 사용자 메시지에 있는 JSON 형식 하나만 출력한다. 코드블록, 인사말, 설명을 붙이지 않는다."""

REP_SCHEMA = """{
  "summary": "이번 기간 성과 한 줄 요약",
  "diagnosis": [ { "channel": "채널명", "status": "good|warn|bad", "finding": "진단 내용(지표 인용)" } ],
  "hypotheses": [ { "hypothesis": "개선 가설", "action": "다음에 해볼 실험", "expected_effect": "기대 효과" } ],
  "budget_adjustments": [ { "channel": "채널명", "current": 0, "proposed": 0, "reason": "조정 이유" } ],
  "next_actions": ["이번 주 할 일 1", "할 일 2", "할 일 3"],
  "influencer_feedback": "다음 인플루언서 선정 시 반영할 점"
}"""

REP_PREP = READ_BODY + r"""
const r2 = x => (x === null || !isFinite(x)) ? null : Math.round(x * 100) / 100;
const div = (a, c) => (c > 0 ? a / c : null);
const pct = (a, c) => (c > 0 ? a / c * 100 : null);

const channels = (Array.isArray(b.channels) ? b.channels : []).map(c => {
  const spend = Number(c.spend || 0), imp = Number(c.impressions || 0), clk = Number(c.clicks || 0),
        conv = Number(c.conversions || 0), rev = Number(c.revenue || 0);
  return {
    name: c.name || '이름 없는 채널', spend, impressions: imp, clicks: clk, conversions: conv, revenue: rev,
    ctr: r2(pct(clk, imp)), cvr: r2(pct(conv, clk)), cpc: r2(div(spend, clk)),
    cpa: r2(div(spend, conv)), roas: r2(pct(rev, spend)),
    enough_data: clk >= 100 && conv >= 10,
  };
});
const t = channels.reduce((a, c) => ({ spend: a.spend + c.spend, impressions: a.impressions + c.impressions, clicks: a.clicks + c.clicks, conversions: a.conversions + c.conversions, revenue: a.revenue + c.revenue }), { spend: 0, impressions: 0, clicks: 0, conversions: 0, revenue: 0 });
const totals = { ...t, ctr: r2(pct(t.clicks, t.impressions)), cvr: r2(pct(t.conversions, t.clicks)), cpc: r2(div(t.spend, t.clicks)), cpa: r2(div(t.spend, t.conversions)), roas: r2(pct(t.revenue, t.spend)) };
const total_budget = Number(v(b.total_budget, t.spend));
const campaign = v(b.campaign, '이번 캠페인');
const period = v(b.period, '최근 2주');
const target_roas = Number(v(b.target_roas, 300));

const fmt = x => (x === null ? '계산 불가' : x.toLocaleString());
let prompt = `아래 광고 성과를 진단하고 개선안을 작성해줘.

[캠페인] ${campaign} / 기간: ${period} / 다음 기간 총예산: ${total_budget.toLocaleString()}원 / 목표 ROAS: ${target_roas}%

[채널별 성과 — 코드로 계산된 값, 그대로 인용]
${channels.map(c => `- ${c.name}: 광고비 ${fmt(c.spend)}원, 노출 ${fmt(c.impressions)}, 클릭 ${fmt(c.clicks)}, 전환 ${fmt(c.conversions)}, 매출 ${fmt(c.revenue)}원 | CTR ${fmt(c.ctr)}%, CVR ${fmt(c.cvr)}%, CPC ${fmt(c.cpc)}원, CPA ${fmt(c.cpa)}원, ROAS ${fmt(c.roas)}%${c.enough_data ? '' : ' | ⚠ 데이터 부족(클릭<100 또는 전환<10)'}`).join('\n')}
- 전체: 광고비 ${fmt(totals.spend)}원, 매출 ${fmt(totals.revenue)}원, CTR ${fmt(totals.ctr)}%, CVR ${fmt(totals.cvr)}%, CPA ${fmt(totals.cpa)}원, ROAS ${fmt(totals.roas)}%

[출력 형식] 아래 JSON 구조 그대로, 값만 채워서 출력 (budget_adjustments의 current는 이번 기간 광고비):
${SCHEMA}`;
""".replace("${SCHEMA}", REP_SCHEMA) + FEEDBACK_JS + r"""
return [{ json: { prompt, request: { campaign, period, total_budget, target_roas }, metrics: { channels, totals }, startedAt: Date.now() } }];
"""

REP_VERIFY = PARSE_FN + r"""
const out = $input.first().json.output;
const prep = $('지표 계산').first().json;
let data, checks = [];
try { data = parseJson(out); } catch (e) { data = { raw: String(out || '') }; checks.push({ ok: false, label: 'AI 응답 JSON 변환 실패 → 원문 표시' }); }

// 운영 규칙 검사: 변경 폭 ±20%, 합계 ≤ 총예산, 데이터 부족 채널 증액 금지 → 위반 시 '대표 승인 필요'
const LIMIT = 20;
const chMap = Object.fromEntries(prep.metrics.channels.map(c => [c.name, c]));
let sum = 0;
(data.budget_adjustments || []).forEach(a => {
  const cur = Number(a.current || (chMap[a.channel] ? chMap[a.channel].spend : 0));
  const pro = Number(a.proposed || 0);
  a.current = cur; a.proposed = pro; sum += pro;
  a.change_pct = cur > 0 ? Math.round((pro - cur) / cur * 1000) / 10 : null;
  const reasons = [];
  if (a.change_pct !== null && Math.abs(a.change_pct) > LIMIT) reasons.push(`변경 폭 ${a.change_pct}% (규칙 ±${LIMIT}%)`);
  if (chMap[a.channel] && !chMap[a.channel].enough_data && pro > cur) reasons.push('데이터 부족 채널 증액');
  a.needs_approval = reasons.length > 0;
  a.approval_reason = reasons.join(', ');
});
if (sum > prep.request.total_budget) checks.push({ ok: false, label: `조정안 합계 ${sum.toLocaleString()}원 > 총예산 ${prep.request.total_budget.toLocaleString()}원 → 대표 승인 필요` });
else if (sum > 0) checks.push({ ok: true, label: `조정안 합계 ${sum.toLocaleString()}원 ≤ 총예산` });
const need = (data.budget_adjustments || []).filter(a => a.needs_approval).length;
checks.push(need ? { ok: false, label: `규칙 밖 조정 ${need}건 → 대표 승인 후 실행` } : { ok: true, label: '모든 조정이 자동 실행 범위(±20%) 안' });
checks.push({ ok: true, label: '지표는 코드로 계산 (AI 계산 아님)' });

return [{ json: { ok: true, type: 'report', generated_at: new Date().toISOString(), elapsed_ms: Date.now() - prep.startedAt, checks, metrics: prep.metrics, data } }];
"""

# ======================================================== 02 INFLUENCER (v2: 플랫폼별 · 티어별 · 실데이터)
ENGINE_SRC = open(os.path.join(OUT, "engine", "influencer-engine.js"), encoding="utf-8").read()

INF_SYSTEM = """너는 '클로이(Chloe)'다. 전담 마케터가 없는 소규모 브랜드 대표를 돕는 AI 인플루언서 마케팅 에이전트다.

[역할]
1. 코드가 계산한 '예산 티어 전략(메가·매크로·미들·마이크로)'과 '추천 조합'을 대표가 이해하기 쉽게 설명한다.
2. 추천 조합의 인플루언서마다 맡을 역할, 추천 이유, 주의할 점, 제안 조건, 콘텐츠 아이디어를 쓴다.
3. 인스타그램·틱톡·유튜브 플랫폼별 운영 팁을 준다.
4. 1순위 후보에게 대표가 직접 보낼 첫 협업 제안 DM, 표준 양식 기반 계약서 초안, 콘텐츠 브리프를 작성한다.

[원칙]
- 사용자 메시지에 주어진 후보 안에서만 이야기한다. 목록에 없는 인플루언서를 만들어내지 않는다.
- 팔로워, 참여율, 단가, 적합도 같은 숫자는 주어진 값을 그대로 쓰고 새로 계산하거나 바꾸지 않는다. '(추정)' 표시가 있는 단가는 추정이라고 밝힌다.
- 티어 역할을 구분한다: 메가·매크로는 넓은 인지도, 미들은 인지도와 신뢰의 균형, 마이크로는 높은 반응과 진정성 있는 후기.
- 지난 협업 이력과 리스크(허수 팔로워 의심, 광고 비중 과다, 데모용 가상 인물 등)를 판단에 반영하고 숨기지 않는다.
- 첫 DM은 대표 이름으로 보내는 정중하고 짧은 메시지다. 단가를 먼저 깎거나 압박하지 않는다.
- 계약서에는 협업 내용, 일정, 대가와 지급, 콘텐츠 2차 활용(광고 사용 범위와 기간), 광고 표기 의무(#광고, 유료광고 포함 표기), 수정 요청 횟수, 계약 해지, 비밀유지 조항을 포함한다. 법률 자문이 아니라는 점을 note에 적는다.
- 한국어로 쓰고, 출력은 사용자 메시지에 있는 JSON 형식 하나만 출력한다. 코드블록, 인사말, 설명을 붙이지 않는다."""

INF_SCHEMA = """{
  "summary": "추천 전략 한 줄 요약",
  "tier_strategy": "왜 이 티어 조합인지 대표에게 설명 (2~3문장)",
  "portfolio_notes": [ { "handle": "@추천 조합의 핸들 그대로", "role": "이 인플루언서가 맡을 역할", "reason": "추천 이유", "risk": "주의할 점", "suggested_offer": "제안 조건(예: 제품 제공 + 원고료 30만원 + 2차 활용 3개월)", "content_idea": "콘텐츠 아이디어 한 줄" } ],
  "platform_tips": { "인스타그램": "운영 팁", "틱톡": "운영 팁", "유튜브": "운영 팁" },
  "proposal_dm": { "to": "@1순위 핸들", "message": "첫 협업 제안 DM 전문" },
  "contract_draft": { "title": "계약서 제목", "clauses": [ { "title": "제1조 (조항명)", "content": "조항 내용" } ], "note": "유의사항" },
  "content_brief": { "key_messages": ["핵심 메시지"], "dos": ["꼭 해주세요"], "donts": ["피해주세요"], "schedule": "초안 제출·수정·게시 일정" }
}"""

INF_PREP = r"""// ⚙ 설정 ─ 필요한 것만 바꾸세요 ─────────────────────────────
const CONFIG = {
  // 팀이 조사한 인플루언서 DB: 구글 시트 → 파일 → 공유 → 웹에 게시 → CSV 주소
  // (프론트 '설정' 탭에 넣으면 그 주소가 우선 사용됩니다)
  SHEET_CSV_URL: '',
  // 유튜브 실시간 검색용 API 키. 비워두면 Railway 환경변수 YOUTUBE_API_KEY 를 사용합니다.
  // ⚠ 여기에 직접 붙여넣었다면, 제출용으로 워크플로를 내보내기 전에 꼭 지우세요!
  YOUTUBE_API_KEY: '',
  // 시트·유튜브 결과가 하나도 없을 때 데모용 가상 후보를 쓸지
  USE_SAMPLE_WHEN_EMPTY: true,
};
// ─────────────────────────────────────────────────────────────
""" + READ_BODY + r"""
let ytKey = CONFIG.YOUTUBE_API_KEY;
try { if (!ytKey) ytKey = $env.YOUTUBE_API_KEY || ''; } catch (e) { /* n8n이 환경변수 접근을 막은 경우 */ }

const platforms = Array.isArray(b.platforms) && b.platforms.length ? b.platforms : ['인스타그램', '틱톡', '유튜브'];
const p = {
  product: v(b.product, '이름 미입력 제품'),
  category: v(b.category, '뷰티'),
  price: Number(v(b.price, 0)),
  features: v(b.features, ''),
  target: v(b.target, ''),
  keywords: v(b.keywords, ''),
  gender: v(b.gender, '무관'),
  ages: Array.isArray(b.ages) ? b.ages : [],
  budget: Number(v(b.budget, 2000000)),
  goal: v(b.goal, '신제품 인지도 확대'),
  platforms,
  past_collabs: Array.isArray(b.past_collabs) ? b.past_collabs : [],
  feedback: b.feedback || '',
  previous: b.previous || null,
};
return [{ json: {
  request: p,
  sheet_url: v(b.sheet_csv_url, CONFIG.SHEET_CSV_URL),
  use_youtube: platforms.includes('유튜브') && !!ytKey,
  yt_key: ytKey,
  yt_query: v(b.youtube_query, `${(p.keywords.split(/[,\s]+/)[0] || p.category)} 리뷰`),
  use_sample: CONFIG.USE_SAMPLE_WHEN_EMPTY,
  startedAt: Date.now(),
} }];
"""

INF_ENGINE = "// ▼ 추천 엔진 (chloe/engine/influencer-engine.js 와 동일한 코드)\n" + ENGINE_SRC + r"""

// ▼ 후보 모으기: 팀 시트 + 유튜브 API (+ 없으면 가상 샘플)
const prep = $('요청 정리 · 설정').first().json;
const notes = [];
let sheet = [];
try {
  const t = $('인플루언서 시트 불러오기').first().json.data;
  if (typeof t === 'string' && t.includes(',')) sheet = ChloeEngine.parseCsv(t).map(r => ChloeEngine.normalize(r, 'sheet')).filter(Boolean);
} catch (e) {}
if (prep.sheet_url) notes.push(sheet.length ? `팀 시트에서 후보 ${sheet.length}명` : '팀 시트를 읽지 못했어요 (웹에 게시한 CSV 주소인지 확인)');
let yt = [];
try { yt = ChloeEngine.fromYouTube($('유튜브 채널 통계').first().json.items); } catch (e) {}
if (prep.use_youtube) notes.push(yt.length ? `YouTube API에서 채널 ${yt.length}개 ('${prep.yt_query}' 검색)` : 'YouTube 검색 결과 없음 (API 키·할당량 확인)');
let cands = [...sheet, ...yt];
if (!cands.length && prep.use_sample) { cands = ChloeEngine.SAMPLE; notes.push('실데이터가 없어 데모용 가상 후보를 사용했어요'); }

const req = prep.request;
const eng = ChloeEngine.run(req, cands);
const won = n => Number(n).toLocaleString() + '원';
const line = c => `${c.handle} | ${c.platform} | ${c.tier_label} | ${c.name} | 팔로워 ${c.followers.toLocaleString()} | 참여율 ${c.engagement_rate ?? '정보없음'}% | 예상단가 ${won(c.est_cost)}${c.cost_estimated ? '(추정)' : ''} | 적합도 ${c.fit_score}점 | 근거: ${c.reasons.join(', ') || '-'} | 리스크: ${c.risks.join(', ') || '-'} | ${c.note}`;

let prompt = `아래 제품의 인플루언서 협업 계획을 작성해줘.

[제품 정보]
- 제품명: ${req.product} / 카테고리: ${req.category} / 판매가: ${req.price.toLocaleString()}원
- 특징: ${req.features}
- 타겟: ${req.target} (성별: ${req.gender}, 연령: ${req.ages.join(', ') || '무관'})
- 협업 목표: ${req.goal} / 플랫폼: ${req.platforms.join(', ')}

[예산 티어 전략 — 코드 계산]
- 총예산 ${won(eng.tier_mix.budget)} (구간: ${eng.tier_mix.band}) ${eng.tier_mix.adjustment}
${eng.tier_mix.allocations.map(a => `- ${a.tier_label}: ${a.ratio}% = ${won(a.amount)} → ${a.count}명 선정, ${won(a.used)} 사용 ${a.note}`).join('\n')}

[추천 조합 — 코드가 예산 안에서 선택, 총 ${won(eng.portfolio_total)}]
${eng.portfolio.map((c, i) => `${i + 1}. ${line(c)}`).join('\n') || '조건에 맞는 후보 없음'}

[플랫폼별 상위 후보]
${Object.entries(eng.by_platform).map(([pf, list]) => `■ ${pf}\n` + (list.map(line).join('\n') || '후보 없음')).join('\n')}

[지난 협업 이력]
${req.past_collabs.length ? req.past_collabs.map(c => `${c.handle}: ${c.result === 'good' ? '성과 좋음' : '성과 아쉬움'} ${c.memo || ''}`).join('\n') : '없음'}

[출력 형식] 아래 JSON 구조 그대로, 값만 채워서 출력:
${SCHEMA}

portfolio_notes는 추천 조합 인원 모두(핸들 그대로), platform_tips는 위 플랫폼만, contract_draft.clauses는 8개 이상. 1순위는 추천 조합 1번.`;
""".replace("${SCHEMA}", INF_SCHEMA) + FEEDBACK_JS.replace("b.feedback", "req.feedback").replace("b.previous", "req.previous") + r"""
return [{ json: { prompt, engine: eng, notes } }];
"""

INF_VERIFY = PARSE_FN + r"""
const out = $input.first().json.output;
const prep = $('요청 정리 · 설정').first().json;
const src = $('후보 통합 · 티어 · 적합도 계산').first().json;
const eng = src.engine;
let data, checks = [];
try { data = parseJson(out); } catch (e) { data = { raw: String(out || '') }; checks.push({ ok: false, label: 'AI 응답 JSON 변환 실패 → 원문 표시' }); }

// AI 설명을 코드가 고른 추천 조합에 붙이기. 목록에 없는 핸들은 버림 (숫자는 항상 엔진 값)
const notes = Array.isArray(data.portfolio_notes) ? data.portfolio_notes : [];
const key = h => String(h || '').toLowerCase();
const inPf = new Set(eng.portfolio.map(c => key(c.handle)));
const invented = notes.filter(n => !inPf.has(key(n.handle))).map(n => n.handle);
eng.portfolio = eng.portfolio.map(c => {
  const n = notes.find(x => key(x.handle) === key(c.handle)) || {};
  return { ...c, role: n.role || '', ai_reason: n.reason || c.reasons.join(', '), ai_risk: n.risk || c.risks.join(', '), suggested_offer: n.suggested_offer || '', content_idea: n.content_idea || '' };
});
delete data.portfolio_notes;
checks.push(invented.length ? { ok: false, label: `추천 조합에 없는 후보 언급 제거: ${invented.join(', ')}` } : { ok: true, label: '추천 인원 전원 엔진 결과와 일치, 수치는 원본 데이터 사용' });
checks.push(eng.portfolio_total <= prep.request.budget
  ? { ok: true, label: `추천 조합 ${eng.portfolio.length}명 · 합계 ${eng.portfolio_total.toLocaleString()}원 ≤ 예산 ${prep.request.budget.toLocaleString()}원` }
  : { ok: false, label: '추천 조합 합계가 예산 초과' });
const est = eng.portfolio.filter(c => c.cost_estimated).length;
if (est) checks.push({ ok: false, label: `${est}명은 단가 미입력 → 팔로워 기준 추정 단가 (실제 견적 확인 필요)` });
const s = eng.sources || {};
checks.push({ ok: !s.sample, label: `데이터 출처: 팀 시트 ${s.sheet || 0} · YouTube API ${s.youtube || 0} · 가상 샘플 ${s.sample || 0}` });

return [{ json: { ok: true, type: 'influencer', generated_at: new Date().toISOString(), elapsed_ms: Date.now() - prep.startedAt, checks, data_notes: src.notes, engine: eng, data } }];
"""

# ======================================================== 04 CREATIVE (프롬프트 → 매체 소재)
CRE_FORMATS_JS = r"""const FORMATS = {
  instagram_feed:  { label: '인스타그램 피드',        ratio: '1:1',    size: '1024x1024', h: 25, b: 125, visual: true },
  instagram_story: { label: '인스타그램 스토리·릴스', ratio: '9:16',   size: '1024x1536', h: 20, b: 40,  visual: true },
  youtube_shorts:  { label: '유튜브 숏츠',            ratio: '9:16',   size: '1024x1536', h: 20, b: 60,  visual: true },
  tiktok:          { label: '틱톡',                   ratio: '9:16',   size: '1024x1536', h: 20, b: 60,  visual: true },
  kakao_bizboard:  { label: '카카오 비즈보드',        ratio: '배너',   size: '1536x1024', h: 20, b: 25,  visual: true },
  naver_search:    { label: '네이버 검색광고',        ratio: '텍스트', size: null,        h: 15, b: 45,  visual: false },
};
"""

CRE_SYSTEM = """너는 '클로이(Chloe)'다. 소규모 브랜드 대표의 요청을 받아 매체별 광고 소재를 만드는 AI 카피라이터 겸 아트 디렉터다.

[역할]
1. 대표가 자유롭게 적은 요청(프롬프트)에서 의도, 타겟, 분위기를 읽어 하나의 크리에이티브 컨셉으로 정리한다.
2. 요청된 매체 규격마다 A/B/C 테스트용 카피 3안(헤드라인, 본문, CTA)을 만든다.
3. 이미지가 필요한 매체마다 이미지 생성 AI에 넣을 영어 프롬프트를 쓴다.

[원칙]
- 대표가 입력한 제품 정보만 사실로 사용한다. 없는 효능, 수치, 수상, 인증을 지어내지 않는다.
- '최고', '1위', '100%', '완치', '부작용 없음' 같은 과장·금지 표현을 쓰지 않는다. 화장품·식품은 의약품으로 오인될 표현(치료, 재생, 질병 예방)을 쓰지 않는다.
- 매체별 글자 수 제한을 반드시 지킨다. 3안은 서로 다른 소구점(예: 문제 공감, 성분·근거, 사용 장면)으로 만든다.
- 이미지 프롬프트는 영어로 쓰고, 이미지 안에 글자·로고·워터마크를 넣지 않도록 한다(카피는 나중에 화면에서 얹는다). 카피가 들어갈 여백을 남기도록 구도를 지정한다.
- 대표의 요청과 브랜드 톤이 다르면 대표의 요청을 우선하되 원칙은 지킨다.
- 한국어로 쓰고(이미지 프롬프트만 영어), 출력은 사용자 메시지에 있는 JSON 형식 하나만 출력한다. 코드블록, 인사말, 설명을 붙이지 않는다."""

CRE_SCHEMA = """{
  "concept": "크리에이티브 컨셉 이름",
  "key_message": "핵심 메시지 한 줄",
  "creatives": [ {
    "format": "포맷 키 그대로",
    "variants": [ { "angle": "소구점", "headline": "헤드라인", "body": "본문", "cta": "CTA" } ],
    "visual": { "description_ko": "이미지 설명(한국어)", "image_prompt_en": "English prompt for the image model", "text_color": "light 또는 dark (이미지 위 글자색)" },
    "hashtags": ["#해시태그"]
  } ],
  "checklist": ["표현·규격 검수 결과"]
}"""

CRE_PREP = r"""// ⚙ 설정 ─────────────────────────────────────────────────────
const CONFIG = {
  IMAGE_MODEL: 'gpt-image-1',   // 더 저렴: 'gpt-image-1-mini' / 조직 인증이 어려우면: 'dall-e-3'
  IMAGE_QUALITY: 'low',         // low(빠르고 저렴) · medium · high  (프론트에서 보내면 그 값 사용)
  // 이미지 생성 방식: 'auto' = OpenAI 먼저, 실패한 이미지는 무료 서비스로 대체
  //                  'openai' = OpenAI만 / 'free' = 무료 서비스만 (OpenAI 이미지 권한이 없을 때)
  IMAGE_PROVIDER: 'auto',
  // 무료 이미지 서비스 주소 ({prompt} {width} {height} {seed} 자리에 값이 들어감)
  FREE_IMAGE_URL: 'https://image.pollinations.ai/prompt/{prompt}?width={width}&height={height}&seed={seed}&nologo=true&model=flux',
};
// ─────────────────────────────────────────────────────────────
""" + READ_BODY + CRE_FORMATS_JS + r"""
const formats = (Array.isArray(b.formats) && b.formats.length ? b.formats : ['instagram_feed', 'instagram_story', 'naver_search']).filter(f => FORMATS[f]);
const p = {
  product: v(b.product, '이름 미입력 제품'),
  category: v(b.category, '기타'),
  price: Number(v(b.price, 0)),
  features: v(b.features, ''),
  target: v(b.target, ''),
  tone: v(b.tone, '친근하고 신뢰감 있게'),
  request: v(b.prompt, '제품의 핵심 장점을 보여주는 광고를 만들어줘'),
  formats,
  make_image: b.make_image !== false,
  has_product_photo: !!b.has_product_photo,
  look: v(b.look, ''),
  quality: v(b.quality, CONFIG.IMAGE_QUALITY),
};

let prompt = `대표님의 요청으로 매체별 광고 소재를 만들어줘.

[대표님 요청 (프롬프트)]
${p.request}

[제품 정보]
- 제품명: ${p.product} / 카테고리: ${p.category} / 판매가: ${p.price.toLocaleString()}원
- 특징: ${p.features}
- 타겟: ${p.target}
- 브랜드 톤: ${p.tone}
- 이미지용 제품 묘사(영어): ${p.look || '없음 → 특징을 보고 제품 종류와 용기 모양을 영어로 구체적으로 묘사'}

[만들 매체 규격 — 글자 수 제한 엄수, 공백 포함]
${formats.map(f => `- ${f} (${FORMATS[f].label}, ${FORMATS[f].ratio}): 헤드라인 ${FORMATS[f].h}자 이내, 본문 ${FORMATS[f].b}자 이내${FORMATS[f].visual ? '' : ', 이미지 없음 → visual은 null'}`).join('\n')}

[이미지 프롬프트 규칙]
- 광고용 사진 스타일, 이미지 안에 글자·로고·워터마크 금지
- 제품 종류(예: 수분크림이면 moisturizing cream jar)와 용기 모양, 제형을 영어로 구체적으로 쓰고, 대표님 요청의 장면·분위기를 영어로 옮길 것 (이미지 AI는 한국어를 잘 이해하지 못함)
- ${p.has_product_photo ? '대표님이 실제 제품 사진을 따로 합성할 예정: 제품 용기는 그리지 말고, 아래쪽 가운데에 제품을 놓을 깨끗한 빈 공간(받침대, 테이블 등)을 남길 것' : '제품은 위의 이미지용 제품 묘사대로, 라벨 없는 무지 용기로 화면 아래쪽 가운데에 크게 표현'}
- 9:16은 위쪽 1/3, 1:1과 배너는 왼쪽 또는 위쪽에 카피용 여백

[출력 형식] 아래 JSON 구조 그대로, 값만 채워서 출력:
${SCHEMA}

creatives는 위 매체 규격마다 1개씩(format 키 그대로), variants는 각 3안, checklist는 3개 이상.`;
""".replace("${SCHEMA}", CRE_SCHEMA) + FEEDBACK_JS + r"""
return [{ json: { prompt, request: p, config: CONFIG, startedAt: Date.now() } }];
"""

CRE_VERIFY = PARSE_FN + CRE_FORMATS_JS + r"""
const out = $input.first().json.output;
const prep = $('요청 정리 · 설정').first().json;
const req = prep.request, CONFIG = prep.config;
let data, checks = [];
try { data = parseJson(out); } catch (e) { data = { raw: String(out || ''), creatives: [] }; checks.push({ ok: false, label: 'AI 응답 JSON 변환 실패 → 원문 표시' }); }
data.creatives = (data.creatives || []).filter(c => FORMATS[c.format]);

// 검증 1: 매체별 글자 수
let over = 0;
data.creatives.forEach(c => (c.variants || []).forEach(v => {
  const f = FORMATS[c.format];
  v.headline_len = [...String(v.headline || '')].length; v.body_len = [...String(v.body || '')].length;
  v.over = v.headline_len > f.h || v.body_len > f.b; if (v.over) over++;
}));
checks.push(over ? { ok: false, label: `글자 수 초과 ${over}안 → 화면에서 빨간색 표시, 수정 요청 권장` } : { ok: true, label: '모든 카피가 매체별 글자 수 제한 이내' });
// 검증 2: 과장·금지 표현
const banned = ['최고', '1위', '100%', '완치', '부작용 없', '무조건', '기적', '치료', '재생'];
const hit = banned.filter(w => JSON.stringify(data.creatives).includes(w));
checks.push(hit.length ? { ok: false, label: `과장·금지 의심 표현: ${hit.join(', ')} → 대표 검토 필요` } : { ok: true, label: '과장·금지 표현 없음' });
const missing = req.formats.filter(f => !data.creatives.find(c => c.format === f));
if (missing.length) checks.push({ ok: false, label: `AI가 빠뜨린 규격: ${missing.join(', ')}` });

// 이미지 생성 요청 만들기 (매체 1개당 이미지 1장)
const items = [];
if (req.make_image) data.creatives.forEach(c => {
  const f = FORMATS[c.format];
  if (!f.visual || !c.visual || !c.visual.image_prompt_en) return;
  const m = CONFIG.IMAGE_MODEL;
  const CAT_EN = { '뷰티': 'skincare and beauty', '푸드': 'food and wellness', '패션': 'fashion', '리빙': 'home and living', '테크': 'consumer tech' };
  const promptEn = `Advertising photograph for a ${CAT_EN[req.category] || 'lifestyle'} brand. ${c.visual.image_prompt_en} High quality, natural light, no text, no letters, no logos, no watermark.`;
  const dalle = m.startsWith('dall-e');
  const size = dalle ? ({ '1024x1536': '1024x1792', '1536x1024': '1792x1024' }[f.size] || '1024x1024') : f.size;
  const image_request = dalle
    ? { model: m, prompt: promptEn, n: 1, size, response_format: 'b64_json' }
    : { model: m, prompt: promptEn, n: 1, size, quality: req.quality, output_format: 'jpeg', output_compression: 80 };
  const [fw, fh] = ({ '1024x1024': [1024, 1024], '1024x1536': [864, 1536], '1536x1024': [1536, 640] })[f.size] || [1024, 1024];
  const free_url = CONFIG.FREE_IMAGE_URL.replace('{prompt}', encodeURIComponent(promptEn.slice(0, 900)))
    .replace('{width}', fw).replace('{height}', fh).replace('{seed}', Math.floor(Math.random() * 1e6));
  items.push({ json: { format: c.format, mime: dalle ? 'image/png' : 'image/jpeg', image_request,
    use_openai: CONFIG.IMAGE_PROVIDER !== 'free', use_free: CONFIG.IMAGE_PROVIDER !== 'openai', free_url } });
});
// 이미지가 없어도 다음 노드가 실행되도록 빈 항목 1개 (요청은 실패 처리되고 무시됨)
if (!items.length) items.push({ json: { skip: true, use_openai: false, use_free: false, image_request: {} } });
items[0].json.result = data; items[0].json.checks = checks;
return items;
"""

CRE_MERGE = r"""// 이미지 생성 결과를 소재에 붙이기 (요청 순서 = 응답 순서)
const reqItems = $('소재 검증 · 이미지 요청 준비').all();
const res = $('이미지 생성 (OpenAI)').all();   // OpenAI 결과
const free = $input.all();                      // 무료 서비스 결과 (바이너리)
const prep = $('요청 정리 · 설정').first().json;
const first = reqItems[0].json;
const data = first.result, checks = first.checks || [];
const images = {}, errors = [], via = {};
for (let i = 0; i < reqItems.length; i++) { const it = reqItems[i]; await (async () => {
  if (it.json.skip) return;
  const r = (res[i] && res[i].json) || {};
  const d = Array.isArray(r.data) ? r.data[0] : null;
  if (d && d.b64_json) { images[it.json.format] = `data:${it.json.mime};base64,${d.b64_json}`; return; }
  // OpenAI 실패/미사용 → 무료 서비스 이미지 확인
  const fi = free[i];
  if (it.json.use_free && fi && fi.binary && fi.binary.data) {
    let b64 = null;
    try { b64 = (await this.helpers.getBinaryDataBuffer(i, 'data')).toString('base64'); } catch (e) { b64 = fi.binary.data.data || null; }
    if (b64 && b64.length > 1000) { images[it.json.format] = `data:${fi.binary.data.mimeType || 'image/jpeg'};base64,${b64}`; via[it.json.format] = 'free'; return; }
  }
  {
    let msg = r.error ? (r.error.message || r.error.description || JSON.stringify(r.error)) : '이미지 없음';
    msg = String(msg).slice(0, 240);
    if (/verif/i.test(msg)) msg += ' → OpenAI 조직 인증이 필요해요. 설정에서 IMAGE_MODEL을 dall-e-3로 바꾸거나 인증을 진행하세요.';
    if (it.json.use_free) msg += ' / 무료 이미지 서비스도 실패';
    errors.push(`${it.json.format}: ${msg}`);
  }
})(); }
(data.creatives || []).forEach(c => { c.image = images[c.format] || null; c.image_source = images[c.format] ? (via[c.format] === 'free' ? 'free' : 'openai') : null; });
const want = reqItems.filter(it => !it.json.skip).length;
if (want) checks.push(errors.length ? { ok: false, label: `이미지 ${want - errors.length}/${want}장 생성 (실패분은 기본 배경 사용)` } : { ok: true, label: `AI 이미지 ${want}장 생성 완료 (OpenAI ${want - Object.keys(via).length}장 · 무료 서비스 ${Object.keys(via).length}장)` });
return [{ json: { ok: true, type: 'creative', generated_at: new Date().toISOString(), elapsed_ms: Date.now() - prep.startedAt, checks, image_errors: errors, data } }];
"""


# ---------------------------------------------------------------- builder
WH = "Webhook (프론트 요청 받기)"
AG = "AI Agent 클로이"
RS = "Respond to Webhook (결과 보내기)"
CONT = {"onError": "continueRegularOutput", "alwaysOutputData": True}

def code(js):
    return ("n8n-nodes-base.code", 2, {"jsCode": js}, {})

def http(params, extra=None):
    return ("n8n-nodes-base.httpRequest", 4.2, params, extra or {})

def agent(system):
    return ("@n8n/n8n-nodes-langchain.agent", 1.7,
            {"promptType": "define", "text": "={{ $json.prompt }}", "options": {"systemMessage": system, "maxIterations": 5}}, {})

def build(fname, name, path, steps, temperature, note):
    """steps: [(node_name, (type, version, params, extra))...] — Webhook 다음부터 Respond 전까지 순서대로"""
    seed = lambda s: str(uuid.uuid5(uuid.NAMESPACE_URL, f"chloe/{fname}/{s}"))
    chain = [(WH, ("n8n-nodes-base.webhook", 2, {"httpMethod": "POST", "path": path, "responseMode": "responseNode",
                                                 "options": {"allowedOrigins": "*"}}, {"webhookId": seed("webhook-id")}))]
    chain += steps
    chain += [(RS, ("n8n-nodes-base.respondToWebhook", 1.1,
                    {"respondWith": "json", "responseBody": "={{ JSON.stringify($json) }}", "options": {}}, {}))]
    nodes, conn = [], {}
    width = 240 * len(chain)
    nodes.append({"id": seed("note"), "name": "설명", "type": "n8n-nodes-base.stickyNote", "typeVersion": 1,
                  "position": [-60, -300], "parameters": {"width": max(1240, width), "height": 240, "content": note}})
    agent_x = 0
    for i, (nm, (t, ver, params, extra)) in enumerate(chain):
        x = i * 240
        if nm == AG: agent_x = x
        n = {"id": seed(nm), "name": nm, "type": t, "typeVersion": ver, "position": [x, 0], "parameters": params}
        n.update(extra)
        nodes.append(n)
        if i + 1 < len(chain):
            conn[nm] = {"main": [[{"node": chain[i + 1][0], "type": "main", "index": 0}]]}
    nodes.append({"id": seed("model"), "name": "OpenAI Chat Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
                  "typeVersion": 1.2, "position": [agent_x - 80, 240],
                  "parameters": {"model": {"__rl": True, "value": "gpt-4o-mini", "mode": "list", "cachedResultName": "gpt-4o-mini"},
                                 "options": {"temperature": temperature, "maxTokens": 6000}}})
    nodes.append({"id": seed("calc"), "name": "Calculator", "type": "@n8n/n8n-nodes-langchain.toolCalculator",
                  "typeVersion": 1, "position": [agent_x + 140, 240], "parameters": {}})
    conn["OpenAI Chat Model"] = {"ai_languageModel": [[{"node": AG, "type": "ai_languageModel", "index": 0}]]}
    conn["Calculator"] = {"ai_tool": [[{"node": AG, "type": "ai_tool", "index": 0}]]}
    return {"name": name, "nodes": nodes, "connections": conn, "pinData": {},
            "settings": {"executionOrder": "v1"}, "active": False, "meta": {"templateCredsSetupCompleted": False}, "tags": []}

PREP_SHEET = "인플루언서 시트 불러오기"
YT_SEARCH = "유튜브 채널 검색"
YT_STATS = "유튜브 채널 통계"
P2 = "$('요청 정리 · 설정').first().json"

FLOWS = [
    dict(fname="01_chloe_performance", name="Chloe 01 - 퍼포먼스 마케팅 (타겟·트렌드·광고소재)", path="chloe-performance", temp=0.7,
         system=PERF_SYSTEM, prompt_code=PERF_PREP, prompt_node="요청 정리",
         steps=[("요청 정리", code(PERF_PREP)), (AG, agent(PERF_SYSTEM)), ("결과 검증", code(PERF_VERIFY))],
         note="## Chloe 01 · 퍼포먼스 마케팅\n프론트 → **Webhook** → 요청 정리(프롬프트 생성) → **AI Agent 클로이**(타겟·트렌드·예산·광고문구·KPI) → 결과 검증(예산 합계 보정, 과장표현 탐지) → 프론트로 응답\n\n⚠ 처음 한 번: `OpenAI Chat Model` 노드를 열어 Credential(OpenAI API 키)을 선택하세요."),
    dict(fname="02_chloe_influencer", name="Chloe 02 - 인플루언서 마케팅 (플랫폼별·티어별 추천)", path="chloe-influencer", temp=0.6,
         system=INF_SYSTEM, prompt_code=INF_ENGINE, prompt_node="후보 통합 · 티어 · 적합도 계산",
         steps=[
             ("요청 정리 · 설정", code(INF_PREP)),
             (PREP_SHEET, http({"url": "={{ $json.sheet_url || 'https://example.invalid/no-sheet' }}",
                                "options": {"timeout": 20000, "response": {"response": {"responseFormat": "text", "outputPropertyName": "data"}}}}, CONT)),
             (YT_SEARCH, http({"url": "https://www.googleapis.com/youtube/v3/search", "sendQuery": True,
                               "queryParameters": {"parameters": [
                                   {"name": "part", "value": "snippet"}, {"name": "type", "value": "channel"},
                                   {"name": "maxResults", "value": "25"}, {"name": "regionCode", "value": "KR"},
                                   {"name": "relevanceLanguage", "value": "ko"},
                                   {"name": "q", "value": "={{ " + P2 + ".yt_query }}"},
                                   {"name": "key", "value": "={{ " + P2 + ".use_youtube ? " + P2 + ".yt_key : 'NO_KEY' }}"}]},
                               "options": {"timeout": 20000}}, CONT)),
             (YT_STATS, http({"url": "https://www.googleapis.com/youtube/v3/channels", "sendQuery": True,
                              "queryParameters": {"parameters": [
                                  {"name": "part", "value": "snippet,statistics"},
                                  {"name": "id", "value": "={{ ($json.items || []).map(i => (i.id && i.id.channelId) || (i.snippet && i.snippet.channelId)).filter(Boolean).join(',') }}"},
                                  {"name": "key", "value": "={{ " + P2 + ".use_youtube ? " + P2 + ".yt_key : 'NO_KEY' }}"}]},
                              "options": {"timeout": 20000}}, CONT)),
             ("후보 통합 · 티어 · 적합도 계산", code(INF_ENGINE)),
             (AG, agent(INF_SYSTEM)),
             ("결과 검증", code(INF_VERIFY))],
         note="## Chloe 02 · 인플루언서 마케팅 (플랫폼별·티어별)\n프론트 → **Webhook** → 요청 정리·설정 → 팀 인플루언서 시트(CSV) 불러오기 → 유튜브 채널 검색·통계(YouTube API) → **후보 통합·티어·적합도 계산**(메가/매크로/미들/마이크로, 100점 점수, 예산 맞춤 조합) → **AI Agent 클로이**(역할·이유·DM·계약서) → 결과 검증 → 응답\n\n시트·유튜브는 설정이 없으면 자동으로 건너뜁니다(주황색 경고는 정상). 둘 다 없으면 데모용 가상 후보를 씁니다.\n설정: `요청 정리 · 설정` 노드 맨 위 CONFIG"),
    dict(fname="03_chloe_report", name="Chloe 03 - 성과 분석·예산 조정", path="chloe-report", temp=0.4,
         system=REP_SYSTEM, prompt_code=REP_PREP, prompt_node="지표 계산",
         steps=[("지표 계산", code(REP_PREP)), (AG, agent(REP_SYSTEM)), ("결과 검증", code(REP_VERIFY))],
         note="## Chloe 03 · 성과 분석\n프론트 → **Webhook** → 지표 계산(CTR·CVR·CPC·CPA·ROAS를 코드로 정확히 계산) → **AI Agent 클로이**(진단·개선 가설·예산 조정안) → 결과 검증(±20% 규칙 밖이면 '대표 승인 필요') → 응답"),
    dict(fname="04_chloe_creative", name="Chloe 04 - 광고 소재 스튜디오 (프롬프트 → 매체 소재)", path="chloe-creative", temp=0.9,
         system=CRE_SYSTEM, prompt_code=CRE_PREP, prompt_node="요청 정리 · 설정",
         steps=[
             ("요청 정리 · 설정", code(CRE_PREP)),
             (AG, agent(CRE_SYSTEM)),
             ("소재 검증 · 이미지 요청 준비", code(CRE_VERIFY)),
             ("이미지 생성 (OpenAI)", http({"method": "POST", "url": "={{ $json.use_openai ? 'https://api.openai.com/v1/images/generations' : 'https://example.invalid/skip-openai' }}",
                                           "authentication": "predefinedCredentialType", "nodeCredentialType": "openAiApi",
                                           "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json.image_request) }}",
                                           "options": {"timeout": 180000}}, CONT)),
             ("무료 이미지 생성 (예비)", http({"url": "={{ (() => { const r = $('소재 검증 · 이미지 요청 준비').all()[$itemIndex].json; const ok = $json.data && $json.data[0] && $json.data[0].b64_json; return (r.use_free && !ok) ? r.free_url : 'https://example.invalid/skip-free'; })() }}",
                                       "options": {"timeout": 120000, "response": {"response": {"responseFormat": "file", "outputPropertyName": "data"}}}}, CONT)),
             ("결과 합치기", code(CRE_MERGE))],
         note="## Chloe 04 · 광고 소재 스튜디오\n프론트(대표 프롬프트) → **Webhook** → 요청 정리·설정 → **AI Agent 클로이**(컨셉·매체별 카피 3안·이미지 프롬프트) → 소재 검증(글자 수·금지 표현) → **이미지 생성 (OpenAI)** 매체당 1장 → 실패분은 **무료 이미지 생성 (예비)** → 결과 합치기 → 응답\n\n⚠ 처음 한 번: `OpenAI Chat Model`과 `이미지 생성 (OpenAI)` 두 노드 모두 OpenAI Credential 선택.\n이미지 방식(auto/openai/free)·모델 변경: `요청 정리 · 설정` 노드 맨 위 CONFIG. OpenAI 이미지 권한이 없으면 IMAGE_PROVIDER를 'free'로 두면 빠릅니다."),
]

for f in FLOWS:
    wf = build(f["fname"], f["name"], f["path"], f["steps"], f["temp"], f["note"])
    with open(f"{OUT}/n8n/{f['fname']}.json", "w", encoding="utf-8") as fp:
        json.dump(wf, fp, ensure_ascii=False, indent=2)
    pc = f["prompt_code"]
    s = pc.index("let prompt = `") + len("let prompt = `")
    user_tpl = pc[s:pc.index("`;", s)]
    md = f"""# {f['name']}

- n8n 파일: `n8n/{f['fname']}.json`
- Webhook 경로: `POST /webhook/{f['path']}`
- 모델: OpenAI `gpt-4o-mini` (AI Agent 노드 + Calculator 도구){' · 이미지: OpenAI Images API (`gpt-image-1`)' if f['fname'].startswith('04') else ''}

## 1. 시스템 프롬프트 (AI Agent 노드 → Options → System Message)

```text
{f['system']}
```

## 2. 사용자 프롬프트 템플릿 (Code 노드 '{f['prompt_node']}'에서 생성 → AI Agent의 Prompt로 전달)

`${{...}}` 부분은 프론트엔드 입력값이나 코드 계산값으로 자동 치환됩니다.

```text
{user_tpl}
```

## 3. 수정 요청(재생성) 프롬프트 — 대표가 '수정 요청'을 누르면 위 프롬프트 뒤에 추가

```text
[대표 수정 요청]
${{feedback}}

[이전 결과]
${{이전 결과 JSON}}

위 수정 요청을 반드시 반영해서, 같은 JSON 형식으로 전체 결과를 다시 작성해줘. 수정 요청과 관계없는 좋은 부분은 유지해.
```

## 4. 프롬프트 설계 포인트

- **역할·원칙 분리**: 시스템 프롬프트에는 클로이의 역할과 원칙만, 실제 데이터와 출력 형식은 사용자 프롬프트에 넣었습니다. (n8n AI Agent의 System Message는 중괄호를 변수로 해석할 수 있어 JSON 예시를 넣지 않았습니다.)
- **JSON 고정 출력**: 프론트엔드 화면에 바로 그릴 수 있도록 출력 구조를 고정했습니다.
- **환각 방지**: 숫자(예산, 인플루언서 수치·티어·적합도, 성과 지표, 글자 수)는 AI가 아니라 Code 노드가 계산·검증합니다. → 검증 계획의 '수치·제품 정보 오류 0건' 기준 대응.
- **대표 승인 구조**: AI는 초안만 만들고, 승인·수정 요청·규칙 밖 결정은 대표가 합니다.
"""
    with open(f"{OUT}/prompts/{f['fname']}_prompt.md", "w", encoding="utf-8") as fp:
        fp.write(md)

print("ok")
