/* 外部環境パネル(2026-10-25追加)：FRBの政策金利・原油・インフレ。
   データは日次JSONの macro(FRED と yfinance)。目安線は公表値か計算値だけを使う:
     政策金利 … FOMC参加者の長期の政策金利見通し(中央値)＝中立金利の目安
     インフレ … FRBの物価目標2%(コアPCE)
     原油     … 公式の適正価格はないので、200日線と過去5年平均 */
(function (root) {
'use strict';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const r1 = (v) => (v === null || v === undefined || !Number.isFinite(Number(v)) ? null : Math.round(Number(v) * 10) / 10);
const r2 = (v) => (v === null || v === undefined || !Number.isFinite(Number(v)) ? null : Math.round(Number(v) * 100) / 100);
const signed = (v, suf = '') => (v === null ? '-' : `${v > 0 ? '+' : ''}${v}${suf}`);

function chart() { return root.JiaiLadder && root.JiaiLadder.priceChart; }

function policyBlock(pr) {
  const draw = chart();
  if (!pr || !pr.upper) return '<div class="sub">政策金利のデータを取得できませんでした(FRED)。次回の日次更新で再取得します。</div>';
  const lowerMap = new Map((pr.lower?.dates || []).map((d, i) => [d, pr.lower.values[i]]));
  const ch = { dates: pr.upper.dates, values: pr.upper.values, lower: pr.upper.dates.map((d) => lowerMap.get(d) ?? null) };
  const neutral = pr.longer_run_median;
  const mid = r2((pr.latest_upper + pr.latest_lower) / 2);
  const gap = neutral ? r2(mid - neutral.value) : null;
  const stance = gap === null ? '' : gap > 0 ? '中立の目安より上＝景気を冷やす側(引き締め的)' : gap < 0 ? '中立の目安より下＝景気を支える側(緩和的)' : '中立の目安と同じ水準';
  return `<div class="macro-head"><div class="macro-label">FRBの政策金利(誘導目標)</div>
      <div class="macro-value">${esc(pr.latest_lower)}〜${esc(pr.latest_upper)}%</div>
      <div class="sub">${esc(pr.as_of)}時点${neutral ? ` ／ 中立の目安 ${esc(neutral.value)}%(${esc(neutral.as_of)}のFOMC見通し)との差 ${signed(gap, 'pt')}` : ''}</div>
      ${stance ? `<div class="macro-read">${esc(stance)}</div>` : ''}</div>
    ${draw ? draw(ch, {
      aria: 'FRB政策金利の推移', width: 420, height: 220, step: true, mainColor: 'var(--err)',
      lines: [{ key: 'lower', color: 'var(--err)', dash: '2 3', width: 1.2, step: true, label: 'レンジ下限' }],
      refs: neutral ? [{ value: neutral.value, label: `中立金利の目安(FOMC長期見通し中央値 ${neutral.value}%)`, short: `中立 ${neutral.value}`, color: 'var(--pri)' }] : [],
      fmt: (v) => `${r1(v)}%`, dateFmt: (d) => d.slice(0, 7).replace('-', '/'), note: '実線＝上限',
    }) : ''}`;
}

function oilBlock(oil) {
  const draw = chart();
  const b = oil && (oil.brent || oil.wti);
  if (!b) return '<div class="sub">原油のデータを取得できませんでした。次回の日次更新で再取得します。</div>';
  const w = oil.wti;
  const vs5 = b.avg_5y ? r1(100 * (b.price / b.avg_5y - 1)) : null;
  const vs200 = b.sma200 ? r1(100 * (b.price / b.sma200 - 1)) : null;
  return `<div class="macro-head"><div class="macro-label">原油(${esc(b.label)})</div>
      <div class="macro-value">$${esc(b.price)}</div>
      <div class="sub">${esc(b.as_of)}時点 ／ 5年平均 $${esc(b.avg_5y)}(${signed(vs5, '%')}) ／ 200日線 $${esc(b.sma200)}(${signed(vs200, '%')})${w && w !== b ? ` ／ WTI $${esc(w.price)}` : ''}</div>
      <div class="macro-read">${vs5 === null ? '' : vs5 > 0 ? '5年平均より高い＝物価の押し上げ要因' : '5年平均より低い＝物価の押し下げ要因'}</div></div>
    ${draw ? draw(b.chart, {
      aria: '原油の日足ローソク', width: 420, height: 220,
      lines: [
        { key: 'sma50', color: 'var(--pri)', label: '50日線' },
        { key: 'sma200', color: 'var(--warn)', dash: '5 3', label: '200日線' },
      ],
      refs: [{ value: b.avg_5y, label: `過去5年平均 $${b.avg_5y}`, short: `5年平均`, color: 'var(--gold)' }],
      fmt: (v) => `$${Math.round(v)}`, note: '日足',
    }) : ''}`;
}

function inflationBlock(inf) {
  const draw = chart();
  if (!inf || !(inf.core_pce || inf.cpi)) return '<div class="sub">インフレ率のデータを取得できませんでした(FRED)。次回の日次更新で再取得します。</div>';
  const keys = ['core_pce', 'cpi', 'core_cpi'].filter((k) => inf[k]);
  const dates = [...new Set(keys.flatMap((k) => inf[k].dates))].sort();
  const pick = (k) => { const m = new Map((inf[k]?.dates || []).map((d, i) => [d, inf[k].values[i]])); return dates.map((d) => m.get(d) ?? null); };
  const mainKey = inf.core_pce ? 'core_pce' : 'cpi';
  const ch = { dates, values: pick(mainKey), cpi: pick('cpi'), core_cpi: pick('core_cpi') };
  const lines = [];
  if (mainKey !== 'cpi' && inf.cpi) lines.push({ key: 'cpi', color: 'var(--warn)', width: 1.3, label: `CPI総合(${inf.cpi.as_of} ${r1(inf.cpi.latest)}%)` });
  if (inf.core_cpi) lines.push({ key: 'core_cpi', color: 'var(--faint)', width: 1.3, dash: '4 3', label: `コアCPI(${inf.core_cpi.as_of} ${r1(inf.core_cpi.latest)}%)` });
  const main = inf[mainKey];
  const gap = r1(main.latest - inf.target_pct);
  return `<div class="macro-head"><div class="macro-label">インフレ率(前年同月比)</div>
      <div class="macro-value">${esc(r1(main.latest))}%<span class="sub" style="font-size:12px;font-weight:600"> ${mainKey === 'core_pce' ? 'コアPCE' : 'CPI総合'}(${esc(main.as_of)})</span></div>
      <div class="sub">FRBの目標 ${esc(inf.target_pct)}%(コアPCEで見る)との差 ${signed(gap, 'pt')}</div>
      <div class="macro-read">${gap > 0 ? '目標より高い＝利下げしにくい(利上げの議論が出やすい)' : '目標以下＝利下げの余地'}</div></div>
    ${draw ? draw(ch, {
      aria: 'インフレ率の推移', width: 420, height: 220, mainColor: 'var(--err)',
      lines,
      refs: [{ value: inf.target_pct, label: `FRBの物価目標 ${inf.target_pct}%`, short: '目標 2%', color: 'var(--ok)' }],
      fmt: (v) => `${r1(v)}%`, dateFmt: (d) => d.slice(0, 7).replace('-', '/'), note: `太線＝${mainKey === 'core_pce' ? 'コアPCE' : 'CPI総合'}`,
    }) : ''}`;
}

function linkage(m) {
  const pr = m.policy_rate, inf = m.inflation, oil = m.oil;
  const parts = [];
  if (pr && inf && inf.core_pce) {
    const mid = (pr.latest_upper + pr.latest_lower) / 2;
    const real = r2(mid - inf.core_pce.latest);
    parts.push(`実質政策金利(政策金利の中央 − コアPCE)は ${signed(real, '%')}。プラスが大きいほど、物価を差し引いても金融は引き締まっている。`);
  }
  if (oil && (oil.brent || oil.wti) && inf) {
    parts.push('原油はガソリン・輸送費を通じてCPI総合に先に効き、時間をおいてコアにも波及する。原油高が続くと、FRBは物価目標との差を縮めにくくなる。');
  }
  if (pr && pr.longer_run_median) {
    parts.push('政策金利が中立の目安より上にある間は、借入コストが高く、AI投資のように資金調達に頼る分野ほど重しになりやすい。');
  }
  return parts.length ? `<div class="macro-link"><b>3つのつながり：</b>${parts.map(esc).join(' ')}</div>` : '';
}

function render(latest) {
  const m = latest && latest.macro;
  if (!m) {
    return `<div class="card"><div class="card-title">外部環境(FRBの政策金利・原油・インフレ)</div><div class="sub">次回の日次更新から表示されます。</div></div>`;
  }
  return `<div class="card macro-card">
    <div class="card-title">外部環境(FRBの政策金利・原油・インフレ)</div>
    <div class="macro-grid">
      <div class="macro-cell">${policyBlock(m.policy_rate)}</div>
      <div class="macro-cell">${oilBlock(m.oil)}</div>
      <div class="macro-cell">${inflationBlock(m.inflation)}</div>
    </div>
    ${linkage(m)}
    ${m.fetch_errors && Object.keys(m.fetch_errors).length ? `<details class="guide" style="margin-top:var(--s3)"><summary>取得できなかったデータ(${Object.keys(m.fetch_errors).length}件)</summary><div class="guide-body">${Object.entries(m.fetch_errors).map(([k, v]) => `<div class="mono" style="font-size:11px">${esc(k)}：${esc(v)}</div>`).join('')}</div></details>` : ''}
    <div class="sub" style="margin-top:var(--s2)">出典：FRED(政策金利・FOMC見通し・CPI・PCE)、Yahoo Finance(原油先物)。前年同月比と実質金利は自前計算。原油の目安線は計算値で、適正価格の予想ではありません。</div>
  </div>`;
}

const api = { render, policyBlock, oilBlock, inflationBlock, linkage };
if (typeof module !== 'undefined' && module.exports) module.exports = api;
else root.MacroPanel = api;
})(typeof window !== 'undefined' ? window : globalThis);
