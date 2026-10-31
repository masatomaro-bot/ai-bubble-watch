/* 地合い回復ラダーと指数の階層(ステージ)パネル。2026-10-25追加。
   入力は日次JSON(latest.json / history/*.json)だけ。外部通信なし。 */
(function (root) {
'use strict';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v));
const signed = (v, suffix = '') => (v === null ? '-' : `${v > 0 ? '+' : ''}${v}${suffix}`);
const GROWTH_OK = new Set(['主導', '改善']);
const LOOKBACK = 5; // 「改善中」を判定する比較対象(営業日前)

/* ---------- 回復ラダー ---------- */

// 回復は一般に「外側が落ち着く→中身の悪化が止まる→指数が線を取り戻す→
// トレンド確認→リーダーが動く→主役が戻る→参加が広がる」の順に進みやすい。
// 順序は典型であって保証ではない。50%などの水準は自前の仮置き(要校正)。
const GATES = [
  { id: 'stress', label: '外側のストレスが落ち着く', target: 'VIXが10日前より低く、かつ直近10日平均以下 / HYG/IEF(信用)が10日前より高い' },
  { id: 'lows', label: '新安値の縮小が止まる', target: '新高値 ≥ 新安値(未達でも新安値が5日前より減っていれば一部)' },
  { id: 'index50', label: '指数が50日線を取り戻す', target: 'S&P500とNASDAQの終値が両方とも50日線の上' },
  { id: 'oneil', label: '上昇トレンドの確認', target: 'O\'Neil/IBD式で両指数が「上昇確認」' },
  { id: 'leaders', label: 'リーダーが崩れていない', target: 'RS上位20銘柄の過半が50日線の上(仮置き)' },
  { id: 'rotation', label: '主役(グロース)が戻る', target: '情報技術(XLK)と半導体(SOXX)が主導/改善、ディフェンシブ優位が消える' },
  { id: 'participation', label: '参加が広がる', target: '50日線上の銘柄が過半(仮置き)' },
];

function leaderShareAbove50(d) {
  const rows = (d.market_leaders || []).filter((r) => r.above_sma50 !== null && r.above_sma50 !== undefined);
  if (!rows.length) return null;
  return Math.round((100 * rows.filter((r) => r.above_sma50).length) / rows.length);
}

