/* 週間ウォッチ(2026-11-07追加)。データは docs/data/weekly.json(technical-practice/weekly.py が週2回作成)。
   - 地合いページ最上部の「週次の警戒ランプ」帯(#weekly-lamps)
   - 新しいタブ「週間ウォッチ」(#weekly-wrap)：重要度の高い順にカードを並べ、各カードに「見方」を付ける
   指標が増えても思い出せるよう、カードごとに「何の数字か／なぜ見るか／どう読むか／警戒ルール」を必ず書く。 */
(function (root) {
'use strict';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const signed = (v, suf = '') => (v === null || v === undefined ? '-' : `${v > 0 ? '+' : ''}${v}${suf}`);
const r1 = (v) => (v === null || v === undefined || !Number.isFinite(Number(v)) ? null : Math.round(Number(v) * 10) / 10);
const chart = () => root.JiaiLadder && root.JiaiLadder.priceChart;
const ymd = (d) => String(d || '').slice(2, 10).replace(/-/g, '/');

const LAMP = {
  on: { label: '点灯', color: 'var(--err)', bg: 'var(--err-h)' },
  watch: { label: '注意', color: 'var(--gold)', bg: 'var(--gold-h)' },
  off: { label: '未点灯', color: 'var(--ok)', bg: 'var(--ok-h)' },
  unknown: { label: '不明', color: 'var(--muted)', bg: 'var(--off)' },
};
const LAMP_DEF = [
  ['eps_revision', '① 利益予想の下方修正', '次四半期・来年の予想増益率が前週より下がった(両方＝点灯、片方＝注意)'],
  ['guidance', '② ガイダンスの下方修正が優勢', '次四半期のEPSガイダンスで、下方修正の社数が上方修正の社数を上回った'],
  ['cuts_breadth', '③ 下方修正がAI以外へ広がる', '消費・資本財・金融などAI以外のセクターでも予想が削られ始めた(日曜の予定タスクが号の本文から判定)'],
  ['credit', '④ 信用の悪化', 'ハイイールド社債の上乗せ金利が5年平均を上回った＝点灯、4週前より拡大＝注意'],
];

function lampChip(l) {
  const s = LAMP[(l && l.state) || 'unknown'] || LAMP.unknown;
  return `<span class="wk-lamp" style="color:${s.color};background:${s.bg}">${s.label}</span>`;
}

function lampStrip(d) {
  if (!d) return '';
  const L = d.lamps || {};
  const lit = LAMP_DEF.filter(([k]) => L[k] && L[k].state === 'on').length;
  return `<div class="card wk-strip">
    <div class="wk-strip-head"><div class="card-title" style="margin:0">週次の警戒ランプ(景気悪化への移行サイン)</div>
      <span class="sub">${esc(d.week)}の週 ／ 点灯 ${lit}/4 ／ <a href="#weekly" data-goto-weekly>週間ウォッチで詳しく見る →</a></span></div>
    <div class="wk-strip-row">${LAMP_DEF.map(([k, name]) => `<div class="wk-strip-item" title="${esc((L[k] || {}).detail || '')}">${lampChip(L[k])}<span>${esc(name)}</span></div>`).join('')}</div>
    ${d.summary ? `<div class="macro-read" style="margin-top:var(--s2)">今週の一文：${esc(d.summary.text)}</div>` : ''}
  </div>`;
}

function guide(what, why, how, rule) {
  return `<details class="guide wk-guide" open><summary>この指標の見方</summary><div class="guide-body">
    <div><b>何の数字か</b>：${what}</div>
    <div style="margin-top:6px"><b>なぜ見るか</b>：${why}</div>
    <div style="margin-top:6px"><b>どう読むか</b>：${how}</div>
    ${rule ? `<div style="margin-top:6px"><b>警戒ルール</b>：${rule}</div>` : ''}
  </div></details>`;
}

function card(rank, title, lamp, head, body, guideHtml, source) {
  return `<div class="card wk-card">
    <div class="wk-card-head"><span class="wk-rank">重要度 ${rank}</span><div class="card-title" style="margin:0">${title}</div>${lamp ? lampChip(lamp) : ''}</div>
    ${head}
    ${body}
    ${guideHtml}
    <div class="sub" style="margin-top:var(--s2)">${source}</div>
  </div>`;
}

const empty = (what) => `<div class="sub">${esc(what)}を取得できませんでした。次回の更新(土曜朝・日曜夜)で再取得します。</div>`;

// 1. 利益予想の修正(分母)
function epsCard(d) {
  const f = d.factset || {};
  const q = f.eps_quarter, y = f.eps_year;
  const draw = chart();
  const last = (s) => { if (!s) return null; for (let i = s.values.length - 1; i >= 0; i--) if (s.values[i] !== null) return { v: s.values[i], l: s.labels[i], d: s.dates[i] }; return null; };
  const lq = last(q), ly = last(y);
  // 期が切り替わる週は線を分けるため、ラベルが変わったら null を挟む
  const split = (s) => s ? s.values.map((v, i) => (i > 0 && s.labels[i] !== s.labels[i - 1] ? null : v)) : [];
  const ch = q && q.dates.length ? { dates: q.dates, values: split(q), year: split(y) } : null;
  const head = lq || ly ? `<div class="macro-value">${lq ? `${esc(lq.l)} ${esc(lq.v)}%` : ''}${ly ? `<span class="sub" style="font-size:13px;font-weight:600"> ／ ${esc(ly.l)} ${esc(ly.v)}%</span>` : ''}</div>
    <div class="sub">FactSetの予想増益率(前年比)。${esc((d.lamps.eps_revision || {}).detail || '')}</div>
    <div class="macro-read">${{ on: '次四半期も来年も予想が削られた＝分母(EPS)が下がり始めたサイン', watch: '片方だけ削られた＝様子見', off: '予想は削られていない＝分母はまだ崩れていない', unknown: '前週と比べられない週(期の切り替わり等)' }[(d.lamps.eps_revision || {}).state || 'unknown']}</div>` : empty('予想増益率');
  const body = draw && ch ? draw(ch, {
    aria: '予想増益率の推移', width: 900, height: 210, mainColor: 'var(--err)',
    lines: [{ key: 'year', color: 'var(--pri)', width: 1.6, label: '来年(暦年)' }],
    fmt: (v) => `${r1(v)}%`, dateFmt: ymd, note: '赤＝次四半期 ／ 青＝来年。期が切り替わる週で線は途切れる', empty: '週ごとの記録がたまると線になります。',
  }) : '';
  return card(1, '利益予想の修正(分母：EPS)', d.lamps.eps_revision, head, body,
    guide('アナリストが予想する、S&P500全体の利益の伸び率(次の四半期と来年)。FactSetが毎週集計して公表している。',
      '予想PERが下がったとき「分母(EPS)が上がった」のか「強欲(倍率)が下がった」のかを見分けるため。景気悪化は、まず利益予想の下方修正として現れる。民主党ショック後、株価(分子)は下げたが、予想EPS(分母)はまだ削られていない可能性がある。',
      '線が右下がりに変わったら要注意。株価が同じでも予想EPSが削られるとPERは上がるので、「PERが低いから割安」と見えていたものが割安ではなくなる。',
      '前週より次四半期・来年の両方が下がれば①点灯、片方なら注意。期が切り替わる週は比べない。'),
    `出典：FactSet Earnings Insight(週次・無料PDF)。最新号 ${esc((f.rows || []).slice(-1)[0]?.issue_date || '-')}`);
}

// 2. ガイダンス
function guidanceCard(d) {
  const rows = (d.factset || {}).rows || [];
  const draw = chart();
  const g = rows.filter((r) => r.guidance_negative !== null && r.guidance_negative !== undefined);
  const last = g[g.length - 1];
  const ch = g.length ? { dates: g.map((r) => r.issue_date || r.week), values: g.map((r) => r.guidance_negative), pos: g.map((r) => r.guidance_positive) } : null;
  const head = last ? `<div class="macro-value">下方 ${esc(last.guidance_negative)}社<span class="sub" style="font-size:13px;font-weight:600"> ／ 上方 ${esc(last.guidance_positive)}社(${esc(last.guidance_quarter || '')})</span></div>
    <div class="sub">${esc(last.issue_date || last.week)}号${last.filled_by_manual ? '(日曜の予定タスクが転記)' : ''}${last.beat_pct ? ` ／ 決算で予想を上回った企業 ${esc(last.beat_pct)}%` : ''}</div>
    <div class="macro-read">${last.guidance_negative > last.guidance_positive ? '下方修正が上方修正を上回る＝企業自身が先行きを弱く見ている' : '上方修正のほうが多い＝企業自身はまだ強気'}</div>` : empty('ガイダンス件数');
  const body = draw && ch ? draw(ch, {
    aria: 'EPSガイダンスの社数', width: 900, height: 190, mainColor: 'var(--err)', zeroBase: true,
    lines: [{ key: 'pos', color: 'var(--ok)', width: 1.6, label: '上方修正の社数' }],
    fmt: (v) => `${Math.round(v)}社`, dateFmt: ymd, note: '赤＝下方修正 ／ 緑＝上方修正(次四半期についての社数)', empty: '週ごとの記録がたまると線になります。',
  }) : '';
  return card(2, '企業ガイダンス(上方修正と下方修正の社数)', d.lamps.guidance, head, body,
    guide('S&P500企業のうち、次の四半期の利益見通し(ガイダンス)を引き下げた社数と引き上げた社数。',
      'アナリストの予想より先に、会社自身が先行きを語る数字。マサトさんの「会社はガイダンスを目標に動く」という見方の土台でもある。',
      '平常時でも下方修正のほうが多いのが普通なので、「上方修正が多い」は強い状態。下方修正が上回り、さらに増え続けたら景気の入口のサイン。',
      '下方修正の社数が上方修正の社数を上回れば②点灯。'),
    '出典：FactSet Earnings Insight(Key Metrics の Earnings Guidance)');
}

// 3. 信用(HY OAS)
function creditCard(d) {
  const h = d.hy_oas;
  const draw = chart();
  const head = h ? `<div class="macro-value">${esc(h.latest)}%</div>
    <div class="sub">${esc(h.as_of)}時点 ／ 5年平均 ${esc(h.avg_5y)}% ／ 前週比 ${signed(h.chg_1w, 'pt')} ／ 4週前比 ${signed(h.chg_4w, 'pt')} ／ 52週の最低 ${esc(h.min_52w)}%</div>
    <div class="macro-read">${h.latest > h.avg_5y ? '5年平均より高い＝お金を借りにくい環境に入った' : h.chg_4w > 0 ? 'まだ平均より低いが広がり始めた＝信用不安の芽' : '低く安定＝信用市場は落ち着いている'}</div>` : empty('ハイイールド社債の上乗せ金利');
  const body = draw && h ? draw(h, {
    aria: 'ハイイールド社債の上乗せ金利', width: 900, height: 210, mainColor: 'var(--err)',
    refs: [{ value: h.avg_5y, label: `過去5年平均 ${h.avg_5y}%`, short: '5年平均', color: 'var(--gold)' }],
    fmt: (v) => `${r1(v)}%`, dateFmt: ymd, note: '週次(金曜)', empty: '',
  }) : '';
  return card(3, '信用(ハイイールド社債の上乗せ金利)', d.lamps.credit, head, body,
    guide('格付けの低い会社の社債が、米国債よりどれだけ高い金利を払っているか(上乗せ金利、OAS)。',
      'オラクルやネオクラウド(CoreWeave・Nebius)のような「借りて貸す層」は、借入で設備を積み上げている。信用不安は株価より先にこの数字に出ることが多い。民主党ショックの直前(11/4)は低い水準だった。',
      '上がる＝投資家が「貸し倒れが怖い」と感じて高い金利を求めている。株が下げても上乗せ金利が落ち着いていれば、まだ株だけの調整。両方悪化したら本物の信用不安。',
      '5年平均を上回れば④点灯、4週前より拡大していれば注意。'),
    '出典：FRED BAMLH0A0HYM2(ICE BofA US High Yield Index Option-Adjusted Spread)。5年平均は計算値');
}

// 4. 予想PER(強欲)
function peCard(d) {
  const rows = ((d.factset || {}).rows || []).filter((r) => r.pe !== null && r.pe !== undefined);
  const draw = chart();
  const last = rows[rows.length - 1];
  const ch = rows.length ? { dates: rows.map((r) => r.issue_date || r.week), values: rows.map((r) => r.pe) } : null;
  const head = last ? `<div class="macro-value">${esc(last.pe)}倍</div>
    <div class="sub">${esc(last.issue_date || last.week)}号 ／ 5年平均 ${esc(last.pe_avg5 ?? '-')}倍 ／ 10年平均 ${esc(last.pe_avg10 ?? '-')}倍</div>
    <div class="macro-read">${last.pe_avg10 && last.pe < last.pe_avg10 ? '10年平均より低い＝市場は利益に高い倍率を払わなくなっている(①が未点灯なら、景気悪化ではなく疑いと金利による縮小)' : '平均以上＝市場は利益にまだ高い倍率を払っている'}</div>` : empty('予想PER');
  const body = draw && ch ? draw(ch, {
    aria: 'S&P500の予想PER', width: 900, height: 210, mainColor: 'var(--pri)',
    refs: [
      last && last.pe_avg5 ? { value: last.pe_avg5, label: `5年平均 ${last.pe_avg5}倍(FactSet公表値)`, short: '5年平均', color: 'var(--gold)' } : null,
      last && last.pe_avg10 ? { value: last.pe_avg10, label: `10年平均 ${last.pe_avg10}倍(FactSet公表値)`, short: '10年平均', color: 'var(--warn)' } : null,
    ],
    fmt: (v) => `${r1(v)}倍`, dateFmt: ymd, note: '週次(FactSetの各号)', empty: '週ごとの記録がたまると線になります。',
  }) : '';
  return card(4, '予想PER(市場の強欲度)', null, head, body,
    guide('S&P500の株価を、今後12か月の予想EPSで割った倍率。',
      '「強欲指数」にあたる数字。下がる理由は二つ：①株価が下がった ②予想EPSが株価以上に上がった。どちらかを、重要度1のカードとセットで見分ける。',
      'PERが下がっても重要度1(EPSの修正)が上向きなら「利益の持続性への疑い・金利」による縮小で、景気悪化ではない。PERが上がり始めたのに株価が上がっていなければ、分母(EPS)が削られている。相対PERで適正株価を出すとき、物差し(S&P500のPER)自体がここで動いている点に注意。',
      ''),
    '出典：FactSet Earnings Insight(Valuation)。平均線はFactSetの公表値');
}

// 5. 心理(AAII・VIX)
function sentimentCard(d) {
  const a = d.aaii || [];
  const v = d.vix;
  const draw = chart();
  const last = a[a.length - 1];
  const spread = last && last.bull !== null && last.bear !== null ? r1(last.bull - last.bear) : null;
  const ch = a.length ? { dates: a.map((x) => x.date), values: a.map((x) => (x.bull !== null && x.bear !== null ? r1(x.bull - x.bear) : null)) } : null;
  const head = last ? `<div class="macro-value">強気−弱気 ${signed(spread, 'pt')}</div>
    <div class="sub">${esc(last.date)}までの週 ／ 強気 ${esc(last.bull)}% ／ 中立 ${esc(last.neutral ?? '-')}% ／ 弱気 ${esc(last.bear)}%${v ? ` ／ VIX ${esc(v.latest)}(${esc(v.as_of)})` : ''}</div>
    <div class="macro-read">${spread !== null && spread < 0 ? '弱気が強気を上回る＝個人が悲観に傾いている(底値圏の条件の一つ。ただしそれだけで底とは言えない)' : '強気が優勢＝個人はまだ楽観'}</div>` : (v ? `<div class="macro-value">VIX ${esc(v.latest)}</div><div class="sub">AAIIは未取得(日曜の予定タスクが転記します)</div>` : empty('投資家心理'));
  const body = draw && ch && a.length >= 5 ? draw(ch, {
    aria: 'AAII 強気−弱気', width: 900, height: 190, mainColor: 'var(--pri)',
    refs: [{ value: 0, label: '0(強気と弱気が同じ)', short: '0', color: 'var(--faint)' }],
    fmt: (v) => `${r1(v)}pt`, dateFmt: ymd, note: '個人投資家の強気%−弱気%(週次)', empty: '',
  }) : '<div class="sub">AAIIは週ごとの記録がたまると線になります。</div>';
  const vixBody = draw && v ? draw(v, { aria: 'VIX', width: 900, height: 150, mainColor: 'var(--warn)', fmt: (x) => `${r1(x)}`, dateFmt: ymd, note: 'VIX(週次・金曜)', empty: '' }) : '';
  return card(5, '投資家心理(個人の強気・弱気／VIX)', null, head, body + vixBody,
    guide('AAII＝米国の個人投資家に毎週「今後6か月、株は上がると思うか」を聞いた結果。VIX＝S&P500オプションから計算する「恐怖指数」。',
      'マサトさんの経験則「○○ショックの下値を拾える局面では、個人の書き込みに買いの話がなくショートの話が多い」を数字で確かめるため。',
      '強気−弱気が大きくマイナス＝悲観が広がっている。逆張りの目安として使われるが、悲観は長く続くこともあるので、①〜④の警戒ランプとセットで見る。VIXは急上昇の後に落ち着き始めるところが、売りが一巡した合図になりやすい。',
      ''),
    `出典：AAII Sentiment Survey(${esc(last?.source || '-')})、Yahoo Finance(^VIX)`);
}

// 6. 景気(GDPNow)
function gdpCard(d) {
  const g = d.gdpnow;
  const draw = chart();
  const head = g ? `<div class="macro-value">${esc(g.latest)}%</div>
    <div class="sub">${esc(g.quarter_start)}から始まる四半期の推計(実質GDP成長率・年率)</div>
    <div class="macro-read">${g.latest < 0 ? 'マイナス＝景気後退の可能性' : g.latest < 1 ? '1%未満＝減速' : 'プラス成長が続く推計'}</div>` : empty('GDPNow');
  const body = draw && g ? draw(g, { aria: 'GDPNow', width: 900, height: 180, mainColor: 'var(--ok)', zeroBase: false,
    refs: [{ value: 0, label: '0%', short: '0%', color: 'var(--faint)' }], fmt: (v) => `${r1(v)}%`, dateFmt: (x) => String(x).slice(0, 7).replace('-', '/'), note: '四半期ごとの推計値', empty: '' }) : '';
  return card(6, '景気(アトランタ連銀GDPNow)', null, head, body,
    guide('いま進んでいる四半期のGDP成長率を、発表済みの経済指標からリアルタイムで推計したもの。',
      '「株安＝景気悪化か」の答え合わせ。株価やPERの動きが、実体経済の減速を伴っているかを確かめる。',
      '推計がプラスで安定していれば、株安は景気以外(評価・金利・政策)が原因。推計が急に下がり、①②も点灯したら景気悪化への移行。',
      ''),
    '出典：FRED GDPNOW(アトランタ連銀)');
}

// 7. 建玉(CFTC)
function cftcCard(d) {
  const c = d.cftc || {};
  const draw = chart();
  const one = (x, color) => {
    if (!x) return `<div class="macro-cell">${empty('建玉')}</div>`;
    return `<div class="macro-cell"><div class="macro-label">${esc(x.label)}</div>
      <div class="macro-value">${x.latest_net.toLocaleString()}枚</div>
      <div class="sub">${esc(x.as_of)}時点 ／ 前週比 ${signed(x.chg_1w, '枚')} ／ 買い ${x.latest_long.toLocaleString()} ・売り ${x.latest_short.toLocaleString()}</div>
      ${draw ? draw({ dates: x.dates, values: x.net }, { aria: `${x.label}の投機筋ネット`, width: 420, height: 170, mainColor: color,
        refs: [{ value: 0, label: '0', short: '0', color: 'var(--faint)' }], fmt: (v) => `${Math.round(v / 1000)}k`, dateFmt: ymd, note: '大口投機筋の買い越し(週次)', empty: '' }) : ''}</div>`;
  };
  return card(7, '建玉(金・原油の大口投機筋)', null, `<div class="macro-grid" style="grid-template-columns:repeat(2,1fr)">${one(c.gold, 'var(--gold)')}${one(c.crude, 'var(--err)')}</div>`, '',
    guide('先物市場で、ヘッジファンドなどの大口投機筋(非商業)が、買いと売りのどちらにどれだけ賭けているか(買い−売り＝ネット)。',
      '現物の金を持っているので、金の買いが混み合っていないかを見るため。原油は民主党ショック後の急落が続くかの確認に使う(原油安はインフレ・金利を通じて成長株の支えになる)。',
      '買い越しが過去の高水準にあるときは、材料が出ると一斉に手じまいされやすい。急減は投機筋の撤退。値動きと逆に動き始めたら転換の前触れのことがある。',
      ''),
    '出典：CFTC 建玉明細(Legacy・先物のみ、火曜時点の集計を金曜に公表)');
}

function page(d) {
  if (!d) return `<div class="error">週間ウォッチのデータ(data/weekly.json)がまだありません。GitHub Actionsの「Weekly Watch」を一度実行してください(Actions → Weekly Watch → Run workflow)。</div>`;
  const errs = d.fetch_errors || {};
  return `${lampStrip(d)}
    <div class="card"><div class="card-title">週間ウォッチの読み方</div>
      <div class="sub">毎日の地合いウォッチとは別に、週1回しか更新されない「分母(利益予想)・信用・心理・景気・建玉」を重要度の高い順に並べています。各カードの「この指標の見方」に、何の数字か・なぜ見るか・どう読むかを書いています。上の4つの警戒ランプは「株安が景気悪化に変わり始めたか」を見るためのもので、①②④はデータから自動判定、③は日曜夕方の予定タスクがFactSetの本文から判定します。</div>
      <div class="sub" style="margin-top:6px">データ更新：${esc(d.updated_at)}(土曜朝と日曜夜に自動更新)</div></div>
    ${epsCard(d)}${guidanceCard(d)}${creditCard(d)}${peCard(d)}${sentimentCard(d)}${gdpCard(d)}${cftcCard(d)}
    ${Object.keys(errs).length ? `<details class="guide"><summary>取得できなかったデータ(${Object.keys(errs).length}件)</summary><div class="guide-body">${Object.entries(errs).map(([k, v]) => `<div class="mono" style="font-size:11px">${esc(k)}：${esc(v)}</div>`).join('')}</div></details>` : ''}`;
}

let cache;
async function load() {
  if (cache !== undefined) return cache;
  try {
    const res = await fetch('data/weekly.json', { cache: 'no-store' });
    cache = res.ok ? await res.json() : null;
  } catch { cache = null; }
  return cache;
}

async function mount() {
  const d = await load();
  const strip = document.getElementById('weekly-lamps');
  if (strip) strip.innerHTML = lampStrip(d);
  const sec = document.getElementById('weekly');
  if (sec) sec.innerHTML = page(d);
  document.querySelectorAll('[data-goto-weekly]').forEach((a) => { a.onclick = (e) => { e.preventDefault(); location.hash = 'weekly'; }; });
}

const api = { lampStrip, page, epsCard, guidanceCard, creditCard, peCard, sentimentCard, gdpCard, cftcCard, LAMP_DEF };
if (typeof module !== 'undefined' && module.exports) module.exports = api;
else {
  root.WeeklyWatch = api;
  root.addEventListener('watch-data', () => setTimeout(mount, 0));
  root.addEventListener('DOMContentLoaded', mount);
}
})(typeof window !== 'undefined' ? window : globalThis);
