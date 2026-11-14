/* ==========================================================================
 * Chloe Influencer Engine
 * - 인스타그램 / 틱톡 / 유튜브 후보를 티어(메가·매크로·미들·마이크로)로 나누고
 *   적합도(100점)를 계산한 뒤, 예산에 맞는 티어 믹스와 추천 조합을 만든다.
 * - 프론트엔드(데모 모드)와 n8n Code 노드가 "똑같은 이 코드"를 사용한다.
 *   (n8n 파일은 tools/build_n8n.py 가 이 파일을 Code 노드 안에 그대로 넣어 만든다)
 * - 숫자 계산은 전부 여기서. AI는 이 결과를 바탕으로 설명·DM·계약서만 쓴다.
 * ========================================================================== */
const ChloeEngine = (() => {
  const PLATFORMS = ['인스타그램', '틱톡', '유튜브'];
  const PLATFORM_ALIAS = {
    instagram: '인스타그램', insta: '인스타그램', ig: '인스타그램', '인스타': '인스타그램', '인스타그램': '인스타그램',
    tiktok: '틱톡', 'tik tok': '틱톡', '틱톡': '틱톡',
    youtube: '유튜브', yt: '유튜브', '유튜브': '유튜브', '유투브': '유튜브',
  };
  // 팔로워(구독자) 기준 티어
  const TIERS = [
    { key: 'mega', label: '메가', min: 1000000, range: '100만+' },
    { key: 'macro', label: '매크로', min: 100000, range: '10만~100만' },
    { key: 'mid', label: '미들', min: 30000, range: '3만~10만' },
    { key: 'micro', label: '마이크로', min: 1000, range: '1천~3만' },
  ];
  const TIER_LABEL = Object.fromEntries(TIERS.map(t => [t.key, t.label]));
  // 단가를 모를 때 쓰는 추정치: 팔로워 1명당 원 (게시물/영상 1건 기준, 업계 통용 범위의 중간값)
  const RATE = {
    '인스타그램': { mega: 5, macro: 8, mid: 12, micro: 15 },
    '틱톡': { mega: 3, macro: 5, mid: 8, micro: 10 },
    '유튜브': { mega: 10, macro: 20, mid: 30, micro: 40 },
  };
  // 참여율 기준값(%) — 인스타·틱톡: (좋아요+댓글)/팔로워, 유튜브: 평균 조회수/구독자
  const ER_BENCH = {
    '인스타그램': { mega: 1.2, macro: 1.8, mid: 2.5, micro: 3.5 },
    '틱톡': { mega: 4, macro: 5, mid: 6, micro: 8 },
    '유튜브': { mega: 6, macro: 10, mid: 15, micro: 20 },
  };
  const CAT_WORDS = {
    '뷰티': ['뷰티', '스킨케어', '화장품', '메이크업', '피부', '코스메틱', '성분', 'beauty', 'skincare', 'makeup'],
    '푸드': ['푸드', '음식', '건강', '식단', '레시피', '먹방', '다이어트', '간식', '요리', 'food', 'recipe'],
    '패션': ['패션', '코디', '스타일', 'ootd', '룩북', '옷', 'fashion'],
    '리빙': ['리빙', '인테리어', '살림', '홈', '자취', '생활', 'living', 'interior'],
    '테크': ['테크', 'it', '가전', '전자', '기기', '데스크', 'tech', 'gadget'],
  };
  const AGES = ['10대', '20대', '30대', '40대', '50대+'];

  // ---------------------------------------------------------------- 유틸
  const toNum = v => {
    if (v === null || v === undefined) return null;
    if (typeof v === 'number') return isFinite(v) ? v : null;
    let s = String(v).trim().replace(/[,\s원%명]/g, '');
    if (!s) return null;
    let mul = 1;
    if (/만$/.test(s)) { mul = 10000; s = s.slice(0, -1); }
    else if (/천$/.test(s)) { mul = 1000; s = s.slice(0, -1); }
    else if (/[kK]$/.test(s)) { mul = 1000; s = s.slice(0, -1); }
    else if (/[mM]$/.test(s)) { mul = 1000000; s = s.slice(0, -1); }
    const n = parseFloat(s);
    return isFinite(n) ? n * mul : null;
  };
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const round = (x, d = 0) => { const p = Math.pow(10, d); return Math.round(x * p) / p; };
  const lower = s => String(s || '').toLowerCase();
  const tierOf = f => (f >= 1000000 ? 'mega' : f >= 100000 ? 'macro' : f >= 30000 ? 'mid' : 'micro');
  const normPlatform = p => PLATFORM_ALIAS[lower(p).trim()] || PLATFORM_ALIAS[String(p || '').trim()] || null;
  const normAge = a => { const m = String(a || '').match(/(10|20|30|40|50)/); return m ? (m[1] === '50' ? '50대+' : m[1] + '대') : ''; };

  // ---------------------------------------------------------------- CSV (구글 시트 '웹에 게시' CSV)
  function parseCsv(text) {
    const rows = []; let row = [], cur = '', q = false;
    const t = String(text || '').replace(/^﻿/, '');
    for (let i = 0; i < t.length; i++) {
      const ch = t[i];
      if (q) {
        if (ch === '"' && t[i + 1] === '"') { cur += '"'; i++; }
        else if (ch === '"') q = false;
        else cur += ch;
      } else if (ch === '"') q = true;
      else if (ch === ',') { row.push(cur); cur = ''; }
      else if (ch === '\n' || ch === '\r') {
        if (ch === '\r' && t[i + 1] === '\n') i++;
        row.push(cur); cur = ''; if (row.some(c => c.trim() !== '')) rows.push(row); row = [];
      } else cur += ch;
    }
    row.push(cur); if (row.some(c => c.trim() !== '')) rows.push(row);
    if (rows.length < 2) return [];
    const HEAD = {
      platform: ['platform', '플랫폼', '채널'], handle: ['handle', '핸들', '계정', '아이디'], name: ['name', '이름', '채널명', '닉네임'],
      followers: ['followers', '팔로워', '구독자', '팔로워수', '구독자수', '팔로워/구독자'], engagement_rate: ['engagement_rate', '참여율', '참여율(%)', '조회율'],
      est_cost: ['est_cost', '단가', '예상단가', '예상 단가', '단가(원)'], tags: ['tags', '태그', '카테고리', '분야'],
      audience_female: ['audience_female', '여성비율', '여성 비율', '여성비율(%)'], audience_age: ['audience_age', '주연령', '주 연령', '주요연령', '주요 연령대'],
      ad_ratio: ['ad_ratio', '광고비율', '광고 비율', '광고비율(%)'], note: ['note', '메모', '특징', '콘텐츠 특징'], url: ['url', '링크', '주소'],
    };
    const head = rows[0].map(h => lower(h).trim());
    const idx = {};
    for (const [k, alts] of Object.entries(HEAD)) idx[k] = head.findIndex(h => alts.map(lower).includes(h));
    return rows.slice(1).map(r => { const o = {}; for (const k of Object.keys(HEAD)) o[k] = idx[k] >= 0 ? (r[idx[k]] || '').trim() : ''; return o; });
  }

  // ---------------------------------------------------------------- 후보 정규화
  function normalize(r, source) {
    const platform = normPlatform(r.platform);
    const followers = toNum(r.followers);
    if (!platform || !followers || followers < 1000) return null;
    let handle = String(r.handle || r.name || '').trim();
    if (!handle) return null;
    if (!handle.startsWith('@')) handle = '@' + handle.replace(/^@+/, '');
    const tier = tierOf(followers);
    const est = toNum(r.est_cost);
    const tags = Array.isArray(r.tags) ? r.tags : String(r.tags || '').split(/[|\/,;#]+/).map(s => s.trim()).filter(Boolean);
    return {
      platform, handle, name: String(r.name || handle).trim(), followers: Math.round(followers),
      engagement_rate: toNum(r.engagement_rate), tags,
      audience_female: toNum(r.audience_female), audience_age: normAge(r.audience_age),
      ad_ratio: toNum(r.ad_ratio), note: String(r.note || '').trim(), url: String(r.url || '').trim(),
      tier, tier_label: TIER_LABEL[tier],
      est_cost: est ? Math.round(est) : Math.max(100000, Math.round(followers * RATE[platform][tier] / 10000) * 10000),
      cost_estimated: !est, source: source || 'sheet',
    };
  }

  // 유튜브 API (channels.list) 응답 → 후보
  function fromYouTube(items) {
    return (items || []).map(ch => {
      const st = ch.statistics || {}, sn = ch.snippet || {};
      if (st.hiddenSubscriberCount) return null;
      const subs = Number(st.subscriberCount || 0), views = Number(st.viewCount || 0), vids = Number(st.videoCount || 0);
      const text = lower(sn.title + ' ' + sn.description);
      const tags = Object.entries(CAT_WORDS).filter(([, ws]) => ws.some(w => text.includes(lower(w)))).map(([c]) => c);
      const er = subs > 0 && vids > 0 ? round(views / vids / subs * 100, 1) : null;
      return normalize({
        platform: '유튜브', handle: sn.customUrl || ch.id, name: sn.title, followers: subs,
        engagement_rate: er, tags, note: String(sn.description || '').replace(/\s+/g, ' ').slice(0, 80),
        url: 'https://www.youtube.com/' + (sn.customUrl || 'channel/' + ch.id),
      }, 'youtube');
    }).filter(Boolean);
  }

  // ---------------------------------------------------------------- 적합도 점수 (100점)
  function score(c, req, medianCpe) {
    const bd = {}; const reasons = []; const risks = [];
    const hay = lower(c.tags.join(' ') + ' ' + c.note + ' ' + c.name);
    // 1) 콘텐츠 적합 30
    const catWords = CAT_WORDS[req.category] || [lower(req.category)];
    const catHit = c.tags.map(lower).includes(lower(req.category)) || catWords.some(w => hay.includes(lower(w)));
    const kws = String(req.keywords || '').split(/[,\s/]+/).map(s => s.trim()).filter(s => s.length >= 2);
    const kwHits = kws.filter(k => hay.includes(lower(k)));
    bd.content = (catHit ? 20 : 0) + Math.min(kwHits.length, 2) * 5;
    if (catHit) reasons.push(`${req.category} 콘텐츠`);
    if (kwHits.length) reasons.push(`키워드 일치: ${kwHits.slice(0, 2).join(', ')}`);
    // 2) 오디언스 적합 25 (성별 12 + 연령 13)
    let g = 6;
    if (c.audience_female !== null && c.audience_female !== undefined) {
      if (req.gender === '여성') g = c.audience_female / 100 * 12;
      else if (req.gender === '남성') g = (100 - c.audience_female) / 100 * 12;
      else g = 9;
    }
    let a = 6;
    const ages = (req.ages && req.ages.length) ? req.ages : [];
    if (c.audience_age && ages.length) {
      const ci = AGES.indexOf(c.audience_age);
      const d = Math.min(...ages.map(x => Math.abs(AGES.indexOf(x) - ci)));
      a = d === 0 ? 13 : d === 1 ? 6 : 0;
      if (d === 0) reasons.push(`주 시청층 ${c.audience_age} 일치`);
    }
    bd.audience = Math.round(g + a);
    if (req.gender !== '무관' && c.audience_female !== null && c.audience_female !== undefined) {
      const share = req.gender === '여성' ? c.audience_female : 100 - c.audience_female;
      if (share >= 70) reasons.push(`${req.gender} 비율 ${share}%`);
    }
    // 3) 참여율 20 (플랫폼·티어별 기준 대비)
    const bench = ER_BENCH[c.platform][c.tier];
    const er = c.engagement_rate;
    if (er === null || er === undefined) { bd.engagement = 8; risks.push('참여율 정보 없음'); }
    else {
      const ratio = er / bench;
      bd.engagement = Math.round(clamp(ratio, 0, 2) / 2 * 20);
      if (ratio >= 1.3) reasons.push(`참여율 ${er}% (기준 ${bench}%의 ${round(ratio, 1)}배)`);
      if (ratio < 0.3) risks.push('팔로워 대비 반응이 매우 낮음 (허수 팔로워 점검)');
      if (ratio > 4) risks.push('반응률이 이례적으로 높음 (이벤트성 게시물 확인)');
    }
    // 4) 비용 효율 15 (반응 1명당 비용, 같은 플랫폼 중앙값 대비)
    const engaged = c.followers * ((er || bench) / 100);
    c.cost_per_engage = engaged > 0 ? round(c.est_cost / engaged, 0) : null;
    const med = medianCpe[c.platform];
    bd.cost = c.cost_per_engage && med ? Math.round(clamp(med / c.cost_per_engage, 0, 2) / 2 * 15) : 7;
    if (bd.cost >= 11) reasons.push('반응 대비 단가 효율 좋음');
    // 5) 신뢰도 10
    let tr = 10;
    if (c.ad_ratio !== null && c.ad_ratio !== undefined && c.ad_ratio > 50) { tr -= 4; risks.push(`최근 광고 게시물 비중 ${c.ad_ratio}%`); }
    if (er !== null && er !== undefined && er / bench < 0.3) tr -= 6;
    if (c.source === 'youtube') risks.push('공개 API 기반 추정치 (시청자 성별·연령은 채널에 직접 확인)');
    if (c.source === 'sample') risks.push('데모용 가상 인물');
    bd.trust = Math.max(0, tr);
    // 6) 지난 협업 이력
    const past = (req.past_collabs || []).find(p => lower(p.handle) === lower(c.handle));
    bd.history = past ? (past.result === 'good' ? 8 : past.result === 'bad' ? -15 : 0) : 0;
    if (past && past.result === 'good') reasons.push('지난 협업 성과 좋음');
    if (past && past.result === 'bad') risks.push('지난 협업 성과 아쉬움');
    if (c.est_cost > req.budget) risks.push('단가가 총예산 초과');
    const fit = clamp(bd.content + bd.audience + bd.engagement + bd.cost + bd.trust + bd.history, 0, 100);
    return { ...c, fit_score: fit, breakdown: bd, reasons, risks, over_budget: c.est_cost > req.budget };
  }

  // ---------------------------------------------------------------- 예산 → 티어 믹스
  function tierMix(budget, goal) {
    let mix, band;
    if (budget < 1000000) { mix = { micro: 100 }; band = '100만원 미만'; }
    else if (budget < 3000000) { mix = { mid: 50, micro: 50 }; band = '100만~300만원'; }
    else if (budget < 15000000) { mix = { macro: 40, mid: 30, micro: 30 }; band = '300만~1,500만원'; }
    else { mix = { mega: 40, macro: 25, mid: 20, micro: 15 }; band = '1,500만원 이상'; }
    const keys = Object.keys(mix); let adj = '';
    if (keys.length > 1) {
      if (/인지도|도달|런칭/.test(goal)) { mix[keys[0]] += 10; mix.micro -= 10; adj = '인지도 목표 → 상위 티어 +10%p'; }
      else if (/전환|구매|리뷰|후기|콘텐츠/.test(goal)) { mix[keys[0]] -= 10; mix.micro += 10; adj = '전환·후기 목표 → 마이크로 +10%p'; }
    }
    let acc = 0;
    const allocations = keys.map((k, i) => {
      const amount = i === keys.length - 1 ? budget - acc : Math.round(budget * mix[k] / 100 / 10000) * 10000;
      acc += amount; return { tier: k, tier_label: TIER_LABEL[k], ratio: mix[k], amount };
    });
    return { budget, band, adjustment: adj, allocations };
  }

  // ---------------------------------------------------------------- 추천 조합 (티어별 예산 안에서, 플랫폼 다양하게)
  function portfolio(scored, mix, maxMembers) {
    const picked = []; let carry = 0;
    for (const a of mix.allocations) {
      let remain = a.amount + carry;
      const pool = scored.filter(c => c.tier === a.tier && c.fit_score >= 55 && c.breakdown.content > 0 && !c.over_budget).sort((x, y) => y.fit_score - x.fit_score);
      const used = new Set();
      for (const pass of [0, 1]) for (const c of pool) {
        if (picked.includes(c) || picked.length >= maxMembers) continue;
        if (pass === 0 && used.has(c.platform)) continue;
        if (c.est_cost <= remain) { picked.push(c); remain -= c.est_cost; used.add(c.platform); }
      }
      a.used = a.amount + carry - remain;
      a.count = picked.filter(c => c.tier === a.tier).length;
      a.note = a.count ? '' : picked.length >= maxMembers ? `추천 인원 상한(${maxMembers}명) 도달` : pool.length ? '예산 부족 → 다음 티어로 이월' : '적합 후보 없음 → 다음 티어로 이월';
      carry = remain;
    }
    const total = picked.reduce((s, c) => s + c.est_cost, 0);
    return { members: picked, total, left: mix.budget - total };
  }

  // ---------------------------------------------------------------- 실행
  function run(req, candidates) {
    req = { budget: 2000000, goal: '', gender: '무관', ages: [], platforms: PLATFORMS, keywords: '', past_collabs: [], ...req };
    const platforms = (req.platforms && req.platforms.length ? req.platforms : PLATFORMS).map(normPlatform).filter(Boolean);
    const seen = new Set();
    const pool = (candidates || []).filter(c => c && platforms.includes(c.platform)).filter(c => {
      const k = c.platform + lower(c.handle); if (seen.has(k)) return false; seen.add(k); return true;
    });
    const medianCpe = {};
    for (const p of PLATFORMS) {
      const xs = pool.filter(c => c.platform === p).map(c => c.est_cost / (c.followers * ((c.engagement_rate || ER_BENCH[p][c.tier]) / 100))).sort((a, b) => a - b);
      medianCpe[p] = xs.length ? xs[Math.floor(xs.length / 2)] : null;
    }
    const scored = pool.map(c => score(c, req, medianCpe)).sort((a, b) => b.fit_score - a.fit_score);
    const mix = tierMix(req.budget, req.goal);
    const pf = portfolio(scored, mix, 8);
    const by_platform = {};
    for (const p of platforms) by_platform[p] = scored.filter(c => c.platform === p).slice(0, 6);
    const sources = scored.reduce((o, c) => { o[c.source] = (o[c.source] || 0) + 1; return o; }, {});
    return { tier_mix: mix, portfolio: pf.members, portfolio_total: pf.total, budget_left: pf.left, by_platform, sources, candidate_count: scored.length, tiers: TIERS };
  }

  // ---------------------------------------------------------------- 데모용 가상 후보 (실존 인물 아님)
  const SAMPLE_ROWS = [
    // platform, handle, name, followers, ER, est_cost, tags, female%, age, ad%, note
    ['인스타그램', '@yuna.daily', '유나 데일리', 1450000, 1.1, '', '뷰티|패션', 78, '20대', 35, '셀럽형 데일리 뷰티'],
    ['인스타그램', '@chef.minho', '셰프 민호', 1120000, 1.4, '', '푸드|리빙', 55, '30대', 30, '집밥 레시피'],
    ['인스타그램', '@skin_note_ara', '아라의 스킨노트', 260000, 2.2, '', '뷰티|스킨케어|성분', 85, '20대', 40, '성분 꼼꼼 리뷰'],
    ['인스타그램', '@mood_room', '무드룸', 180000, 1.9, '', '리빙|인테리어', 77, '30대', 45, '원룸 인테리어'],
    ['인스타그램', '@fit_jun', '핏준', 140000, 2.6, '', '푸드|건강|운동', 35, '20대', 25, '홈트·식단'],
    ['인스타그램', '@glowwith_hana', '하나의 피부일기', 48000, 5.8, 450000, '뷰티|스킨케어|민감성', 82, '20대', 20, '민감성 피부 루틴'],
    ['인스타그램', '@daily_minji', '민지의 데일리', 72000, 3.1, '', '뷰티|패션', 75, '20대', 55, '데일리룩·메이크업'],
    ['인스타그램', '@salad_mom', '샐러드맘', 39000, 4.2, '', '푸드|건강|육아', 80, '30대', 30, '건강 간식 레시피'],
    ['인스타그램', '@desk_setup_k', '데스크셋업K', 55000, 2.9, '', '테크|리빙', 30, '20대', 35, '데스크테리어'],
    ['인스타그램', '@dry_skin_diary', '건성피부 일기', 18000, 6.4, 250000, '뷰티|스킨케어|건성|수분', 88, '20대', 15, '건성 피부 보습 루틴'],
    ['인스타그램', '@office_lookbook', '오피스 룩북', 12500, 4.8, '', '패션|직장인', 81, '30대', 20, '출근룩'],
    ['인스타그램', '@homecafe_yeon', '연의 홈카페', 9800, 7.5, '', '푸드|리빙|홈카페', 84, '20대', 10, '홈카페 레시피'],
    ['틱톡', '@dance_jay', '댄스 제이', 2300000, 4.5, '', '라이프|패션', 60, '10대', 30, '챌린지 댄스'],
    ['틱톡', '@hack_life', '생활꿀팁 해커', 1050000, 5.2, '', '리빙|테크', 50, '20대', 40, '생활 꿀팁 숏폼'],
    ['틱톡', '@ootd_seoul', '서울 오오티디', 180000, 8.3, '', '패션|뷰티', 70, '20대', 35, '숏폼 스타일링'],
    ['틱톡', '@cleanbeauty_yu', '유의 클린뷰티', 320000, 7.1, '', '뷰티|스킨케어|성분', 82, '20대', 30, '성분·사용감 숏폼 리뷰'],
    ['틱톡', '@mukbang_bori', '먹방보리', 410000, 6.0, '', '푸드|먹방', 55, '20대', 45, '편의점 먹방'],
    ['틱톡', '@gadget_bori', '가젯보리', 76000, 7.7, '', '테크|라이프', 40, '20대', 25, '신기한 아이템'],
    ['틱톡', '@skincare_tok_rin', '린의 스킨케어톡', 64000, 9.4, '', '뷰티|스킨케어|수분', 86, '20대', 20, '스킨케어 루틴 숏폼'],
    ['틱톡', '@diet_recipe_su', '수의 다이어트 레시피', 45000, 8.8, '', '푸드|건강|다이어트', 78, '20대', 25, '저칼로리 레시피'],
    ['틱톡', '@minimal_vanity', '미니멀 화장대', 22000, 10.2, '', '뷰티|스킨케어|민감성', 90, '20대', 10, '최소 루틴 스킨케어'],
    ['틱톡', '@studentmakeup_j', '학생메이크업 J', 15000, 11.5, '', '뷰티|메이크업', 87, '10대', 15, '학생 메이크업'],
    ['틱톡', '@room_tour_s', '룸투어S', 11000, 9.0, '', '리빙|자취', 72, '20대', 10, '자취방 룸투어'],
    ['틱톡', '@snack_review_t', '간식리뷰T', 26000, 8.1, '', '푸드|간식', 60, '20대', 30, '신상 간식 리뷰'],
    ['유튜브', '@beautyclass_jin', '뷰티클래스 진', 1800000, 5, '', '뷰티|메이크업', 80, '20대', 35, '메이크업 튜토리얼'],
    ['유튜브', '@tech_ssam', '테크쌤', 1250000, 7, '', '테크|리빙', 25, '30대', 30, '가전·IT 리뷰'],
    ['유튜브', '@skin_lab_doc', '피부연구소 J', 210000, 14, '', '뷰티|스킨케어|성분', 72, '30대', 30, '성분 분석 리뷰'],
    ['유튜브', '@hometable_k', '홈테이블', 145000, 11, '', '푸드|리빙', 75, '30대', 35, '집밥·주방용품'],
    ['유튜브', '@ondo_vlog', '온도 브이로그', 120000, 16, '', '라이프|리빙|자취', 68, '20대', 20, '자취·살림 브이로그'],
    ['유튜브', '@sensitive_skin_tv', '민감피부TV', 58000, 22, 1500000, '뷰티|스킨케어|민감성', 84, '30대', 15, '민감성 피부 제품 비교'],
    ['유튜브', '@office_vlog_mina', '미나의 직장인 브이로그', 42000, 18, '', '라이프|직장인|뷰티', 79, '30대', 20, '직장인 일상'],
    ['유튜브', '@fitness_hoon', '피트니스 훈', 85000, 12, '', '운동|건강|푸드', 30, '20대', 30, '운동·식단'],
    ['유튜브', '@cosme_note_h', '코스메 노트 H', 21000, 25, '', '뷰티|스킨케어|수분', 86, '20대', 10, '기초 화장품 리뷰'],
    ['유튜브', '@cook_for_one', '1인분 요리', 16000, 28, '', '푸드|자취', 60, '20대', 10, '1인 가구 요리'],
    ['유튜브', '@desk_review_d', '데스크 리뷰 D', 13000, 19, '', '테크', 20, '20대', 20, '데스크 기기 리뷰'],
    ['유튜브', '@slow_living_y', '슬로우리빙 Y', 8500, 30, '', '리빙|라이프', 81, '30대', 5, '느린 살림 브이로그'],
  ];
  const SAMPLE = SAMPLE_ROWS.map(r => normalize({ platform: r[0], handle: r[1], name: r[2], followers: r[3], engagement_rate: r[4], est_cost: r[5], tags: r[6], audience_female: r[7], audience_age: r[8], ad_ratio: r[9], note: r[10] }, 'sample'));

  return { run, parseCsv, normalize, fromYouTube, tierMix, tierOf, PLATFORMS, TIERS, SAMPLE, SAMPLE_ROWS };
})();
if (typeof window !== 'undefined') window.ChloeEngine = ChloeEngine;