function evaluateGates(d, prior) {
  // prior: 比較用の過去データ(5営業日前程度)。なければ「改善中」の判定はしない。
  const p = prior || null;
  const out = [];
  const g = d.stress_gauges || {};
  const vixCh = num(g.vix?.change_10d);
  const vixLv = num(g.vix?.level);
  const vixAvg = num(g.vix?.avg_10d); // 古い履歴JSONには無い(null→従来判定)
  const credCh = num(g.credit_hyg_ief?.change_10d_pct);
  {
    // 10日前との1点比較だけだと、10日前が急騰日なら再上昇中でも「低下」になる。
    // 直近10日平均を上回っている間は落ち着いたと見なさない。
    const okVix = vixCh !== null && vixCh <= 0 && (vixAvg === null || vixLv === null || vixLv <= vixAvg);
    const okCred = credCh !== null && credCh >= 0;
    const status = vixCh === null && credCh === null ? 'na' : okVix && okCred ? 'ok' : okVix || okCred ? 'partial' : 'ng';
    out.push({ ...GATES[0], status, value: `VIX ${vixLv ?? '-'}(10日 ${signed(vixCh)}${vixAvg !== null ? ` / 10日平均 ${vixAvg}` : ''}) / 信用 ${signed(credCh, '%')}` });
  }
  {
    const ext = d.breadth_extended || {};
    const hi = num(ext.new_52w_highs), lo = num(ext.new_52w_lows);
    const loPrev = num(p?.breadth_extended?.new_52w_lows);
    let status = 'na';
    if (hi !== null && lo !== null) status = hi >= lo ? 'ok' : loPrev !== null && lo < loPrev ? 'partial' : 'ng';
    out.push({ ...GATES[1], status, value: `新高値 ${hi ?? '-'} / 新安値 ${lo ?? '-'}${loPrev !== null ? `(5日前の新安値 ${loPrev})` : ''}` });
  }
  {
    const a = d.sp500?.above_sma50, b = d.nasdaq?.above_sma50;
    const known = [a, b].filter((x) => x === true || x === false);
    const n = known.filter(Boolean).length;
    const status = known.length < 2 ? 'na' : n === 2 ? 'ok' : n === 1 ? 'partial' : 'ng';
    out.push({ ...GATES[2], status, value: `S&P500 ${a ? '上' : a === false ? '下' : '-'} / NASDAQ ${b ? '上' : b === false ? '下' : '-'}` });
  }
  {
    const s = d.overall_trend_state;
    const status = s === 'confirmed_uptrend' ? 'ok' : s === 'uptrend_under_pressure' ? 'partial' : s === 'correction' ? 'ng' : 'na';
    const lbl = { confirmed_uptrend: '上昇確認', uptrend_under_pressure: '圧力下', correction: '調整' };
    out.push({ ...GATES[3], status, value: `S&P500 ${lbl[d.sp500?.trend_state?.state] || '-'} / NASDAQ ${lbl[d.nasdaq?.trend_state?.state] || '-'}` });
  }
  {
    const share = leaderShareAbove50(d);
    const prev = p ? leaderShareAbove50(p) : null;
    let status = 'na';
    if (share !== null) status = share > 50 ? 'ok' : prev !== null && share > prev ? 'partial' : 'ng';
    out.push({ ...GATES[4], status, value: share === null ? '-' : `${share}%が50日線の上${prev !== null ? `(5日前 ${prev}%)` : ''}` });
  }
  {
    const xlk = d.sectors?.XLK?.quadrant, soxx = d.themes?.SOXX?.quadrant;
    const def = (d.warning_flags || []).find((f) => f.id === 'defensive_rotation');
    const checks = [GROWTH_OK.has(xlk), GROWTH_OK.has(soxx), def ? !def.active : null].filter((x) => x !== null);
    const n = checks.filter(Boolean).length;
    const status = !xlk && !soxx ? 'na' : n === checks.length ? 'ok' : n > 0 ? 'partial' : 'ng';
    out.push({ ...GATES[5], status, value: `XLK ${xlk || '-'} / SOXX ${soxx || '-'} / ディフェンシブ優位 ${def ? (def.active ? 'あり' : 'なし') : '-'}` });
  }
  {
    const v = num(d.broad_universe_technicals?.pct_above_50dma);
    const prev = num(p?.broad_universe_technicals?.pct_above_50dma);
    let status = 'na';
    if (v !== null) status = v > 50 ? 'ok' : prev !== null && v > prev ? 'partial' : 'ng';
    out.push({ ...GATES[6], status, value: v === null ? '-' : `${v}%${prev !== null ? `(5日前 ${prev}%)` : ''}` });
  }
  return out;
}

function priorFor(history, idx) {
  if (!history || idx <= 0) return null;
  return history[Math.max(0, idx - LOOKBACK)].data;
}

function summarize(gates) {
  return {
    ok: gates.filter((g) => g.status === 'ok').length,
    partial: gates.filter((g) => g.status === 'partial').length,
    total: gates.length,
    next: gates.find((g) => g.status !== 'ok') || null,
  };
}

const STATUS_STYLE = {
  ok: { label: 'クリア', color: 'var(--ok)', bg: 'var(--ok-h)' },
  partial: { label: '一部', color: 'var(--gold)', bg: 'var(--gold-h)' },
  ng: { label: '未達', color: 'var(--err)', bg: 'var(--err-h)' },
  na: { label: 'データなし', color: 'var(--muted)', bg: 'var(--off)' },
};

