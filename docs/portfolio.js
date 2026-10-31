// ポートフォリオウォッチ (2026-10-31)
// 保有銘柄のPERが、過去5年の自分自身の範囲のどこにいるかを表示する。
// データ: docs/data/per_watch.json (各週の終値 ÷ その週が属する会計年度の確定EPS)。
// 使い道: コア株の「織り込み上限 → 部分利確」の上限値の候補(上位10%)、下値の目処(下位10%)、
//         「EPSは伸びているのにPERが縮む」警報。短期の売買タイミングには使わない。
(function () {
  const root = document.getElementById('portfolio');
  if (!root) return;
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const f1 = (v) => (v == null || !isFinite(v) ? '-' : Number(v).toFixed(1));

  function zone(h) {
    const p = Number(h.percentile_now);
    if (p <= 15) return { label: '下限付近', cls: 'ok' };
    if (p >= 85) return { label: '上限付近', cls: 'warn' };
    if (p < 40) return { label: '中央より下', cls: 'muted' };
    if (p > 60) return { label: '中央より上', cls: 'muted' };
    return { label: '中央', cls: 'muted' };
  }

  function chart(h) {
    const W = 640, H = 230, m = { t: 10, r: 92, b: 24, l: 36 };
    const rows = h.series.map(([d, per, lo, hi]) => ({ t: Date.parse(d), per, lo, hi })).filter((r) => isFinite(r.t));
    if (!rows.length) return '';
    const vals = rows.flatMap((r) => [r.per, r.lo, r.hi]).filter((v) => v != null && v > 0).concat([h.p10, h.p90]);
    const lmin = Math.log(Math.min(...vals) * 0.9), lmax = Math.log(Math.max(...vals) * 1.1);
    const t0 = rows[0].t, t1 = rows[rows.length - 1].t;
    const x = (t) => m.l + (t - t0) / (t1 - t0) * (W - m.l - m.r);
    const y = (v) => H - m.b - (Math.log(v) - lmin) / (lmax - lmin) * (H - m.t - m.b);
    const line = (pts) => pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('');
    // 実績PER(確定年度)
    const segs = []; let cur = [];
    for (const r of rows) { if (r.per != null && r.per > 0) cur.push([x(r.t), y(r.per)]); else if (cur.length) { segs.push(cur); cur = []; } }
    if (cur.length) segs.push(cur);
    // 直近期の帯
    const band = rows.filter((r) => r.lo != null && r.hi != null);
    const area = band.length ? line(band.map((r) => [x(r.t), y(r.hi)])) + band.slice().reverse().map((r) => `L${x(r.t).toFixed(1)},${y(r.lo).toFixed(1)}`).join('') + 'Z' : '';
    const mid = band.length ? line(band.map((r) => [x(r.t), y((r.lo + r.hi) / 2)])) : '';
    // 目盛
    const ticks = [];
    for (const base of [1, 1.5, 2, 3, 5, 7]) for (let e = -1; e <= 3; e++) { const v = base * 10 ** e; if (Math.log(v) >= lmin && Math.log(v) <= lmax) ticks.push(v); }
    ticks.sort((a, b) => a - b);
    const years = [];
    for (let yr = new Date(t0).getUTCFullYear() + 1; yr <= new Date(t1).getUTCFullYear(); yr++) years.push(yr);
    // 基準線ラベルの重なりを避ける
    const refs = [
      { v: h.p10, lab: '下位10%', c: 'var(--ok)' },
      { v: h.p50, lab: '中央', c: 'var(--muted)' },
      { v: h.p90, lab: '上位10%', c: 'var(--warn)' },
    ].map((r) => ({ ...r, ly: y(r.v) })).sort((a, b) => b.ly - a.ly);
    for (let i = 1; i < refs.length; i++) if (refs[i - 1].ly - refs[i].ly < 13) refs[i].ly = refs[i - 1].ly - 13;
    return `<svg class="pf-chart" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(h.ticker)} のPERの推移">
      ${ticks.map((v) => `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" class="pf-gl"/><text x="${m.l - 5}" y="${y(v)}" dy="0.32em" text-anchor="end" class="pf-tick">${v}</text>`).join('')}
      ${years.map((yr) => { const xx = x(Date.UTC(yr, 0, 1)); return `<line x1="${xx}" x2="${xx}" y1="${m.t}" y2="${H - m.b}" class="pf-gl"/><text x="${xx}" y="${H - 6}" text-anchor="middle" class="pf-tick">${yr}</text>`; }).join('')}
      ${area ? `<path d="${area}" class="pf-band"/><path d="${mid}" class="pf-mid"/>` : ''}
      ${segs.map((s) => `<path d="${line(s)}" class="pf-line"/>`).join('')}
      ${refs.map((r) => `<line x1="${m.l}" x2="${W - m.r}" y1="${y(r.v)}" y2="${y(r.v)}" stroke="${r.c}" stroke-dasharray="4 3"/><text x="${W - m.r + 5}" y="${r.ly}" dy="0.32em" fill="${r.c}" class="pf-tick">${r.lab} ${f1(r.v)}</text>`).join('')}
    </svg>`;
  }

  function card(h) {
    const z = zone(h);
    return `<div class="card pf-card" id="pf-${esc(h.ticker)}">
      <div class="pf-head">
        <div><div class="story-ticker">${esc(h.ticker)}</div><div class="sub">${esc(h.name)}・${esc(h.role)}</div></div>
        <div class="pf-now"><span class="pf-big mono">${esc(h.per_now)}</span><span class="sub">倍</span> <span class="badge ${z.cls}">${z.label}</span></div>
      </div>
      <div class="story-metrics pf-metrics">
        <div class="story-metric"><span>下位10%（下値の目処）</span><strong>${f1(h.p10)}倍 / ${esc(h.price_floor)}</strong></div>
        <div class="story-metric"><span>中央</span><strong>${f1(h.p50)}倍 / ${esc(h.price_mid)}</strong></div>
        <div class="story-metric"><span>上位10%（部分利確の上限候補）</span><strong>${f1(h.p90)}倍 / ${esc(h.price_cap)}</strong></div>
        <div class="story-metric"><span>過去5年の位置・株価</span><strong>下から${esc(h.percentile_now)}% / ${esc(h.price)} ${esc(h.currency)}</strong></div>
      </div>
      ${chart(h)}
      <div class="story-note">${esc(h.eps_basis)}</div>
    </div>`;
  }

  // 来年度の予想EPS × 過去のPER帯 ＝ 株価の枠（週足ローソク＋10週・40週線）
  const BAND_COLOR = { '最低': 'var(--faint)', '下位10%': 'var(--ok)', '中央': 'var(--muted)', '上位10%': 'var(--warn)', '最高': 'var(--err)' };
  function frameZone(h) {
    const f = h.frame, p = Number(h.price);
    const bs = f.bands;
    for (let i = bs.length - 1; i >= 0; i--) if (p >= bs[i].lo) {
      if (p <= bs[i].hi) return `${bs[i].name}の帯の中`;
      return i === bs.length - 1 ? '最高の帯より上' : `${bs[i].name}と${bs[i + 1].name}の間`;
    }
    return '最低の帯より下';
  }
  function frameChart(h) {
    const f = h.frame, w = h.weekly || [];
    if (!f || !w.length) return '';
    const W = 640, H = 300, m = { t: 10, r: 112, b: 24, l: 44 };
    const bars = w.map(([d, o, hi, lo, c, a10, a40]) => ({ t: Date.parse(d), o, hi, lo, c, a10, a40 }));
    const price = bars.map((b) => [b.hi, b.lo]).flat();
    const pmin = Math.min(...price), pmax = Math.max(...price);
    // 表示範囲：値動きの範囲＋その近くの帯（遠すぎる帯は端に「↑」で示す）
    let ymin = pmin * 0.85, ymax = pmax * 1.15;
    for (const b of f.bands) { if (b.hi >= ymin * 0.9 && b.lo <= ymax * 1.25) { ymin = Math.min(ymin, b.lo * 0.97); ymax = Math.max(ymax, b.hi * 1.03); } }
    // 値動きの上下で一番近い帯は、離れていても必ず表示する（どこまで距離があるかを見るため）
    const upN = f.bands.filter((b) => b.lo > pmax).sort((a, b) => a.lo - b.lo)[0];
    const dnN = f.bands.filter((b) => b.hi < pmin).sort((a, b) => b.hi - a.hi)[0];
    if (upN) ymax = Math.max(ymax, upN.hi * 1.03);
    if (dnN) ymin = Math.min(ymin, dnN.lo * 0.97);
    const lmin = Math.log(ymin), lmax = Math.log(ymax);
    const y = (v) => H - m.b - (Math.log(v) - lmin) / (lmax - lmin) * (H - m.t - m.b);
    const n = bars.length, bw = (W - m.l - m.r) / n;
    const x = (i) => m.l + bw * (i + 0.5);
    const clamp = (v) => Math.max(m.t, Math.min(H - m.b, v));
    const ticks = [];
    for (const base of [1, 1.5, 2, 3, 5, 7]) for (let e = -1; e <= 4; e++) { const v = base * 10 ** e; if (v >= ymin && v <= ymax) ticks.push(v); }
    ticks.sort((a, b) => a - b);
    const quarters = [];
    bars.forEach((b, i) => { const dt = new Date(b.t); if (dt.getUTCDate() <= 7 && [0, 3, 6, 9].includes(dt.getUTCMonth())) quarters.push([i, `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, '0')}`]); });
    const line = (key) => { let d = ''; bars.forEach((b, i) => { if (b[key] == null) return; d += `${d ? 'L' : 'M'}${x(i).toFixed(1)},${y(b[key]).toFixed(1)}`; }); return d; };
    const bandsIn = f.bands.filter((b) => b.hi >= ymin && b.lo <= ymax);
    const above = f.bands.filter((b) => b.lo > ymax), below = f.bands.filter((b) => b.hi < ymin);
    const labs = bandsIn.map((b) => ({ ...b, ly: (clamp(y(b.lo)) + clamp(y(b.hi))) / 2 })).sort((a, b) => b.ly - a.ly);
    for (let i = 1; i < labs.length; i++) if (labs[i - 1].ly - labs[i].ly < 22) labs[i].ly = labs[i - 1].ly - 22;
    const fmt = (v) => (v >= 100 ? Math.round(v) : v.toFixed(1));
    const last = bars[n - 1];
    return `<svg class="pf-chart" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(h.ticker)} の株価と予想PERの枠">
      ${bandsIn.map((b) => `<rect x="${m.l}" width="${W - m.l - m.r}" y="${clamp(y(b.hi))}" height="${Math.max(2, clamp(y(b.lo)) - clamp(y(b.hi)))}" fill="${BAND_COLOR[b.name]}" opacity=".18"/>`).join('')}
      ${ticks.map((v) => `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" class="pf-gl"/><text x="${m.l - 5}" y="${y(v)}" dy="0.32em" text-anchor="end" class="pf-tick">${v}</text>`).join('')}
      ${quarters.map(([i, lab]) => `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" class="pf-tick">${lab}</text>`).join('')}
      ${bars.map((b, i) => { const up = b.c >= b.o, col = up ? 'var(--ok)' : 'var(--err)'; const top = y(Math.max(b.o, b.c)), bot = y(Math.min(b.o, b.c)); return `<line x1="${x(i)}" x2="${x(i)}" y1="${y(b.hi)}" y2="${y(b.lo)}" stroke="${col}" stroke-width="1"/><rect x="${x(i) - bw * 0.35}" width="${bw * 0.7}" y="${top}" height="${Math.max(1, bot - top)}" fill="${col}"/>`; }).join('')}
      <path d="${line('a10')}" fill="none" stroke="var(--pri)" stroke-width="1.3"/>
      <path d="${line('a40')}" fill="none" stroke="#8e24aa" stroke-width="1.3"/>
      <line x1="${m.l}" x2="${W - m.r}" y1="${y(last.c)}" y2="${y(last.c)}" stroke="var(--tx)" stroke-dasharray="2 3"/>
      ${labs.map((b) => `<text x="${W - m.r + 5}" y="${b.ly - 5}" fill="${BAND_COLOR[b.name]}" class="pf-tick pf-bl">${b.name} ${b.mult}倍</text><text x="${W - m.r + 5}" y="${b.ly + 7}" fill="${BAND_COLOR[b.name]}" class="pf-tick">${fmt(b.lo)}${b.lo !== b.hi ? '〜' + fmt(b.hi) : ''}</text>`).join('')}
      ${above.length ? `<text x="${m.l + 4}" y="${m.t + 9}" class="pf-tick">↑ さらに上：${above.map((b) => `${b.name} ${fmt(b.lo)}〜`).join('・')}</text>` : ''}
      ${below.length ? `<text x="${m.l + 4}" y="${H - m.b - 5}" class="pf-tick">↓ さらに下：${below.map((b) => `${b.name} 〜${fmt(b.hi)}`).join('・')}</text>` : ''}
    </svg>
    <div class="legend pf-legend"><span><span class="dot" style="background:var(--pri)"></span>10週線（≈50日）</span><span><span class="dot" style="background:#8e24aa"></span>40週線（≈200日）</span><span>点線＝最新の終値</span></div>`;
  }
  function frameCard(h) {
    const f = h.frame;
    if (!f) return '';
    return `<div class="card pf-card" id="pff-${esc(h.ticker)}">
      <div class="pf-head">
        <div><div class="story-ticker">${esc(h.ticker)}</div><div class="sub">${esc(h.name)}・予想EPS ${esc(f.label)}</div></div>
        <div class="pf-now"><span class="pf-big mono">${f1(f.per_now_lo)}${f.per_now_lo !== f.per_now_hi ? '〜' + f1(f.per_now_hi) : ''}</span><span class="sub">倍（予想PER）</span> <span class="badge muted">${esc(frameZone(h))}</span></div>
      </div>
      ${frameChart(h)}
      <div class="story-note">予想EPS ${esc(f.eps_lo)}${f.eps_lo !== f.eps_hi ? '〜' + esc(f.eps_hi) : ''} ${esc(h.currency)}（${esc(f.source)}）。${esc(f.note)}</div>
    </div>`;
  }

  function table(hs) {
    return `<div class="op-table"><table class="pf-table"><thead><tr>
      <th>銘柄</th><th>区分</th><th class="r">今のPER</th><th class="r">位置</th><th class="r">下位10%</th><th class="r">中央</th><th class="r">上位10%</th><th class="r">最高</th>
      <th class="r">株価</th><th class="r">下値の目処</th><th class="r">上限候補の株価</th></tr></thead><tbody>
      ${hs.map((h) => `<tr><td><a href="#pf-${esc(h.ticker)}" class="mono">${esc(h.ticker)}</a> <span class="sub">${esc(h.name)}</span></td><td>${esc(h.role)}</td>
        <td class="r mono">${esc(h.per_now)}</td><td class="r mono">${esc(h.percentile_now)}%</td>
        <td class="r mono pf-floor">${f1(h.p10)}</td><td class="r mono">${f1(h.p50)}</td><td class="r mono pf-cap">${f1(h.p90)}</td><td class="r mono">${f1(h.per_max)}</td>
        <td class="r mono">${esc(h.price)}</td><td class="r mono pf-floor">${esc(h.price_floor)}</td><td class="r mono pf-cap">${esc(h.price_cap)}</td></tr>`).join('')}
    </tbody></table></div>`;
  }

  function render(d) {
    const hs = d.holdings || [];
    root.innerHTML = `
      <div class="card op-hero">
        <div class="op-eyebrow">PORTFOLIO WATCH</div>
        <h2>保有銘柄のPERは、過去5年の自分の範囲のどこにいるか</h2>
        <p class="op-note">上位10%の倍率はコア株の「織り込み上限 → 部分利確」の上限値の候補、下位10%は下値の目処。短期のタイミングではなく、長期の値付けの位置を見る画面です。</p>
        <div class="sub">データ時点 ${esc(d.asof)}・${esc(d.source)}</div>
      </div>
      <div class="card"><div class="card-title">一覧：今のPERと過去の範囲</div>${table(hs)}
        <div class="sub" style="margin-top:var(--s3)">${esc(d.method)} 株価換算は直近期のEPSに過去の倍率を掛けたもの。</div></div>
      <div class="card"><div class="card-title">来年度の予想EPSで見た株価の枠</div>
        <div class="sub">${esc(d.frame_method || '')} 色の帯＝過去5年のPERの最低・下位10%・中央・上位10%・最高を、来年度の予想EPSで株価に直したもの。</div></div>
      <div class="pf-grid">${hs.map(frameCard).join('')}</div>
      <div class="card" style="margin-top:var(--s5)"><div class="card-title">PERの推移（過去5年）</div><div class="sub">確定EPSで見たPERの推移と、過去の範囲。</div></div>
      <div class="pf-grid">${hs.map(card).join('')}</div>
      <div class="card"><div class="card-title">読み方と注意</div><ul class="pf-notes">
        <li><b>警報</b>：EPSは伸びているのにPERが2〜3四半期続けて縮むときは、市場がストーリーを疑い始めているサイン。</li>
        <li><b>一時益</b>：純利益がEBITDAを上回る四半期は、保有株の評価益など本業以外の利益が入っている。その年はPERが低く出すぎる。</li>
        <li><b>PERが合わない銘柄</b>：保険会社（中国平安）はPBRが本筋。資源株（紫金鉱業）は利益が最高のときにPERが低く出る。NVDAの上位10%は2022年の利益の落ち込みで跳ね上がった値で、上限値には使えない。</li>
        <li><b>更新</b>：固定データ。更新はClaudeに「ポートフォリオウォッチを更新して」と頼む（TradingViewから再計算して docs/data/per_watch.json を差し替える）。</li>
      </ul></div>`;
  }

  fetch('data/per_watch.json', { cache: 'no-cache' })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(render)
    .catch(() => { root.innerHTML = '<div class="card"><div class="sub">PERデータ(data/per_watch.json)を読み込めませんでした。</div></div>'; });
})();
