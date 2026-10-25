/* テーマ代表銘柄(2026-10-25追加)。テーマごとに2〜3銘柄と「何で稼いでいるか」。
   説明文は事業の仕組みだけを書き、売上高などの数字は入れない(数字は決算で確認する)。
   値動きは日次JSONの opportunity_universe(普通株・流動性フィルタ通過の全銘柄)から引く。 */
(function (root) {
'use strict';

const THEMES = [
  { name: 'AIの計算基盤(半導体)', etf: 'SOXX', stocks: [
    { t: 'NVDA', biz: 'データセンター向けGPUと、それをつなぐネットワーク機器・ソフト(CUDA)を売る。ソフト資産が他社への乗り換えを難しくしている。' },
    { t: 'TSM', biz: '他社が設計した最先端チップの受託製造(ファウンドリー)。最先端の製造技術と規模で、NVIDIAやAppleなど主要顧客を抱える。' },
    { t: 'MU', biz: 'メモリ(DRAM・NAND)の製造販売。AI向け高帯域メモリ(HBM)が成長源だが、メモリ価格の市況で業績が大きく振れる。' },
  ] },
  { name: 'AIの料金所(クラウド・プラットフォーム)', etf: null, stocks: [
    { t: 'GOOGL', biz: '検索とYouTubeの広告が収益の柱。クラウド(Google Cloud)と自社AI(Gemini・TPU)が成長源。' },
    { t: 'MSFT', biz: 'Office・Windowsなどのソフトの定額課金と、クラウド(Azure)の利用料で稼ぐ。AIはAzureとCopilotで収益化する。' },
  ] },
  { name: 'データセンター建設', etf: 'SRVR', stocks: [
    { t: 'CAT', biz: '建設・鉱山機械とエンジン・発電設備の販売、その保守部品とサービス。データセンター向けの発電設備の需要が加わっている。' },
    { t: 'VRT', biz: 'データセンター向けの電源・冷却機器(UPS、液冷など)の販売と保守。AIサーバーの発熱が増えるほど冷却の需要が伸びる。' },
    { t: 'PWR', biz: '送電網・変電所・発電所の建設工事を請け負う専門工事会社(Quanta Services)。電力網の増強需要が受注源。' },
  ] },
  { name: '電力・原子力', etf: 'URA', stocks: [
    { t: 'CEG', biz: '米国最大級の原子力発電事業者として電気を売る。データセンター向けの長期電力契約が増えている。' },
    { t: 'CCJ', biz: 'ウラン(原子力の燃料)の採掘と燃料加工を行い、長期契約で電力会社に売る。原子炉メーカーのWestinghouseにも出資。' },
  ] },
  { name: '宇宙・防衛', etf: 'ITA', stocks: [
    { t: 'RTX', biz: '民間機エンジン(Pratt & Whitney)、航空機部品(Collins)、ミサイル・防空システム(Raytheon)の3本柱。' },
    { t: 'LMT', biz: '戦闘機F-35、ミサイル、宇宙システムなどを主に米国政府へ売る防衛最大手。' },
  ] },
  { name: 'エネルギー(原油・ガス生産)', etf: 'XOP', stocks: [
    { t: 'COP', biz: '原油・天然ガスの探鉱と生産に専念する上流企業。原油価格で利益が大きく動く。' },
    { t: 'EOG', biz: '米国のシェールを中心とした原油・天然ガスの生産。生産コストの低い鉱区が強み。' },
  ] },
  { name: '素材・鉱業', etf: 'PICK', stocks: [
    { t: 'FCX', biz: '銅を中心に金・モリブデンを採掘して売る。インドネシアのGrasbergなど大型鉱山を持ち、銅価格で業績が動く。' },
    { t: 'NEM', biz: '世界最大の金鉱山会社。金価格が利益を左右する。' },
  ] },
  { name: 'バイオテクノロジー', etf: 'IBB', stocks: [
    { t: 'VRTX', biz: '嚢胞性線維症の治療薬でほぼ独占的な地位を持つ。痛みなど新しい領域へ広げている。' },
    { t: 'REGN', biz: '眼の病気の薬(アイリーア)や、Sanofiと共同で売るアトピーなどの薬(デュピクセント)など、抗体医薬で稼ぐ。' },
  ] },
  { name: 'クリーンエネルギー', etf: 'ICLN', stocks: [
    { t: 'FSLR', biz: '米国で製造する薄膜型の太陽光パネルを売る。米国内製造への優遇策の恩恵を受ける。' },
    { t: 'NEE', biz: 'フロリダの規制電力会社(FPL)と、風力・太陽光発電の開発事業の二本柱。' },
  ] },
  { name: '輸送', etf: 'IYT', stocks: [
    { t: 'UNP', biz: '米国西部の大手貨物鉄道。運賃収入が中心で、景気と貨物量に連動する。' },
    { t: 'FDX', biz: '宅配と航空貨物の物流。景気と貿易量に業績が連動する。' },
  ] },
];

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (v) => (v === null || v === undefined ? '-' : `${v > 0 ? '+' : ''}${v}%`);
const col = (v) => (v === null || v === undefined ? 'var(--muted)' : v > 0 ? 'var(--ok)' : v < 0 ? 'var(--err)' : 'var(--muted)');
const QCOLOR = { '主導': 'var(--ok)', '改善': 'var(--pri)', '鈍化': 'var(--warn)', '遅行': 'var(--err)' };

function rowIndex(latest) {
  const map = {};
  for (const r of latest?.opportunity_universe?.rows || []) map[r.ticker] = r;
  for (const r of latest?.market_leaders || []) if (!map[r.ticker]) map[r.ticker] = r;
  return map;
}

function render(latest) {
  const rows = rowIndex(latest);
  const hasData = Object.keys(rows).length > 0;
  const cards = THEMES.map((th) => {
    const q = th.etf ? latest?.themes?.[th.etf]?.quadrant : null;
    const stocks = th.stocks.map((s) => {
      const r = rows[s.t];
      const stats = r
        ? `<span class="tl-stat">RS <b>${esc(r.rs_percentile)}</b></span><span class="tl-stat">1M <b style="color:${col(r.one_month_pct)}">${pct(r.one_month_pct)}</b></span><span class="tl-stat">3M <b style="color:${col(r.three_month_pct)}">${pct(r.three_month_pct)}</b></span><span class="tl-stat">${r.above_sma50 ? '<b style="color:var(--ok)">50日線の上</b>' : r.above_sma50 === false ? '<b style="color:var(--err)">50日線の下</b>' : '-'}</span>`
        : `<span class="tl-stat sub">${hasData ? '本日の値動きデータなし' : '値動きデータは次回更新から'}</span>`;
      return `<div class="tl-stock">
        <div class="tl-head"><a class="tl-ticker" href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(s.t)}" target="_blank" rel="noopener">${esc(s.t)}</a><span class="tl-stats">${stats}</span></div>
        <div class="tl-biz">${esc(s.biz)}</div>
      </div>`;
    }).join('');
    return `<div class="tl-card">
      <div class="tl-theme"><strong>${esc(th.name)}</strong>${th.etf ? `<span class="sub mono">${esc(th.etf)}</span>` : ''}${q ? `<span class="tl-q" style="color:${QCOLOR[q] || 'var(--muted)'}">${esc(q)}</span>` : ''}</div>
      ${stocks}
    </div>`;
  }).join('');
  return `<div class="tl-grid">${cards}</div>
    <div class="sub" style="margin-top:var(--s3)">RSは母集団内の1年騰落率の百分位(IBDのRSレーティングとは別物)。テーマ名の横はその代理ETFのRRG象限。銘柄名からTradingViewのチャートを開けます。</div>`;
}

const api = { THEMES, render };
if (typeof module !== 'undefined' && module.exports) module.exports = api;
else root.ThemeLeaders = api;
})(typeof window !== 'undefined' ? window : globalThis);