function ladderPanel(latest, history) {
  const idx = history ? history.findIndex((h) => h.date === latest.date) : -1;
  const gates = evaluateGates(latest, priorFor(history, idx));
  const sum = summarize(gates);
  const rows = gates.slice().reverse().map((g, revI) => {
    const step = gates.length - revI; // 7..1
    const st = STATUS_STYLE[g.status];
    const isNext = sum.next && sum.next.id === g.id;
    return `<div class="ladder-row${isNext ? ' is-next' : ''}" style="--indent:${(step - 1) * 4}%">
      <div class="ladder-step" style="background:${st.bg};border-color:${st.color}">
        <span class="ladder-num">${step}</span>
        <div class="ladder-text">
          <div class="ladder-label">${esc(g.label)}${isNext ? ' <span class="ladder-next">次の関門</span>' : ''}</div>
          <div class="ladder-value">${esc(g.value)}</div>
          <div class="ladder-target">クリア条件：${esc(g.target)}</div>
        </div>
        <span class="ladder-status" style="color:${st.color}">${st.label}</span>
      </div>
    </div>`;
  }).join('');
  return `
    <div class="ladder-head">
      <div class="hero-state" style="margin:0">${sum.ok} / ${sum.total} 段クリア${sum.partial ? `<span class="sub" style="font-size:13px;font-weight:600"> (一部 ${sum.partial})</span>` : ''}</div>
      <div class="sub">下から順に埋まるほど地合いが良い。${sum.next ? `いま越えるべき関門は「${esc(sum.next.label)}」。` : 'すべての関門をクリア。'}</div>
    </div>
    <div class="ladder">${rows}</div>
    <div id="ladder-history"></div>
    <div class="sub" style="margin-top:var(--s3)">関門の順番は回復局面で典型的な順序で、必ずこの順に進むわけではない。「過半(50%)」の水準は自前の仮置きで、過去データでの校正は未実施。</div>`;
}

function ladderHistory(history) {
  if (!history || history.length < 2) return '';
  const counts = history.map((h, i) => ({ date: h.date, ...summarize(evaluateGates(h.data, priorFor(history, i))) }));
  const bars = counts.map((c) => {
    const h = Math.max(4, Math.round((c.ok / c.total) * 44));
    const color = c.ok >= 5 ? 'var(--ok)' : c.ok >= 3 ? 'var(--gold)' : 'var(--err)';
    return `<div class="ladder-hbar" title="${esc(c.date)}: ${c.ok}/${c.total}段クリア(一部${c.partial})"><span style="height:${h}px;background:${color}"></span></div>`;
  }).join('');
  return `<div class="ladder-hist">
    <div class="sub" style="margin-bottom:4px">クリア段数の推移(直近${counts.length}営業日)</div>
    <div class="ladder-hbars">${bars}</div>
    <div class="mini-trend-caption"><span>${esc(counts[0].date)}</span><span>${esc(counts[counts.length - 1].date)}</span></div>
  </div>`;
}

/* ---------- 指数の階層(ステージ分析) ---------- */

// パイプラインが stage を出していない古いJSONでも表示できるよう、同じ規則を
// 画面側にも持つ(market_climate.classify_weinstein_stage と同一の判定)。
function classifyStage(i) {
  const p = num(i.price), s50 = num(i.sma50), s150 = num(i.sma150), s200 = num(i.sma200);
  if ([p, s50, s150, s200].some((v) => v === null)) return { stage: null, stage_label: '不明', stage_sub: null };
  const above = p > s150 && p > s200, below = p < s150 && p < s200, up = s150 > s200;
  if (above && up && i.sma200_rising) return { stage: 2, stage_label: 'Stage 2 上昇', stage_sub: p > s50 ? '本流' : '押し目' };
  if (below && !up) return { stage: 4, stage_label: 'Stage 4 下落', stage_sub: null };
  if (up) return { stage: 3, stage_label: 'Stage 3 天井圏', stage_sub: null };
  return { stage: 1, stage_label: 'Stage 1 底固め', stage_sub: null };
}

