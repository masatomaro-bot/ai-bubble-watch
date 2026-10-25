const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../docs/jiai-ladder.js');
const T = require('../docs/theme-leaders.js');
const O = require('../docs/opportunity-lanes.js');

const base = () => ({
  date: '2026-10-22',
  overall_trend_state: 'confirmed_uptrend',
  sp500: { above_sma50: true, trend_state: { state: 'confirmed_uptrend' }, price: 110, sma50: 105, sma150: 100, sma200: 95, sma200_rising: true, pct_below_52w_high: 2 },
  nasdaq: { above_sma50: true, trend_state: { state: 'confirmed_uptrend' }, price: 110, sma50: 105, sma150: 100, sma200: 95, sma200_rising: true },
  stress_gauges: { vix: { level: 15, change_10d: -1 }, credit_hyg_ief: { change_10d_pct: 0.5 } },
  breadth_extended: { new_52w_highs: 300, new_52w_lows: 100 },
  market_leaders: [{ above_sma50: true }, { above_sma50: true }, { above_sma50: false }],
  sectors: { XLK: { quadrant: '主導' } },
  themes: { SOXX: { quadrant: '改善' } },
  warning_flags: [{ id: 'defensive_rotation', active: false }],
  broad_universe_technicals: { pct_above_50dma: 62 },
});

test('all gates clear on a healthy market', () => {
  const s = L.summarize(L.evaluateGates(base(), null));
  assert.equal(s.ok, 7);
  assert.equal(s.next, null);
});

test('2026-10-22 style weak internals: next gate is the lowest uncleared one', () => {
  const d = base();
  d.overall_trend_state = 'uptrend_under_pressure';
  d.stress_gauges = { vix: { level: 19, change_10d: 4.2 }, credit_hyg_ief: { change_10d_pct: -1.1 } };
  d.breadth_extended = { new_52w_highs: 138, new_52w_lows: 365 };
  d.broad_universe_technicals = { pct_above_50dma: 28.4 };
  const prior = { breadth_extended: { new_52w_lows: 757 }, broad_universe_technicals: { pct_above_50dma: 22.7 } };
  const g = L.evaluateGates(d, prior);
  const by = Object.fromEntries(g.map((x) => [x.id, x.status]));
  assert.equal(by.stress, 'ng');
  assert.equal(by.lows, 'partial');       // 新安値は5日前より減っている
  assert.equal(by.oneil, 'partial');
  assert.equal(by.participation, 'partial');
  assert.equal(L.summarize(g).next.id, 'stress');
});

test('missing data is "na", not a pass', () => {
  const g = L.evaluateGates({ date: 'x' }, null);
  assert.ok(g.every((x) => x.status === 'na'));
});

test('client-side stage fallback matches the python rule', () => {
  assert.equal(L.classifyStage({ price: 110, sma50: 105, sma150: 100, sma200: 95, sma200_rising: true }).stage_sub, '本流');
  assert.equal(L.classifyStage({ price: 102, sma50: 105, sma150: 100, sma200: 95, sma200_rising: true }).stage_sub, '押し目');
  assert.equal(L.classifyStage({ price: 80, sma50: 85, sma150: 90, sma200: 95, sma200_rising: false }).stage, 4);
  assert.equal(L.classifyStage({ price: 94, sma50: 98, sma150: 100, sma200: 95, sma200_rising: false }).stage, 3);
  assert.equal(L.classifyStage({ price: 98, sma50: 95, sma150: 92, sma200: 95, sma200_rising: false }).stage, 1);
  assert.equal(L.stageOf({ stage: 2, stage_label: 'Stage 2 上昇', stage_sub: '本流' }).stage, 2);
});

test('panels render without throwing and escape text', () => {
  const html = L.ladderPanel(base(), null) + L.stagePanel(base()) + L.ladderHistory([{ date: 'a', data: base() }, { date: 'b', data: base() }]);
  assert.match(html, /7 \/ 7 段クリア/);
  assert.match(L.candleSvg(null), /次回の日次更新/);
});

test('theme leaders: every theme has 2-3 stocks with a business line and no META/AMZN', () => {
  for (const th of T.THEMES) {
    assert.ok(th.stocks.length >= 2 && th.stocks.length <= 3, th.name);
    for (const s of th.stocks) { assert.ok(s.biz.length > 10); assert.ok(!['META', 'AMZN'].includes(s.t)); }
  }
  const html = T.render({ opportunity_universe: { rows: [{ ticker: 'CAT', rs_percentile: 90, one_month_pct: 1, three_month_pct: 2, above_sma50: true }] }, themes: {} });
  assert.match(html, /CAT/);
});

const row = (t, o) => ({ ticker: t, rs_percentile: 90, pct_below_52w_high: 5, sma_stack: true, avg_dollar_volume_20d: 1e8, above_sma50: true, range_contraction: 0.9, volume_dryup: 0.9, one_month_pct: 1, three_month_pct: 2, ...o });

test('lane B applies RS / 25%-from-high / MA stack / liquidity and region exclusion', () => {
  const latest = { overall_trend_state: 'confirmed_uptrend', opportunity_universe: { rows: [
    row('GOOD'), row('LOWRS', { rs_percentile: 70 }), row('FAR', { pct_below_52w_high: 40 }), row('FLAT', { sma_stack: false }),
    row('THIN', { avg_dollar_volume_20d: 1e6 }), row('CN'), row('UNDER50', { above_sma50: false }),
  ] } };
  const profiles = { get: (t) => (t === 'CN' ? { status: 'excluded' } : { status: 'review' }) };
  const res = O.leaderCandidates(latest, { profiles });
  assert.deepEqual(res.rows.map((r) => r.ticker), ['GOOD']);
  assert.equal(res.excludedRegion, 1);
  // 調整中は50日線割れでも「高値近くで耐えている」なら残す
  latest.overall_trend_state = 'correction';
  assert.ok(O.leaderCandidates(latest, { profiles }).rows.some((r) => r.ticker === 'UNDER50'));
});

test('lane B sorts by mode', () => {
  const latest = { overall_trend_state: 'correction', opportunity_universe: { rows: [row('A', { pct_below_52w_high: 10, range_contraction: 0.5 }), row('B', { pct_below_52w_high: 2, range_contraction: 1.2 })] } };
  assert.equal(O.leaderCandidates(latest).rows[0].ticker, 'B');
  latest.overall_trend_state = 'confirmed_uptrend';
  assert.equal(O.leaderCandidates(latest).rows[0].ticker, 'A');
});

test('mode is downgraded when ladder is weak even if trend is confirmed', () => {
  assert.equal(O.modeFor({ overall_trend_state: 'confirmed_uptrend' }, 5).name, 'ブレイク監視');
  assert.equal(O.modeFor({ overall_trend_state: 'confirmed_uptrend' }, 1).name, '選別');
  assert.equal(O.modeFor({ overall_trend_state: 'correction' }, 6).name, '仕込みリスト作り');
});

test('old-format data shows a waiting message instead of junk candidates', () => {
  const html = O.laneB({ overall_trend_state: 'correction', opportunity_universe: { rows: [{ ticker: 'DHY', rs_percentile: 99.9 }] } }, { state: { minDollarVolume: 5e7 }, ffty: null, profiles: null });
  assert.match(html, /次回の日次更新/);
  assert.doesNotMatch(html, /DHY/);
});
