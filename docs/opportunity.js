/* AI reports and personal judgments are stored separately. No API keys in the browser. */
(function () {
'use strict';
const KEY='opportunity-watch-v1';
const AI_KEY='opportunity-analysis-v1';
const judgments=['未判断','納得','保留','異論あり'];
const A=typeof module!=='undefined'&&module.exports?require('./opportunity-analysis.js'):window.OpportunityAnalysis;
const e=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fields={story:'ストーリー（自分の仮説）',strength:'強まる条件（2〜3個）',broken:'壊れる条件（2〜3個）',evidence:'根拠・出典・確認日',counter:'反証・未確認事項',scenario:'最有力シナリオと、その理由',price:'価格条件・TradingView確認内容',event:'次の確認イベント',date:'次の確認日',stance:'方向感',state:'条件の状態',verified:'価格データの確認状況'};
const choices={stance:['未判断','強気','中立','弱気'],state:['未設定','監視中','条件に進展','条件を確認済み','反証あり'],verified:['未確認','TradingView確認済み']};
function seed(ticker){return {ticker,lane:'story',story:'',strength:'',broken:'',evidence:'',counter:'',scenario:'',price:'',event:'',date:'',stance:'未判断',state:'未設定',verified:'未確認',updated:''};}
function validate(x){
  return !!(x&&x.version===1&&Array.isArray(x.cards)&&x.cards.length<=100&&Array.isArray(x.log)&&x.log.length<=200&&
    x.cards.every(c=>c&&typeof c.ticker==='string'&&/^[A-Z0-9.^-]{1,12}$/.test(c.ticker)&&['story','technical'].includes(c.lane)&&
      Object.keys(fields).every(k=>typeof c[k]==='string'&&c[k].length<=10000)&&Object.entries(choices).every(([k,a])=>a.includes(c[k]))&&typeof c.updated==='string'&&
      (c.judgment===undefined||judgments.includes(c.judgment))&&(c.note===undefined||(typeof c.note==='string'&&c.note.length<=10000))&&
      (c.reviewedReportId===undefined||c.reviewedReportId===null||(typeof c.reviewedReportId==='string'&&c.reviewedReportId.length<=120)))&&
    new Set(x.cards.map(c=>c.ticker)).size===x.cards.length&&
    x.log.every(l=>l&&typeof l.at==='string'&&typeof l.text==='string'&&l.text.length<=20000));
}
function changes(latest,prev){if(!prev)return [];return Object.entries(latest.themes||{}).flatMap(([ticker,t])=>{const p=prev.themes?.[ticker];return p&&p.quadrant!==t.quadrant?[{ticker,name:t.name_jp,from:p.quadrant,to:t.quadrant}]:[]});}
function priority(c,today){if(c.state==='反証あり')return 0;if(c.date&&c.date<=today)return 1;if(c.state==='条件に進展')return 2;if(c.state==='条件を確認済み')return 3;return 4;}
if(typeof module!=='undefined')module.exports={seed,validate,changes,priority};
if(typeof document==='undefined')return;
const drafts=new Map();
function draftKey(f){return f.dataset.review?'review:'+f.dataset.review:f.dataset.ticker?'legacy:'+f.dataset.ticker:f.id;}
function forgetDraft(f){drafts.delete(draftKey(f));delete f.dataset.dirty;}
function clearDrafts(){drafts.clear();document.querySelectorAll('#opportunity form').forEach(f=>delete f.dataset.dirty);}
let feed={version:1,demo:false,reports:[]},feedStatus='AI分析を読み込み中です。',pendingMarket=false;
try{const raw=localStorage.getItem(AI_KEY);if(raw){const parsed=JSON.parse(raw);if(!A.validateFeed(parsed)||parsed.demo)throw Error();feed=parsed;feedStatus='このブラウザに取り込んだAI分析';}}catch{feedStatus='保存済みAI分析を読み込めません。再取り込みしてください。';}
let data={version:1,cards:['NVDA','GOOGL','AVGO'].map(seed),log:[]},lane='story',storageError='';
try{const raw=localStorage.getItem(KEY);if(raw){const parsed=JSON.parse(raw);if(!validate(parsed))throw Error('invalid');data=parsed;}}catch{storageError='保存データを読み込めません。元データ保護のため保存を停止しています。バックアップから復元してください。';}
function persist(next){try{localStorage.setItem(KEY,JSON.stringify(next));data=next;storageError='';return true;}catch{message('保存できませんでした。ブラウザの保存設定・空き容量を確認してください。');return false;}}
function message(t){document.getElementById('op-status').textContent=t;}
function field(c,k){let control;if(choices[k])control=`<select name="${k}">${choices[k].map(v=>`<option ${c[k]===v?'selected':''}>${e(v)}</option>`).join('')}</select>`;else if(k==='date')control=`<input name="date" type="date" value="${e(c.date)}">`;else control=`<textarea name="${k}" maxlength="10000">${e(c[k])}</textarea>`;return `<label class="op-field">${fields[k]}${control}</label>`;}
function reportFor(ticker){return feed.reports.find(r=>r.ticker===ticker);}
function sources(r,ids){return ids.map(id=>{const s=r.sources.find(x=>x.id===id);return `<a href="${e(s.url)}" target="_blank" rel="noopener noreferrer">${e(s.title)} (${e(s.publishedAt)})</a>`;}).join(' / ');}
function bulletList(xs){return `<ul>${xs.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`;}
function reportView(r,c){
  if(!r)return `<div class="op-analysis-empty"><h4>AI分析待ち</h4><p>この銘柄の分析はまだ届いていません。仮説の入力は不要です。</p><p class="op-note">決算・ニュースの自動収集とAI生成は接続準備中です。分析が届くと、ストーリー・出典・反証がここに表示されます。</p></div>`;
  return `<div class="op-analysis"><p class="op-tag">AI分析 · 情報基準日 ${e(r.asOf)} · ${e(r.model)}</p>
    ${A.stale(r)?'<p class="op-alert">情報基準日から7日を超えています。最新の決算・ニュースを確認してください。</p>':''}
    ${A.changedSinceReview(c,r)?'<p class="op-alert">判断後にAI分析が更新されています。再確認が必要です。</p>':''}
    <h4>${e(r.headline)}</h4>
    <section><h5>何が起きたか <span>出典付き事実・AI抽出</span></h5><ul>${r.facts.map(f=>`<li>${e(f.text)}<div class="op-note">${sources(r,f.sourceIds)}</div></li>`).join('')}</ul></section>
    <section class="op-thesis"><h5>AIの投資ストーリー <span>推測・解釈</span></h5><p>${e(r.story.thesis)}</p><dl><dt>変化が効く仕組み</dt><dd>${e(r.story.mechanism)}</dd><dt>売上・利益への影響</dt><dd>${e(r.story.earningsImpact)}</dd></dl></section>
    <section><h5>市場の期待との違い <span>${e(r.expectations.status)}</span></h5><p>${e(r.expectations.text)}</p>${r.expectations.sourceIds.length?`<p class="op-note">${sources(r,r.expectations.sourceIds)}</p>`:''}</section>
    <section><h5>前回からの変化 <span>AIの評価</span></h5><p><strong>${e(r.change.direction)}</strong> — ${e(r.change.summary)}</p>${r.change.previousReportId?`<p class="op-note">比較元：${e(r.change.previousReportId)}</p>`:''}</section>
    <section><h5>反証・未確認事項</h5>${bulletList(r.counterarguments)}</section>
    <section><h5>ストーリーが崩れる条件</h5>${bulletList(r.breakConditions)}</section>
    <section><h5>次に確認すること</h5><ul>${r.nextChecks.map(x=>`<li><strong>${e(x.event)}</strong> · ${e(x.date||'日付未定')}<br>${e(x.condition)}</li>`).join('')}</ul></section>
    <p class="op-note">作成：${e(new Date(r.generatedAt).toLocaleString('ja-JP'))} · 分析ID ${e(r.id)}<br>出典との整合性は未検証です。AIの解釈を含み、売買の指示ではありません。</p></div>`;
}
function card(c){const r=reportFor(c.ticker);return `<article class="card op-card"><h3>${e(c.ticker)}</h3>${reportView(r,c)}
  <div class="op-personal"><h4>あなたの判断 <span class="op-note">任意</span></h4>
  <p class="op-note">読むだけでも使えます。AIの分析が更新されても、あなたの判断・メモは保持します。</p>
  <form data-review="${e(c.ticker)}" data-report="${e(r?.id||'')}"><label class="op-field">AIストーリーへの判断<select name="judgment">${judgments.map(v=>`<option ${v===(c.judgment||'未判断')?'selected':''}>${v}</option>`).join('')}</select></label>
  <label class="op-field">メモ（必要なときだけ）<textarea name="note" maxlength="10000" placeholder="納得した点、気になる反証など">${e(c.note||'')}</textarea></label><button class="op-btn" type="submit">判断・メモを保存</button></form>
  ${c.reviewedReportId?`<p class="op-note">判断した分析：${e(c.reviewedReportId)}</p>`:''}</div>
  <details class="op-legacy"><summary>以前のメモ・詳細な監視条件</summary><p class="op-note">これまで入力した内容は、この中に保持しています。</p><form data-ticker="${e(c.ticker)}"><label class="op-field">運用の軸<select name="lane"><option value="story" ${c.lane==='story'?'selected':''}>ストーリー投資</option><option value="technical" ${c.lane==='technical'?'selected':''}>テクニカル売買</option></select></label><div class="op-form-grid">${Object.keys(fields).map(k=>field(c,k)).join('')}</div><button class="op-btn" type="submit">詳細メモを保存</button></form></details></article>`;}
function render(){const root=document.getElementById('opportunity');if(!root)return;root.querySelectorAll('form[data-dirty=true]').forEach(f=>drafts.set(draftKey(f),{values:Object.fromEntries(new FormData(f)),reportId:f.dataset.report}));const latest=window.watchLatest,prev=window.watchPrevious;const today=new Date().toLocaleDateString('sv-SE');const diff=latest?changes(latest,prev?.data):[];const selected=data.cards.filter(c=>c.lane===lane).sort((a,b)=>Number(!!reportFor(b.ticker))-Number(!!reportFor(a.ticker)));const queue=selected.filter(c=>priority(c,today)<4).sort((a,b)=>priority(a,today)-priority(b,today)||(a.date||'9999').localeCompare(b.date||'9999')).slice(0,3);const age=latest?Math.floor((Date.now()-Date.parse(latest.date+'T00:00:00Z'))/86400000):null;
root.innerHTML=`<div class="card op-hero"><div class="op-eyebrow">OPPORTUNITY WATCH / 攻めの準備</div><h2>AIのストーリーを読み、自分で判断する。</h2><p>事実と推測、反証、次の確認事項を読み比べる。メモは必要なときだけ。</p><p class="op-note">${e(feedStatus)} · 分析 ${feed.reports.length} 銘柄</p><p class="op-note">${latest?`地合い：${e(({correction:'調整局面',uptrend_under_pressure:'圧力下の上昇トレンド',confirmed_uptrend:'確認された上昇トレンド'})[latest.overall_trend_state]||latest.overall_trend_state)} / データ日 ${e(latest.date)} / 自動取得・未検証`:'市場データを取得できていません。判断カードは利用できます。'}${age>3?' / データが古いため最新状況を確認してください。':''}</p></div>
<div class="op-actions"><button type="button" class="op-btn" data-lane="story" aria-pressed="${lane==='story'}">ストーリー投資</button><button type="button" class="op-btn" data-lane="technical" aria-pressed="${lane==='technical'}">テクニカル売買</button></div>
<h3>AIストーリーとあなたの判断</h3><p class="op-note">分析のある銘柄から読めます。未分析の銘柄に仮のストーリーは表示しません。</p><div class="op-actions"><form id="op-add"><label>銘柄追加 <input aria-label="追加するティッカー" name="ticker" placeholder="例：MSFT" maxlength="12" required></label> <button class="op-btn">追加</button></form><button class="op-btn" id="op-export">バックアップ保存</button><label class="op-btn">バックアップ復元<input id="op-import" type="file" accept="application/json,.json" hidden></label></div><p class="op-note">カードはこの端末・ブラウザだけに保存します。端末間の自動同期はありません。</p><p id="op-status" class="op-status" role="status">${e(storageError)}</p><div class="op-grid">${selected.map(card).join('')||'<p class="op-empty">この運用のカードはありません。銘柄を追加してください。</p>'}</div><details class="card op-transfer"><summary>AI分析ファイルの取り込み</summary><p class="op-note">AIが作成した専用JSONを取り込めます。あなたの判断・メモは変わりません。ファイルはこのブラウザにのみ保存されます。</p><label class="op-btn">AI分析JSONを選択<input id="op-ai-import" type="file" accept="application/json,.json" hidden></label><p class="op-note">バックアップ復元は個人メモ用です。AI分析ファイルは別に保管してください。</p></details><div class="card"><h3>自分で設定した確認候補 · 最大3件</h3><p class="op-note">反証あり → 確認日到来 → 条件に進展 → 条件確認済み、の順。購入順位ではありません。</p>${queue.length?queue.map(c=>`<p class="op-log"><strong>${e(c.ticker)}</strong> · ${e(c.state)} · ${e(c.event||'根拠と価格条件を点検')} / ${e(c.date||'日付未設定')}</p>`).join(''):'<p class="op-empty">該当なし。未設定・欠損から候補を推定しません。</p>'}</div>
<div class="grid2"><section class="card"><h3>テーマの変化</h3><p class="op-note">${prev?`${e(prev.date)} → ${e(latest?.date)}（取得できた直前の履歴との比較）`:'比較用の履歴 '+(window.watchHistoryLoaded?'なし':'読み込み中')} / 自動取得・未検証</p>${diff.length?diff.map(d=>`<p class="op-log">${e(d.name)} (${e(d.ticker)})：${e(d.from)} → <strong>${e(d.to)}</strong></p>`).join(''):`<p class="op-empty">${prev?'象限の変化なし。':'比較結果は未判定。'}</p>`}<p class="op-note">ETFの相対的な値動きです。資金流入や企業利益の改善を直接確認したものではありません。</p></section><section class="card"><h3>判断カードの更新履歴</h3>${data.log.length?data.log.slice(0,5).map(l=>`<p class="op-log"><span class="op-note">${e(new Date(l.at).toLocaleString('ja-JP'))}</span><br>${e(l.text)}</p>`).join(''):'<p class="op-empty">まだ更新はありません。</p>'}</section></div>
`;
root.querySelectorAll('form').forEach(f=>{const draft=drafts.get(draftKey(f));if(!draft)return;for(const [k,v]of Object.entries(draft.values)){if(f.elements.namedItem(k))f.elements.namedItem(k).value=v;}if(draft.reportId!==undefined)f.dataset.report=draft.reportId;f.dataset.dirty='true';if(f.closest('details'))f.closest('details').open=true;});
root.querySelectorAll('form[data-review]').forEach(f=>f.onsubmit=ev=>{
  ev.preventDefault();if(storageError){message(storageError);return;}
  const values=Object.fromEntries(new FormData(f));
  const current=data.cards.find(c=>c.ticker===f.dataset.review);
  const reportId=f.dataset.report||null;
  if(values.judgment!=='未判断'&&!reportId){message('AI分析が届いてから判断を記録してください。メモだけなら「未判断」のまま保存できます。');return;}
  const next={...current,judgment:values.judgment,note:values.note,reviewedReportId:values.judgment==='未判断'?null:reportId,updated:new Date().toISOString()};
  const updated={...data,cards:data.cards.map(c=>c.ticker===next.ticker?next:c),log:[{at:next.updated,text:`${next.ticker}：判断・メモを更新（${next.judgment}）`},...data.log].slice(0,200)};
  if(!validate(updated)){message('入力内容が無効です。');return;}
  if(persist(updated)){forgetDraft(f);pendingMarket=false;render();message(`${next.ticker} の判断・メモを保存しました。`);}
});
root.querySelector('#op-ai-import').onchange=async ev=>{
  const file=ev.target.files[0];if(!file)return;
  try{
    if(file.size>5000000)throw Error();
    const imported=JSON.parse(await file.text());
    if(!A.validateFeed(imported)||imported.demo||!imported.reports.length)throw Error();
    if(!confirm('AI分析をこのファイルの内容に置き換えますか？あなたの判断・メモは保持されます。'))return;
    localStorage.setItem(AI_KEY,JSON.stringify(imported));feed=imported;feedStatus='このブラウザに取り込んだAI分析';
    refreshAnalysis();message('AI分析を取り込みました。未登録の銘柄は「銘柄追加」で表示できます。');
  }catch{message('取り込めません。形式・出典・日付を確認してください。見本データは取り込めません。');}
  finally{ev.target.value='';}
};
root.querySelectorAll('form').forEach(f=>f.addEventListener('input',()=>{f.dataset.dirty='true';}));
root.querySelectorAll('details').forEach(d=>d.addEventListener('toggle',()=>{if(!d.open&&pendingMarket)refreshAnalysis();}));
root.querySelectorAll('[data-lane]').forEach(b=>b.onclick=()=>{lane=b.dataset.lane;render();});
root.querySelectorAll('form[data-ticker]').forEach(f=>f.onsubmit=ev=>{ev.preventDefault();if(storageError){message(storageError);return;}const original=data.cards.find(c=>c.ticker===f.dataset.ticker),next={...original,...Object.fromEntries(new FormData(f))};if(['条件に進展','条件を確認済み','反証あり'].includes(next.state)&&!next.evidence.trim()){message('状態の根拠・出典・確認日を入力してください。');return;}if(next.verified==='TradingView確認済み'&&!next.price.trim()){message('TradingViewの確認内容と確認日を価格条件に記録してください。');return;}const changed=['lane',...Object.keys(fields)].filter(k=>next[k]!==original[k]);if(!changed.length){forgetDraft(f);if(pendingMarket)refreshAnalysis();message('変更はありません。');return;}next.updated=new Date().toISOString();const log={at:next.updated,text:`${next.ticker}：${changed.map(k=>fields[k]||'運用の軸').join('・')} を更新（${original.state} → ${next.state}）`};if(persist({...data,cards:data.cards.map(c=>c.ticker===next.ticker?next:c),log:[log,...data.log].slice(0,200)})){forgetDraft(f);render();message(`${next.ticker} を保存しました。`);}});
root.querySelector('#op-add').onsubmit=ev=>{ev.preventDefault();if(storageError){message(storageError);return;}const ticker=new FormData(ev.target).get('ticker').trim().toUpperCase();if(!/^[A-Z0-9.^-]{1,12}$/.test(ticker)||data.cards.some(c=>c.ticker===ticker)||data.cards.length>=100){message('ティッカーが無効・登録済み、または100件の上限です。');return;}if(persist({...data,cards:[...data.cards,{...seed(ticker),lane}]})){forgetDraft(ev.target);render();}};
root.querySelector('#op-export').onclick=()=>{if(storageError){message('読み込みエラーのためバックアップ出力を停止しています。');return;}const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=`opportunity-watch-${today}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
root.querySelector('#op-import').onchange=async ev=>{const file=ev.target.files[0];if(!file)return;try{if(file.size>5000000)throw Error();const imported=JSON.parse(await file.text());if(!validate(imported))throw Error();if(!confirm('現在の判断カードをバックアップの内容で置き換えますか？'))return;if(persist(imported)){clearDrafts();render();message('バックアップを復元しました。');}}catch{message('復元できません。有効な機会ウォッチのJSONを選んでください。');}finally{ev.target.value='';}};
}
function view(name){const offense=name==='opportunity';document.getElementById('opportunity').hidden=!offense;document.getElementById('content').hidden=offense;document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===name)));}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{location.hash=b.dataset.view;view(b.dataset.view);});
window.addEventListener('hashchange',()=>view(location.hash==='#opportunity'?'opportunity':'climate'));
function refreshAnalysis(){
  if(document.querySelector('#opportunity form[data-dirty=true]')){pendingMarket=true;message('新しいデータを受信しました。編集中の内容を保存すると表示に反映されます。');return;}
  pendingMarket=false;render();
}
window.addEventListener('watch-data',refreshAnalysis);
async function loadAnalysis(){
  if(feed.reports.length)return;
  try{
    const response=await fetch('data/opportunity/latest.json',{cache:'no-cache'});
    if(!response.ok)throw Error();
    const fetched=await response.json();
    if(!A.validateFeed(fetched)||fetched.demo)throw Error();
    // An import may have finished while the public file was loading.
    if(feed.reports.length)return;
    feed=fetched;feedStatus=feed.reports.length?'配信されたAI分析':'AI分析は未生成です。自動生成はまだ接続していません。';
  }catch{if(feed.reports.length)return;feedStatus='AI分析を取得できませんでした。個人メモは利用できます。';}
  refreshAnalysis();
}
render();view(location.hash==='#opportunity'?'opportunity':'climate');
loadAnalysis();
})();