function stageOf(i) {
  return i && i.stage !== undefined && i.stage_label ? { stage: i.stage, stage_label: i.stage_label, stage_sub: i.stage_sub } : classifyStage(i || {});
}

const STAGE_DESC = {
  1: '下げ止まって横ばい。200日線が平らになり、売りが一巡するのを待つ段階。',
  2: '移動平均が上向きに並ぶ上昇局面。O\'Neil/ミネルヴィニ流で買いを狙うのはこの段階だけ。',
  3: '上昇の並びは残るが、値動きが荒れて200日線の勢いが落ちる天井圏。',
  4: '移動平均が下向きに並ぶ下落局面。買いの対象外。',
};

function stageStairs(stage, sub) {
  // ワインスタインの4段階を、底→上昇→天井→下落の山形で描き、現在地に印をつける。
  const pts = { 1: [50, 150], 2: [170, 91], 3: [300, 40], 4: [430, 110] };
  const seg = (a, b, s) => `<path d="M${a[0]},${a[1]} L${b[0]},${b[1]}" stroke="${s === stage ? 'var(--pri)' : 'var(--bdr)'}" stroke-width="${s === stage ? 7 : 4}" stroke-linecap="round" fill="none"/>`;
  const p1a = [10, 150], p1b = [90, 150], p2b = [240, 40], p3b = [360, 40], p4b = [470, 150];
  const marker = stage === 2 ? (sub === '押し目' ? [190, 77] : [225, 51]) : stage ? pts[stage] : null;
  const label = (x, s, t) => `<text x="${x}" y="182" text-anchor="middle" font-size="12" font-weight="${s === stage ? 800 : 500}" fill="${s === stage ? 'var(--pri)' : 'var(--muted)'}">${t}</text>`;
  return `<svg class="stage-svg" viewBox="0 0 480 190" role="img" aria-label="ステージの現在地">
    ${seg(p1a, p1b, 1)}${seg(p1b, p2b, 2)}${seg(p2b, p3b, 3)}${seg(p3b, p4b, 4)}
    ${label(50, 1, 'Stage 1 底固め')}${label(165, 2, 'Stage 2 上昇')}${label(300, 3, 'Stage 3 天井圏')}${label(430, 4, 'Stage 4 下落')}
    ${marker ? `<circle cx="${marker[0]}" cy="${marker[1]}" r="10" fill="var(--pri)" stroke="var(--surf)" stroke-width="3"/><text x="${marker[0] > 380 ? marker[0] - 16 : marker[0] + 16}" y="${marker[1] + 5}" text-anchor="${marker[0] > 380 ? 'end' : 'start'}" font-size="13" font-weight="800" fill="var(--pri)">いまここ</text>` : ''}
  </svg>`;
}

