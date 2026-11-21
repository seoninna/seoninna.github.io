/* ==========================================================================
 * Chloe Cycle Engine — 캠페인 선순환
 *   ① 인플루언서 선정 → ② 협업 콘텐츠로 매체 광고 → ③ 광고 성과 입력
 *   → ④ 인플루언서별 판정(유지/관찰/제외) + 다음 회차 광고 예산 재배분 → 검증된 인플루언서 풀
 * - 프론트엔드(데모 모드)와 n8n Code 노드가 같은 코드를 사용한다.
 * - store = { pool: {키: 인플루언서}, campaigns: [캠페인] } 형태의 객체를 받아 직접 수정한다.
 *   (n8n에서는 워크플로 static data, 데모에서는 브라우저 저장소)
 * ========================================================================== */
const ChloeCycle = (() => {
  const RULES = { keepRatio: 1.0, dropRatio: 0.8, minClicks: 100, minConversions: 5, watchShareMax: 0.15, maxCampaigns: 30 };
  const keyOf = m => `${m.platform}|${String(m.handle || '').toLowerCase()}`;
  const r2 = x => (x === null || !isFinite(x)) ? null : Math.round(x * 100) / 100;
  const num = v => { const n = Number(String(v ?? '').replace(/[,\s원%]/g, '')); return isFinite(n) ? n : 0; };
  const nowIso = () => new Date().toISOString();

  function init(store) {
    store.pool = store.pool || {};
    store.campaigns = store.campaigns || [];
    return store;
  }

  function poolList(store) {
    const order = { keep: 0, watch: 1, new: 2, drop: 3 };
    return Object.values(init(store).pool).sort((a, b) => (order[a.status] - order[b.status]) || ((b.avg_roas || 0) - (a.avg_roas || 0)));
  }

  // ① 캠페인 시작: 추천 조합(인플루언서 엔진 결과)을 담는다
  function start(store, body) {
    init(store);
    const product = String(body.product || '제품');
    const round = store.campaigns.filter(c => c.product === product).length + 1;
    const members = (body.members || []).map(m => ({
      handle: m.handle, platform: m.platform, name: m.name || m.handle, tier: m.tier || '', tier_label: m.tier_label || '',
      followers: num(m.followers), est_cost: num(m.est_cost), fit_score: num(m.fit_score), url: m.url || '', source: m.source || '',
    })).filter(m => m.handle && m.platform);
    const c = {
      id: 'c' + Date.now().toString(36), name: body.campaign_name || `${product} ${round}회차`, product, round,
      created_at: nowIso(), status: 'selected', influencer_budget: num(body.influencer_budget), members,
    };
    store.campaigns.unshift(c);
    store.campaigns = store.campaigns.slice(0, RULES.maxCampaigns);
    for (const m of members) {
      const k = keyOf(m), p = store.pool[k];
      if (!p) store.pool[k] = { ...m, status: 'new', rounds: [], totals: { ad_spend: 0, revenue: 0 }, avg_roas: null, updated_at: nowIso() };
      else Object.assign(p, { name: m.name, followers: m.followers || p.followers, tier: m.tier || p.tier, tier_label: m.tier_label || p.tier_label, url: m.url || p.url, updated_at: nowIso() });
    }
    return c;
  }

  // ④ 성과 판정 + 다음 회차 예산 재배분
  function evaluate(store, body) {
    init(store);
    const c = store.campaigns.find(x => x.id === body.campaign_id) || store.campaigns[0];
    if (!c) throw new Error('캠페인이 없어요. 먼저 인플루언서 조합으로 캠페인을 시작하세요.');
    if (!(body.results || []).length) throw new Error('광고 성과를 한 명 이상 입력해주세요.');
    const target = num(body.target_roas) || 300;
    const results = (body.results || []).map(r => {
      const ad = num(r.ad_spend), imp = num(r.impressions), clk = num(r.clicks), conv = num(r.conversions), rev = num(r.revenue), collab = num(r.collab_cost);
      const roas = ad > 0 ? rev / ad * 100 : null;
      const total_roi = ad + collab > 0 ? rev / (ad + collab) * 100 : null;
      const enough = clk >= RULES.minClicks && conv >= RULES.minConversions;
      let verdict, reason;
      if (!enough) { verdict = 'watch'; reason = `데이터 부족 (클릭 ${clk}, 구매 ${conv}건) → 한 회차 더 관찰`; }
      else if (roas >= target * RULES.keepRatio) { verdict = 'keep'; reason = `ROAS ${r2(roas)}% ≥ 목표 ${target}%`; }
      else if (roas >= target * RULES.dropRatio) { verdict = 'watch'; reason = `ROAS ${r2(roas)}%로 목표의 ${Math.round(RULES.dropRatio * 100)}~100% 구간 → 소재 교체 후 재확인`; }
      else { verdict = 'drop'; reason = `ROAS ${r2(roas)}% < 목표의 ${Math.round(RULES.dropRatio * 100)}% → 다음 회차 제외`; }
      return { handle: r.handle, platform: r.platform, name: r.name || r.handle, ad_spend: ad, impressions: imp, clicks: clk, conversions: conv, revenue: rev, collab_cost: collab,
        ctr: imp > 0 ? r2(clk / imp * 100) : null, cvr: clk > 0 ? r2(conv / clk * 100) : null, cpa: conv > 0 ? r2(ad / conv) : null,
        roas: r2(roas), total_roi: r2(total_roi), enough_data: enough, verdict, reason };
    });
    // 다음 회차 광고 예산: 제외 0, 관찰은 지난 광고비 유지(상한 15%), 나머지는 유지 인플루언서에게 ROAS 비례
    const next = num(body.next_ad_budget) || results.reduce((s, r) => s + r.ad_spend, 0);
    const keep = results.filter(r => r.verdict === 'keep'), watch = results.filter(r => r.verdict === 'watch');
    const alloc = {};
    let used = 0;
    for (const r of watch) { const a = Math.round(Math.min(r.ad_spend, next * RULES.watchShareMax) / 10000) * 10000; alloc[keyOf(r)] = a; used += a; }
    if (used > next) { const s = next / used; used = 0; for (const r of watch) { alloc[keyOf(r)] = Math.floor(alloc[keyOf(r)] * s / 10000) * 10000; used += alloc[keyOf(r)]; } }
    const left = next - used;
    const wsum = keep.reduce((s, r) => s + (r.roas || 0), 0);
    keep.forEach((r, i) => {
      const a = i === keep.length - 1 ? left - keep.slice(0, -1).reduce((s, x) => s + alloc[keyOf(x)], 0) : Math.round(left * (r.roas || 0) / (wsum || 1) / 10000) * 10000;
      alloc[keyOf(r)] = Math.max(0, a);
    });
    const unallocated = next - Object.values(alloc).reduce((s, a) => s + a, 0);
    const allocation = results.map(r => ({ handle: r.handle, platform: r.platform, name: r.name, verdict: r.verdict, current: r.ad_spend, proposed: alloc[keyOf(r)] || 0,
      change_pct: r.ad_spend > 0 ? r2(((alloc[keyOf(r)] || 0) - r.ad_spend) / r.ad_spend * 100) : null }));
    // 풀 업데이트
    for (const r of results) {
      const k = keyOf(r);
      const p = store.pool[k] || (store.pool[k] = { handle: r.handle, platform: r.platform, name: r.name, status: 'new', rounds: [], totals: { ad_spend: 0, revenue: 0 } });
      p.rounds = (p.rounds || []).filter(x => x.campaign_id !== c.id);
      p.rounds.push({ campaign_id: c.id, campaign: c.name, round: c.round, ad_spend: r.ad_spend, revenue: r.revenue, roas: r.roas, verdict: r.verdict, at: nowIso() });
      // 누적은 회차 기록으로 다시 계산 (같은 캠페인을 다시 판정해도 중복되지 않게)
      const t = { ad_spend: 0, revenue: 0 };
      for (const x of p.rounds) { t.ad_spend += x.ad_spend; t.revenue += x.revenue; }
      p.totals = t;
      p.avg_roas = t.ad_spend > 0 ? r2(t.revenue / t.ad_spend * 100) : null;
      const drops = p.rounds.filter(x => x.verdict === 'drop').length;
      p.status = r.verdict === 'keep' ? 'keep' : (r.verdict === 'drop' || drops >= 2) ? 'drop' : 'watch';
      p.updated_at = nowIso();
    }
    Object.assign(c, { status: 'evaluated', evaluated_at: nowIso(), target_roas: target, results, allocation, next_ad_budget: next, unallocated });
    const tot = results.reduce((s, r) => ({ ad: s.ad + r.ad_spend, rev: s.rev + r.revenue }), { ad: 0, rev: 0 });
    c.totals = { ad_spend: tot.ad, revenue: tot.rev, roas: tot.ad > 0 ? r2(tot.rev / tot.ad * 100) : null };
    c.counts = { keep: keep.length, watch: watch.length, drop: results.length - keep.length - watch.length };
    return c;
  }

  // 다음 회차 추천에 넘길 이력 (유지 → 가산점, 제외 → 추천에서 빠짐)
  function pastCollabs(store) {
    return poolList(store).filter(p => p.status === 'keep' || p.status === 'drop')
      .map(p => ({ handle: p.handle, platform: p.platform, result: p.status === 'keep' ? 'good' : 'bad', exclude: p.status === 'drop', memo: p.avg_roas !== null ? `누적 ROAS ${p.avg_roas}%` : '' }));
  }

  function aiPrompt(c, store) {
    const won = n => Number(n || 0).toLocaleString() + '원';
    return `아래는 인플루언서 협업 콘텐츠를 광고 소재로 집행한 결과야. 코드가 이미 판정과 예산 재배분을 끝냈으니, 숫자는 그대로 인용하고 대표님이 이해하기 쉽게 해석해줘.

[캠페인] ${c.name} (${c.round}회차) / 목표 ROAS ${c.target_roas}% / 전체 광고비 ${won(c.totals.ad_spend)} → 매출 ${won(c.totals.revenue)} (ROAS ${c.totals.roas}%)

[인플루언서 콘텐츠별 광고 성과 — 코드 계산]
${c.results.map(r => `- ${r.handle} (${r.platform}): 광고비 ${won(r.ad_spend)}, 클릭 ${r.clicks}, 구매 ${r.conversions}건, 매출 ${won(r.revenue)} | CTR ${r.ctr ?? '-'}% CVR ${r.cvr ?? '-'}% ROAS ${r.roas ?? '-'}% | 협업비 포함 ROI ${r.total_roi ?? '-'}% → 판정 ${({ keep: '유지', watch: '관찰', drop: '제외' })[r.verdict]} (${r.reason})`).join('\n')}

[다음 회차 광고 예산 재배분 — 코드 계산, 총 ${won(c.next_ad_budget)}]
${c.allocation.map(a => `- ${a.handle}: ${won(a.current)} → ${won(a.proposed)}`).join('\n')}${c.unallocated ? `\n- 미배정 ${won(c.unallocated)} (새 후보 테스트용)` : ''}

[검증된 인플루언서 풀]
${poolList(store).slice(0, 15).map(p => `- ${p.handle} (${p.platform}) 상태 ${p.status}, 누적 ROAS ${p.avg_roas ?? '-'}%, ${p.rounds.length}회 참여`).join('\n')}

[출력 형식] 아래 JSON 구조 그대로, 값만 채워서 출력:
{
  "summary": "이번 회차 결과 한 줄 요약",
  "insights": ["성과 차이의 원인 해석 1", "해석 2", "해석 3"],
  "per_influencer": [ { "handle": "@핸들 그대로", "comment": "이 인플루언서에 대한 한 줄 코멘트와 다음 행동" } ],
  "creative_tips": ["다음 광고 소재에 반영할 점 1", "반영할 점 2"],
  "next_round_strategy": "다음 회차 전략 (유지 인플루언서 활용, 새 후보 테스트 규모 포함 2~3문장)"
}`;
  }

  return { RULES, start, evaluate, poolList, pastCollabs, aiPrompt, init, keyOf };
})();
if (typeof window !== 'undefined') window.ChloeCycle = ChloeCycle;
