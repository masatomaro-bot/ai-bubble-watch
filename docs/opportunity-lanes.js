/* 機会ウォッチ(2026-10-25作り直し)。地合いに連動したモード表示と3レーン。
   A: 次のNVDA(ストーリー監視)  B: リーダー候補(テクニカル)  C: 動意銘柄
   入力は日次JSON(latest.json)と data/ffty_latest.json だけ。外部送信なし。 */
(function (root) {
'use strict';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (v) => (v === null || v === undefined ? '-' : `${v > 0 ? '+' : ''}${v}%`);
const col = (v) => (v === null || v === undefined ? 'var(--muted)' : v > 0 ? 'var(--ok)' : v < 0 ? 'var(--err)' : 'var(--muted)');
const tv = (t) => `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(t)}`;

/* ---------- モード ---------- */

const MODES = {
  correction: {
    name: '仕込みリスト作り', cls: 'err',
    text: '指数は調整中。ブレイク買いより、下げ相場の中でも高値の近くに踏みとどまっている強い銘柄を探してリストにしておく時期。次の上昇でまず動くのはこの中から出やすい。',
    sortLabel: '52週高値に近い順(下げに耐えている順)', sortKey: 'near_high',
  },
  uptrend_under_pressure: {
    name: '選別', cls: 'warn',
    text: '上昇基調は残るが売り圧力がある。出来高を伴う強いブレイクだけに絞り、数を増やさない時期。',
    sortLabel: 'RSの高い順', sortKey: 'rs',
  },
  confirmed_uptrend: {
    name: 'ブレイク監視', cls: 'ok',
    text: '上昇トレンドが確認された。値幅が縮んで出来高が細った土台(VCP・カップウィズハンドル)からのブレイクを狙える時期。',
    sortLabel: '値幅が締まっている順', sortKey: 'tight',
  },
};

// 基本はO'Neil式の総合判定で決め、上昇確認でも回復ラダーが3段未満
// (中身が伴っていない)なら一段控えめの「選別」にする(3段は自前の仮置き)。
function modeFor(latest, ladderOk) {
  const m = MODES[latest?.overall_trend_state] || MODES.correction;
  if (m === MODES.confirmed_uptrend && typeof ladderOk === 'number' && ladderOk < 3) {
    return { ...MODES.uptrend_under_pressure, text: '指数は上昇確認だが、回復ラダーが3段未満で中身が伴っていない。' + MODES.uptrend_under_pressure.text };
  }
  return m;
}

/* ---------- レーンB: リーダー候補 ---------- */

// 固定の条件(出典のある目安): RS 80以上(O'Neil)、52週高値から25%以内・
// 50日>150日>200日線の並び(ミネルヴィニのトレンドテンプレート)。
// 売買代金の下限は画面で選ぶ(既定値は自前の仮置き)。
const RS_MIN = 80;
const OFF_HIGH_MAX = 25;
const LIQUIDITY_OPTIONS = [
  { v: 10e6, label: '1,000万ドル以上' },
  { v: 50e6, label: '5,000万ドル以上' },
  { v: 100e6, label: '1億ドル以上' },
];

function leaderCandidates(latest, opts) {
  const o = { minDollarVolume: 50e6, fftyOnly: false, budgetOnly: false, ffty: null, profiles: null, limit: 12, sortKey: null, ...opts };
  const state = latest?.overall_trend_state;
  const fftyMap = {};
  for (const r of o.ffty?.rows || []) fftyMap[String(r.ticker).replace('.', '-')] = r;
  const rows = latest?.opportunity_universe?.rows || [];
  let excludedRegion = 0;
  const hasShape = rows.some((r) => r.sma_stack !== undefined);
  const picked = rows.filter((r) => {
    if (!(r.rs_percentile >= RS_MIN)) return false;
    if (hasShape) {
      if (r.sma_stack !== true) return false;
      if (r.pct_below_52w_high === null || r.pct_below_52w_high === undefined || r.pct_below_52w_high > OFF_HIGH_MAX) return false;
      if ((r.avg_dollar_volume_20d ?? 0) < o.minDollarVolume) return false;
    }
    if (state !== 'correction' && r.above_sma50 === false) return false;
    const f = fftyMap[r.ticker];
    if (o.fftyOnly && !f) return false;
    if (o.budgetOnly && !(f && f.within_budget_max === true)) return false;
    const prof = o.profiles?.get ? o.profiles.get(r.ticker) : null;
    if (prof && prof.status === 'excluded') { excludedRegion++; return false; }
    return true;
  });
  const sorters = {
    near_high: (a, b) => (a.pct_below_52w_high ?? 99) - (b.pct_below_52w_high ?? 99) || b.rs_percentile - a.rs_percentile,
    tight: (a, b) => (a.range_contraction ?? 9) - (b.range_contraction ?? 9) || b.rs_percentile - a.rs_percentile,
    rs: (a, b) => b.rs_percentile - a.rs_percentile,
  };
  const key = o.sortKey || (modeFor({ overall_trend_state: state }).sortKey);
  picked.sort(sorters[key] || sorters.rs);
  return { rows: picked.slice(0, o.limit), total: picked.length, excludedRegion, hasShape, fftyMap };
}

function researchPrompt(r, name) {
  return `${r.ticker}${name ? `(${name})` : ''}について、最新の決算資料(IR・SEC)をもとに次の構成でまとめてください。` +
    '①事業セグメント別の売上・成長率の分解 ②前四半期・前年同期との比較 ③成長ドライバーごとの構造分析(何で稼ぎ、競争優位はどこにあるか) ④供給制約など今後のリスク・変化要因 ⑤結論。' +
    `株価面では、RS百分位${r.rs_percentile}、52週高値から-${r.pct_below_52w_high ?? '-'}%、1か月${pct(r.one_month_pct)}・3か月${pct(r.three_month_pct)}(日次データ ${r.observed_date || ''})。数字は出典と対象期間を付け、わからないことはわからないと書いてください。`;
}

function laneB(latest, ctx) {
  const st = ctx.state;
  const mode = ctx.mode || modeFor(latest);
  const res = leaderCandidates(latest, { minDollarVolume: st.minDollarVolume, fftyOnly: st.fftyOnly, budgetOnly: st.budgetOnly, ffty: ctx.ffty, profiles: ctx.profiles, sortKey: mode.sortKey });
  const fftyNote = ctx.ffty ? `FFTY構成銘柄データ: ${esc(ctx.ffty.date)}` : 'FFTY構成銘柄のデータは次回の日次更新から(現在は未取得)';
  const controls = `<div class="ol-controls">
    <label>売買代金(20日平均)<select data-ol="liq">${LIQUIDITY_OPTIONS.map((x) => `<option value="${x.v}" ${x.v === st.minDollarVolume ? 'selected' : ''}>${x.label}</option>`).join('')}</select></label>
    <label><input type="checkbox" data-ol="ffty" ${st.fftyOnly ? 'checked' : ''} ${ctx.ffty ? '' : 'disabled'}> FFTY構成銘柄のみ</label>
    <label><input type="checkbox" data-ol="budget" ${st.budgetOnly ? 'checked' : ''} ${ctx.ffty ? '' : 'disabled'}> 予算内(100万円で1株以上)</label>
  </div>`;
  if (!res.hasShape) {
    return `${controls}<div class="sub">今のデータは旧形式のため、土台の補助値(値幅収縮・出来高の細り・移動平均の並び)がまだありません。次回の日次更新(新しい母集団・品質フィルタ)から候補が出ます。</div>`;
  }
  const body = res.rows.map((r) => {
    const f = res.fftyMap[r.ticker];
    const prof = ctx.profiles?.get ? ctx.profiles.get(r.ticker) : null;
    const name = f?.name || (prof && prof.status !== 'review' ? prof.name : '');
    const tags = f ? '<span class="ol-tag">FFTY</span>' : '';
    const contraction = r.range_contraction === null || r.range_contraction === undefined ? '-' : `${r.range_contraction}`;
    const dry = r.volume_dryup === null || r.volume_dryup === undefined ? '-' : `${r.volume_dryup}`;
    return `<tr>
      <td><a class="mono ol-ticker" href="${tv(r.ticker)}" target="_blank" rel="noopener">${esc(r.ticker)}</a>${tags}${name ? `<div class="sub">${esc(name)}</div>` : ''}</td>
      <td class="num">${esc(r.rs_percentile)}</td>
      <td class="num">-${esc(r.pct_below_52w_high)}%</td>
      <td class="num" style="color:${r.range_contraction < 1 ? 'var(--ok)' : 'var(--muted)'}">${contraction}</td>
      <td class="num" style="color:${r.volume_dryup < 1 ? 'var(--ok)' : 'var(--muted)'}">${dry}</td>
      <td class="num" style="color:${col(r.one_month_pct)}">${pct(r.one_month_pct)}</td>
      <td class="num" style="color:${col(r.three_month_pct)}">${pct(r.three_month_pct)}</td>
      <td class="num"><button type="button" class="ol-copy" data-copy="${esc(researchPrompt(r, name))}">調査文</button></td>
    </tr>`;
  }).join('');
  return `${controls}
    <div class="sub" style="margin:6px 0 10px">条件：RS ${RS_MIN}以上 ／ 52週高値から${OFF_HIGH_MAX}%以内 ／ 50日>150日>200日線${latest?.overall_trend_state !== 'correction' ? ' ／ 終値が50日線の上' : ''}。並び順：${esc(mode.sortLabel)}。該当 ${res.total} 銘柄中、上位 ${res.rows.length} 件。${res.excludedRegion ? `地域方針で除外 ${res.excludedRegion} 件。` : ''}${fftyNote}</div>
    ${res.rows.length ? `<div class="ol-table-wrap"><table class="ol-table"><thead><tr><th>銘柄</th><th class="num">RS</th><th class="num">高値から</th><th class="num" title="直近10日の平均値幅÷50日平均。1未満は値幅が縮んでいる">値幅収縮</th><th class="num" title="直近10日の平均出来高÷50日平均。1未満は出来高が細っている">出来高</th><th class="num">1M</th><th class="num">3M</th><th></th></tr></thead><tbody>${body}</tbody></table></div>` : '<div class="sub">条件に合う銘柄はありません。無理に候補を埋めません。</div>'}
    <div class="sub" style="margin-top:8px">値幅収縮・出来高は「土台が締まってきているか」の目安で、VCPやカップの形の判定ではありません。形はTradingViewのチャートで判断してください(銘柄名から開けます)。「調査文」は決算分析の質問文をコピーします。</div>`;
}

/* ---------- レーンA: 次のNVDA ---------- */

function laneA(latest, data) {
  if (!data) return '<div class="sub">データファイルを読み込めません。</div>';
  const sigRows = data.SIGNALS.map((s) => `<tr><td class="mono"><b>${esc(s.id)}</b></td><td>${esc(s.name)}</td><td>${esc(s.what)}</td><td class="sub">${esc(s.how)}</td></tr>`).join('');
  const rsw = latest?.rs_line_watch || {};
  const cards = data.CANDIDATES.map((c) => {
    const dots = data.SIGNALS.map((s) => {
      const on = c.lit.includes(s.id);
      return `<span class="nv-dot${on ? ' on' : ''}" title="${esc(s.id)} ${esc(s.name)}：${on ? '点灯' : '未点灯'}">${esc(s.id)}</span>`;
    }).join('');
    const rs = rsw[c.t];
    const s6 = rs
      ? `RSライン(対NASDAQ)：${rs.rs_line_new_high_52w ? '<b style="color:var(--ok)">52週新高値</b>' : `高値から -${esc(rs.rs_line_pct_below_high)}%`}、1か月 ${pct(rs.rs_line_1m_pct)}(${esc(rs.as_of)})`
      : 'RSライン(対NASDAQ)は次回の日次更新から';
    return `<div class="nv-card">
      <div class="nv-head"><a class="mono ol-ticker" href="${tv(c.t)}" target="_blank" rel="noopener">${esc(c.t)}</a><span class="sub">${esc(c.name)}</span><span class="badge muted">${esc(c.status)}</span></div>
      <div class="nv-dots">${dots}</div>
      <div class="nv-biz">${esc(c.biz)}</div>
      <div class="sub"><b>次に見る点：</b>${esc(c.watch)}</div>
      <div class="sub"><b>S6の補助：</b>${s6}。点灯はチャート確認後。</div>
    </div>`;
  }).join('');
  return `<div class="ol-table-wrap"><table class="nv-signals"><thead><tr><th>#</th><th>シグナル</th><th>何を見るか</th><th>確認手段</th></tr></thead><tbody>${sigRows}</tbody></table></div>
    <div class="sub" style="margin:6px 0 12px">判定ルール：${esc(data.RULE)}</div>
    <div class="nv-grid">${cards}</div>
    <div class="sub" style="margin-top:8px">点灯状況は${esc(data.BASE_DATE)}の基準状態。週次のスケジュール済みタスク(毎週月曜)で変化があれば、このページの表も更新します。</div>`;
}

/* ---------- レーンC: 動意銘柄 ---------- */

function laneC(latest, ctx) {
  const rows = (latest?.story_candidates || []).filter((r) => !(ctx.profiles?.get && ctx.profiles.get(r.ticker)?.status === 'excluded'));
  if (!rows.length) return '<div class="sub">本日は「市場比+2%以上・出来高20日平均の1.5倍以上」を満たす銘柄はありません。</div>';
  const body = rows.map((r) => `<tr>
    <td><a class="mono ol-ticker" href="${tv(r.ticker)}" target="_blank" rel="noopener">${esc(r.ticker)}</a></td>
    <td class="num" style="color:${col(r.day_change_pct)}">${pct(r.day_change_pct)}</td>
    <td class="num" style="color:${col(r.market_excess_pct)}">${pct(r.market_excess_pct)}</td>
    <td class="num">${esc(r.volume_ratio_20d)}倍</td>
    <td class="num" style="color:${col(r.one_month_pct)}">${pct(r.one_month_pct)}</td>
    <td class="num">${esc(r.rs_percentile)}</td>
  </tr>`).join('');
  return `<div class="ol-table-wrap"><table class="ol-table"><thead><tr><th>銘柄</th><th class="num">1D</th><th class="num">市場超過</th><th class="num">出来高/20日平均</th><th class="num">1M</th><th class="num">RS</th></tr></thead><tbody>${body}</tbody></table></div>
    <div class="sub" style="margin-top:8px">今日、出来高を伴って市場より強く動いた銘柄。上昇の理由は価格データからは分かりません。気になったものだけニュースで確認します。</div>`;
}

/* ---------- 画面 ---------- */

function render(target, latest, ctx) {
  if (!target) return;
  if (!latest) { target.innerHTML = '<div class="card"><div class="loading">データを読み込み中...</div></div>'; return; }
  let ladder = '', ladderOk;
  if (root.JiaiLadder) {
    const hist = ctx.history || [];
    const i = hist.findIndex((h) => h.date === latest.date);
    const prior = i > 0 ? hist[Math.max(0, i - 5)].data : null;
    const sum = root.JiaiLadder.summarize(root.JiaiLadder.evaluateGates(latest, prior));
    ladderOk = sum.ok;
    ladder = `地合い回復ラダー ${sum.ok}/${sum.total} 段クリア${sum.next ? `、次の関門は「${esc(sum.next.label)}」` : ''}`;
  }
  const mode = modeFor(latest, ladderOk);
  ctx.mode = mode;
  target.innerHTML = `
    <div class="card ol-mode ol-mode-${mode.cls}">
      <div class="card-title">いまの使い方(地合いに連動)</div>
      <div class="hero-state">「${esc(mode.name)}」モード</div>
      <div style="margin-bottom:6px">${esc(mode.text)}</div>
      <div class="sub">データ日 ${esc(latest.date)} ／ ${ladder}</div>
    </div>
    <div class="card"><div class="card-title">B. リーダー候補(O'Neil/ミネルヴィニ式・テクニカル)</div><div data-ol-lane="b">${laneB(latest, ctx)}</div></div>
    <div class="card"><div class="card-title">A. 次のNVDA(ストーリー監視：境シグナル S1〜S6)</div>${laneA(latest, root.NextNvdaData)}</div>
    <div class="card"><div class="card-title">C. 動意銘柄(出来高を伴って市場より強く動いた銘柄)</div>${laneC(latest, ctx)}</div>`;
  const rerender = () => { const box = target.querySelector('[data-ol-lane="b"]'); if (box) { box.innerHTML = laneB(latest, ctx); bind(); } };
  function bind() {
    const liq = target.querySelector('[data-ol="liq"]');
    if (liq) liq.onchange = () => { ctx.state.minDollarVolume = Number(liq.value); rerender(); };
    const ff = target.querySelector('[data-ol="ffty"]');
    if (ff) ff.onchange = () => { ctx.state.fftyOnly = ff.checked; rerender(); };
    const bd = target.querySelector('[data-ol="budget"]');
    if (bd) bd.onchange = () => { ctx.state.budgetOnly = bd.checked; rerender(); };
    target.querySelectorAll('[data-copy]').forEach((b) => {
      b.onclick = async () => {
        try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = 'コピー済み'; }
        catch { window.prompt('コピーしてください', b.dataset.copy); }
      };
    });
  }
  bind();
}

const api = { MODES, modeFor, leaderCandidates, researchPrompt, laneA, laneB, laneC, render, RS_MIN, OFF_HIGH_MAX };
if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
root.OpportunityLanes = api;

if (typeof document === 'undefined') return;
const ctx = { state: { minDollarVolume: 50e6, fftyOnly: false, budgetOnly: false }, ffty: null, history: null, profiles: root.IssuerProfiles || null };
function draw() { render(document.getElementById('op-lanes'), root.watchLatest, ctx); }
fetch('data/ffty_latest.json', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null).then((j) => { ctx.ffty = j; draw(); });
root.addEventListener('watch-data', () => { ctx.history = root.watchHistory || ctx.history; ctx.profiles = root.IssuerProfiles || ctx.profiles; draw(); });
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', draw); else draw();
})(typeof window !== 'undefined' ? window : globalThis);