// 汎用のローソク足/折れ線チャート。lines: 重ねる系列、refs: 水平の目安線。
//   lines: [{key, color, dash, label}]  refs: [{value, label, color, dash}]
function priceChart(ch, opts) {
  const o = opts || {};
  const lines = o.lines || [];
  const refs = (o.refs || []).filter((r) => r && r.value !== null && r.value !== undefined && Number.isFinite(Number(r.value)));
  const candle = Array.isArray(ch?.o) && Array.isArray(ch?.h);
  const main = candle ? ch.c : (ch?.values || null);
  if (!ch || !Array.isArray(main) || main.length < 5) return `<div class="sub">${esc(o.empty || 'チャートは次回の日次更新から表示されます。')}</div>`;
  const n = main.length, W = o.width || 640, H = o.height || 230, padL = 4, padR = 54, padT = 10, padB = 18;
  const vals = [...(candle ? [...ch.h, ...ch.l] : main), ...lines.flatMap((l) => ch[l.key] || []), ...refs.map((r) => Number(r.value))]
    .filter((v) => v !== null && v !== undefined && Number.isFinite(Number(v)));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (o.zeroBase && lo > 0) lo = 0;
  const pad = (hi - lo) * 0.04 || 1; lo -= pad; hi += pad;
  const rng = hi - lo || 1;
  const x = (i) => padL + ((W - padL - padR) * (i + 0.5)) / n;
  const y = (v) => padT + (H - padT - padB) * (1 - (v - lo) / rng);
  const bw = Math.max(1.2, ((W - padL - padR) / n) * 0.6);
  const poly = (arr, color, dash, width, step) => {
    if (!arr) return '';
    const segs = []; let cur = []; let prevY = null;
    arr.forEach((v, i) => {
      if (v === null || v === undefined) { if (cur.length) segs.push(cur); cur = []; prevY = null; return; }
      const yy = y(v).toFixed(1);
      if (step && prevY !== null && prevY !== yy) cur.push(`${x(i).toFixed(1)},${prevY}`);
      cur.push(`${x(i).toFixed(1)},${yy}`); prevY = yy;
    });
    if (cur.length) segs.push(cur);
    return segs.map((sg) => `<polyline points="${sg.join(' ')}" fill="none" stroke="${color}" stroke-width="${width || 1.6}" stroke-linejoin="round"${dash ? ` stroke-dasharray="${dash}"` : ''}/>`).join('');
  };
  let body = '';
  if (candle) {
    body = ch.c.map((c, i) => {
      const op = ch.o[i], h = ch.h[i], l = ch.l[i];
      if ([op, h, l, c].some((v) => v === null || v === undefined)) return '';
      const up = c >= op, col = up ? 'var(--ok)' : 'var(--err)';
      const top = y(Math.max(op, c)), bot = y(Math.min(op, c));
      return `<line x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}" y1="${y(h).toFixed(1)}" y2="${y(l).toFixed(1)}" stroke="${col}" stroke-width="1"/>` +
        `<rect x="${(x(i) - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, bot - top).toFixed(1)}" fill="${up ? 'var(--surf)' : col}" stroke="${col}" stroke-width="1"/>`;
    }).join('');
  } else {
    body = poly(main, o.mainColor || 'var(--pri)', null, 2.2, o.step);
  }
  const overlay = lines.map((l) => poly(ch[l.key], l.color, l.dash, l.width, l.step)).join('');
  const refSvg = refs.map((r) => {
    const yy = y(Number(r.value)).toFixed(1);
    return `<line x1="${padL}" x2="${W - padR}" y1="${yy}" y2="${yy}" stroke="${r.color || 'var(--gold)'}" stroke-width="1.4" stroke-dasharray="${r.dash || '6 4'}"/>` +
      `<text x="${W - padR + 4}" y="${(Number(yy) + 4).toFixed(1)}" font-size="10.5" font-weight="700" fill="${r.color || 'var(--gold)'}">${esc(r.short || '')}</text>`;
  }).join('');
  const fmt = o.fmt || ((v) => Math.round(v).toLocaleString('en-US'));
  const ticks = [hi - pad, (hi + lo) / 2, lo + pad].map((v) => `<text x="${W - padR + 4}" y="${(y(v) + 4).toFixed(1)}" font-size="10" fill="var(--muted)">${esc(fmt(v))}</text>`).join('');
  const dates = ch.dates || [];
  const dl = (i) => (dates[i] ? `<text x="${x(i).toFixed(1)}" y="${H - 4}" font-size="10" text-anchor="middle" fill="var(--muted)">${esc(o.dateFmt ? o.dateFmt(dates[i]) : dates[i].slice(5))}</text>` : '');
  const legend = [
    ...lines.map((l) => `<span><span class="dot" style="background:${l.color}"></span>${esc(l.label)}</span>`),
    ...refs.map((r) => `<span><span class="dot" style="background:${r.color || 'var(--gold)'}"></span>${esc(r.label)}</span>`),
    o.note ? `<span>${esc(o.note)}</span>` : '',
  ].join('');
  return `<svg class="candle-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || 'チャート')}">
    ${refSvg}${body}${overlay}${ticks}${dl(0)}${dl(Math.floor(n / 2))}${dl(n - 1)}
  </svg>${legend ? `<div class="legend" style="margin-top:4px">${legend}</div>` : ''}`;
}

function candleSvg(ch) {
  return priceChart(ch, {
    empty: 'ローソク足は次回の日次更新から表示されます。',
    aria: '日足ローソクと移動平均',
    lines: [
      { key: 'sma50', color: 'var(--pri)', label: '50日線' },
      { key: 'sma150', color: 'var(--gold)', label: '150日線' },
      { key: 'sma200', color: 'var(--warn)', dash: '5 3', label: '200日線(破線)' },
    ],
    note: ch && ch.c ? `直近${ch.c.length}営業日` : '',
  });
}

const WEEKLY_LEVEL = {
  warning: { color: 'var(--err)', bg: 'var(--err-h)' },
  watch: { color: 'var(--gold)', bg: 'var(--gold-h)' },
  none: { color: 'var(--ok)', bg: 'var(--ok-h)' },
};

function weeklyBlock(i) {
  const w = i && i.weekly;
  if (!w) return '<div class="weekly-block"><div class="sub">週足(30週線)のStage 3警戒は次回の日次更新から表示されます。</div></div>';
  const lv = WEEKLY_LEVEL[w.level] || WEEKLY_LEVEL.none;
  const ck = w.checks || {};
  const mark = (b) => (b ? '<b style="color:var(--err);font-size:14px">点灯</b>' : '<span class="sub">-</span>');
  const rows = [
    ['週足終値が30週線の下', ck.below_ma30w],
    ['30週線が4週前より上がっていない(平ら〜下向き)', ck.ma30w_not_rising],
    ['高値更新のない週が8週以上(仮置き)', ck.no_new_high_8w],
    ['30週線との距離が1%以内(仮置き)', ck.near_ma30w],
  ];
  return `<div class="weekly-block">
    <div class="weekly-head"><span class="weekly-badge" style="color:${lv.color};background:${lv.bg};border-color:${lv.color}">週足：${esc(w.label)}</span>
      <span class="sub">週足終値 ${esc(w.weekly_close)} ／ 30週線 ${esc(w.ma30w)}(${signed(num(w.pct_vs_ma30w), '%')}) ／ 30週線の4週変化 ${signed(num(w.ma30w_change_4w_pct), '%')} ／ 高値から${esc(w.weeks_since_high)}週</span></div>
    ${priceChart(w.chart, {
      aria: '週足ローソクと30週線', height: 200,
      lines: [{ key: 'ma30w', color: 'var(--pri)', width: 2, label: '30週線' }],
      note: w.chart ? `直近${w.chart.c.length}週` : '',
      dateFmt: (d) => d.slice(2, 7).replace('-', '/'),
    })}
    <table class="stage-checks"><tbody>${rows.map(([t, b]) => `<tr><td>${esc(t)}</td><td class="num">${mark(b)}</td></tr>`).join('')}</tbody></table>
  </div>`;
}

function stageChecks(i) {
  const p = num(i.price), s50 = num(i.sma50), s150 = num(i.sma150), s200 = num(i.sma200);
  const yes = (b) => (b === null || b === undefined ? '<span class="sub">-</span>' : b ? '<b style="color:var(--ok);font-size:14px">○</b>' : '<b style="color:var(--err);font-size:14px">×</b>');
  const rows = [
    ['終値が150日線・200日線の上', p !== null && s150 !== null && s200 !== null ? p > s150 && p > s200 : null],
    ['150日線が200日線の上', s150 !== null && s200 !== null ? s150 > s200 : null],
    ['200日線が1か月前より上向き', i.sma200_rising],
    ['50日線が150日・200日線の上', s50 !== null && s150 !== null && s200 !== null ? s50 > s150 && s50 > s200 : null],
    ['終値が50日線の上', p !== null && s50 !== null ? p > s50 : null],
    ['52週高値から25%以内', num(i.pct_below_52w_high) !== null ? num(i.pct_below_52w_high) <= 25 : null],
  ];
  return `<table class="stage-checks"><tbody>${rows.map(([t, b]) => `<tr><td>${esc(t)}</td><td class="num">${yes(b)}</td></tr>`).join('')}</tbody></table>
    <div class="sub">高値から −${num(i.pct_below_52w_high) ?? '-'}%${num(i.pct_above_52w_low) !== null ? ` ／ 52週安値から +${num(i.pct_above_52w_low)}%` : ''}${num(i.pct_vs_sma200) !== null ? ` ／ 200日線から ${signed(num(i.pct_vs_sma200), '%')}` : ''}</div>`;
}

function stageCard(name, i, tvSymbol) {
  if (!i) return '';
  const st = stageOf(i);
  return `<div class="card stage-card">
    <div class="stage-top">
      <div>
        <div class="card-title" style="margin-bottom:6px">${esc(name)}</div>
        <div class="hero-state" style="margin-bottom:2px">${esc(st.stage_label)}${st.stage_sub ? `<span class="stage-sub">・${esc(st.stage_sub)}</span>` : ''}</div>
        ${i.weekly && i.weekly.level !== 'none' ? `<span class="weekly-badge" style="color:${(WEEKLY_LEVEL[i.weekly.level] || WEEKLY_LEVEL.none).color};background:${(WEEKLY_LEVEL[i.weekly.level] || WEEKLY_LEVEL.none).bg};border-color:${(WEEKLY_LEVEL[i.weekly.level] || WEEKLY_LEVEL.none).color};display:inline-block;margin:4px 0">週足：${esc(i.weekly.label)}</span>` : ''}
        <div class="sub">${esc(STAGE_DESC[st.stage] || '判定材料が不足しています。')}</div>
      </div>
      ${tvSymbol ? `<a class="btn-link" href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvSymbol)}" target="_blank" rel="noopener">TradingView ↗</a>` : ''}
    </div>
    ${stageStairs(st.stage, st.stage_sub)}
    <div class="stage-sec">日足(50・150・200日線の並び)</div>
    ${candleSvg(i.chart)}
    ${stageChecks(i)}
    <div class="stage-sec">週足(30週線)：Stage 3の早期警戒</div>
    ${weeklyBlock(i)}
  </div>`;
}

function stagePanel(latest) {
  const ew = latest.equal_weight;
  return `<div class="grid2">
      ${stageCard('S&P500', latest.sp500, 'SP:SPX')}
      ${stageCard('NASDAQ総合', latest.nasdaq, 'NASDAQ:IXIC')}
    </div>
    ${ew ? `<div class="grid2">${stageCard('S&P500均等加重(RSP)— 中小型も含めた「平均的な銘柄」', ew, 'AMEX:RSP')}<div class="card"><div class="card-title">階層の読み方</div>
      <div class="sub" style="font-size:12.5px;line-height:1.7">ステージ分析はワインスタインが体系化し、ミネルヴィニが買いの前提に使う考え方です。判定は移動平均の並びだけで機械的に行う近似で、本来はチャートの形を見て決めます。<br>
      ・指数がStage 2でも、均等加重(RSP)が弱ければ「一部の大型株だけの相場」。<br>
      ・Stage 2の「押し目」は50日線割れ。上昇の並びが保たれていれば調整の範囲内です。<br>
      ・日足の並びは崩れるのが遅いので、天井(Stage 3)の入口は週足で見ます。ワインスタインの見方では、30週線の上昇が止まって平らになり、週足が30週線の上下を行き来し始めたらStage 3です。各カード下段の「週足：…」がその警戒表示です。</div></div></div>` : ''}`;
}

const api = { evaluateGates, summarize, ladderPanel, ladderHistory, classifyStage, stageOf, stagePanel, candleSvg, priceChart, weeklyBlock, GATES };
if (typeof module !== 'undefined' && module.exports) module.exports = api;
else root.JiaiLadder = api;
})(typeof window !== 'undefined' ? window : globalThis);
