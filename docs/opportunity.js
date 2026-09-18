/* Rule-based discovery using existing market snapshots. No AI service or API keys. */
(function () {
'use strict';
const KEY='opportunity-watch-v1';
const judgments=['未判断','納得','保留','異論あり'];
const R=typeof module!=='undefined'&&module.exports?require('./opportunity-rules.js'):window.OpportunityRules;
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
const S=window.OpportunityStories;
let storyTicker='SBUX';
const drafts=new Map();
function draftKey(f){return f.dataset.review?'review:'+f.dataset.review:f.dataset.ticker?'legacy:'+f.dataset.ticker:f.id;}
function forgetDraft(f){drafts.delete(draftKey(f));delete f.dataset.dirty;}
function clearDrafts(){drafts.clear();document.querySelectorAll('#opportunity form').forEach(f=>delete f.dataset.dirty);}
let pendingMarket=false;
let discovery=R.derive(null,null);
let data={version:1,cards:['NVDA','GOOGL','AVGO'].map(seed),log:[]},lane='story',storageError='';
try{const raw=localStorage.getItem(KEY);if(raw){const parsed=JSON.parse(raw);if(!validate(parsed))throw Error('invalid');data=parsed;}}catch{storageError='保存データを読み込めません。元データ保護のため保存を停止しています。バックアップから復元してください。';}
function persist(next){try{localStorage.setItem(KEY,JSON.stringify(next));data=next;storageError='';return true;}catch{message('保存できませんでした。ブラウザの保存設定・空き容量を確認してください。');return false;}}
function message(t){document.getElementById('op-status').textContent=t;}
function field(c,k){let control;if(choices[k])control=`<select name="${k}">${choices[k].map(v=>`<option ${c[k]===v?'selected':''}>${e(v)}</option>`).join('')}</select>`;else if(k==='date')control=`<input name="date" type="date" value="${e(c.date)}">`;else control=`<textarea name="${k}" maxlength="10000">${e(c[k])}</textarea>`;return `<label class="op-field">${fields[k]}${control}</label>`;}
function reportFor(ticker){return discovery.byTicker[ticker];}
function bulletList(xs){return `<ul>${xs.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`;}
function reportView(r,c){
  if(!r)return `<div class="op-analysis-empty"><h4>取得済みの上位リストにデータなし</h4><p>この銘柄の値動きは未判定です。銘柄を登録しても、新たなデータ取得は行いません。</p></div>`;
  return `<div class="op-analysis"><p class="op-tag">ルール判定 · ${e(discovery.date)} · ${r.caution?'注意点を確認':'変化を確認'}</p>
    ${c.reviewedReportId&&c.reviewedReportId!==r.id?'<p class="op-alert">前回の判断からデータ日または判定方式が変わっています。</p>':''}
    <h4>${r.signals.length?'なぜこの銘柄を見るのか':'今回、抽出ルールに該当する変化なし'}</h4>${bulletList(r.signals.map(x=>x.text))}
    <p>前日比 ${e(R.pct(r.row.day_change_pct))} / 1か月 ${e(R.pct(r.row.one_month_pct))} / 3か月 ${e(R.pct(r.row.three_month_pct))}</p>
    <p>RS百分位 ${Number.isFinite(r.row.rs_percentile)?e(r.row.rs_percentile.toFixed(1)):'未取得'} / 50日線 ${r.row.above_sma50===true?'より上':r.row.above_sma50===false?'より下':'未取得'}</p>
    <section><h5>未確認・注意点</h5>${bulletList(r.limitations)}</section>
    <section><h5>次に確認すること</h5><p>${e(r.next)}</p></section></div>`;
}
function candidateView(r){return `<article class="card op-card op-candidate"><span class="op-tag">${r.caution?'注意点を確認':'変化を確認'} · ルールによる抽出</span><h3>${e(r.ticker)}</h3>${reportView(r,{})}
  <button class="op-btn" data-watch="${e(r.ticker)}" ${data.cards.some(c=>c.ticker===r.ticker)?'disabled':''}>${data.cards.some(c=>c.ticker===r.ticker)?'監視に登録済み':'監視に追加'}</button>
  <details><summary>必要なときだけ深掘りする</summary><p class="op-note">ここまでの説明は自動表示です。さらに調べたい場合だけ、このメモをチャットへ渡せます。</p><textarea class="op-brief" aria-label="${e(r.ticker)}の調査メモ" readonly>${e(R.briefing(r,discovery.date,discovery.previousDate))}</textarea><button class="op-btn" data-copy="${e(r.ticker)}">調査メモをコピー</button></details></article>`;}
function discoveryView(){return `<section class="op-discovery"><h3>データ日の確認候補 · 最大3件</h3><p class="op-note">${e(discovery.notice)} ${discovery.previousDate?e(discovery.previousDate)+' → '+e(discovery.date):''}</p>
  ${discovery.stale?'<p class="op-alert">現在の投資機会を示すものではありません。市場データの更新を確認してください。</p>':''}
  <p class="op-note">取得済みの上位2リスト・重複除外後 ${discovery.coverage} 銘柄から ${discovery.all.length} 件が条件に該当。全米国株をこの画面で再検索しているわけではありません。</p>
  <div class="op-grid">${discovery.candidates.map(candidateView).join('')||'<div class="card"><p>確認候補はありません。データがない場合や条件に合わない場合、候補を埋めるための推測はしません。</p></div>'}</div>
  ${discovery.excluded.length?`<p class="op-alert">確認候補から保留：${e(discovery.excluded.join(', '))}。大きすぎる騰落率・不正な値・リスト間の不一致があるため、元データの確認が必要です。</p>`:''}
  <details class="card"><summary>抽出ルール・対象範囲を見る</summary><p>50日線の上→下、下→上、上位リストへの掲載、RS百分位の1ポイント以上の変化、3%以上の騰落を確認します。上昇候補は50日線より上・RS百分位90以上が条件です。</p><p>確認順は50日線変化→リスト掲載→RS変化→大幅騰落を基本とし、下落の注意も含めます。利益確率・買い順位ではありません。閾値の投資成績は未検証です。</p><p>取得対象は既存の日次処理が出力するRS上位20件とトレンド条件合格のRS上位20件。RSの計算対象が変わると百分位にも影響します。比較間隔が7日を超える場合、変化判定は行いません。</p><p>前日比の絶対値50%超、1か月200%超、3か月500%超は保留します。企業行動やデータ調整の影響を確認するためで、異常と断定するものではありません。</p><p>個別出来高、52週高値更新、ニュース、業績は未取得です。<a href="data/history/latest.json" target="_blank" rel="noopener">使用中の市場データJSON</a></p></details></section>`;}
function card(c){const story=S?.get(c.ticker),r=story||reportFor(c.ticker);return `<article class="card op-card" id="review-${e(c.ticker)}"><h3>${e(c.ticker)}</h3>${story?S.summary(story):reportView(r,c)}
  ${story&&c.reviewedReportId&&c.reviewedReportId!==story.id?'<p class="op-alert">前回の判断は別の資料・判定方式に対するものです。今回のストーリーを読み直してください。</p>':''}
  <div class="op-personal"><h4>あなたの判断 <span class="op-note">任意</span></h4>
  <p class="op-note">読むだけでも使えます。市場データが更新されても、あなたの判断・メモは保持します。</p>
  <form data-review="${e(c.ticker)}" data-report="${e(r?.id||'')}"><label class="op-field">${story?'ストーリー':'見る理由'}への判断<select name="judgment">${judgments.map(v=>`<option ${v===(c.judgment||'未判断')?'selected':''}>${v}</option>`).join('')}</select></label>
  <label class="op-field">メモ（必要なときだけ）<textarea name="note" maxlength="10000" placeholder="納得した点、気になる反証など">${e(c.note||'')}</textarea></label><button class="op-btn" type="submit">判断・メモを保存</button></form>
  ${c.reviewedReportId?`<p class="op-note">判断時のデータ：${e(c.reviewedReportId)}</p>`:''}</div>
  <details class="op-legacy"><summary>以前のメモ・詳細な監視条件</summary><p class="op-note">これまで入力した内容は、この中に保持しています。</p><form data-ticker="${e(c.ticker)}"><label class="op-field">運用の軸<select name="lane"><option value="story" ${c.lane==='story'?'selected':''}>ストーリー投資</option><option value="technical" ${c.lane==='technical'?'selected':''}>テクニカル売買</option></select></label><div class="op-form-grid">${Object.keys(fields).map(k=>field(c,k)).join('')}</div><button class="op-btn" type="submit">詳細メモを保存</button></form></details></article>`;}
function render(){const root=document.getElementById('opportunity');if(!root)return;root.querySelectorAll('form[data-dirty=true]').forEach(f=>drafts.set(draftKey(f),{values:Object.fromEntries(new FormData(f)),reportId:f.dataset.report}));const latest=window.watchLatest,prev=window.watchPrevious;discovery=R.derive(latest,prev?.data);const today=new Date().toLocaleDateString('sv-SE');const diff=latest?changes(latest,prev?.data):[];const selected=data.cards.filter(c=>c.lane===lane).sort((a,b)=>Number(!!reportFor(b.ticker))-Number(!!reportFor(a.ticker)));const queue=selected.filter(c=>priority(c,today)<4).sort((a,b)=>priority(a,today)-priority(b,today)||(a.date||'9999').localeCompare(b.date||'9999')).slice(0,3);const age=latest?Math.floor((Date.now()-Date.parse(latest.date+'T00:00:00Z'))/86400000):null;
root.innerHTML=`<div class="card op-hero"><div class="op-eyebrow">OPPORTUNITY WATCH / 攻めの準備</div><h2>選ばれる理由から、成長の先を考える。</h2><p>企業の魅力が、どう売上と利益につながるのか。ストーリーを読み、数字を確かめ、あなたが判断する。</p><p class="op-note">企業ストーリーと決算の実績を掲載。判断・メモは任意です。</p><p class="op-note">${latest?`地合い：${e(({correction:'調整局面',uptrend_under_pressure:'圧力下の上昇トレンド',confirmed_uptrend:'確認された上昇トレンド'})[latest.overall_trend_state]||latest.overall_trend_state)} / データ日 ${e(latest.date)} / 自動取得・未検証`:'市場データを取得できていません。判断カードは利用できます。'}${age>3?' / データが古いため最新状況を確認してください。':''}</p></div>
${S?S.render(storyTicker,data.cards):'<p class="op-alert">企業ストーリーを読み込めませんでした。再読み込みしてください。</p>'}
<details class="card op-market-extra"><summary>補足：値動きから見つける変化</summary>${discoveryView()}</details>
<h3>自分の監視銘柄・任意のメモ</h3><p class="op-note">収録済みの企業はストーリーを読んで判断できます。未収録の企業はメモを残せますが、銘柄追加だけでは企業分析は作られません。</p>
<div class="op-actions"><button type="button" class="op-btn" data-lane="story" aria-pressed="${lane==='story'}">ストーリー投資</button><button type="button" class="op-btn" data-lane="technical" aria-pressed="${lane==='technical'}">テクニカル売買</button></div>
<div class="op-actions"><form id="op-add"><label>銘柄追加 <input aria-label="追加するティッカー" name="ticker" placeholder="例：MSFT" maxlength="12" required></label> <button class="op-btn">追加</button></form><button class="op-btn" id="op-export">バックアップ保存</button><label class="op-btn">バックアップ復元<input id="op-import" type="file" accept="application/json,.json" hidden></label></div><p class="op-note">カードはこの端末・ブラウザだけに保存します。端末間の自動同期はありません。</p><p id="op-status" class="op-status" role="status">${e(storageError)}</p><div class="op-grid">${selected.map(card).join('')||'<p class="op-empty">この運用のカードはありません。銘柄を追加してください。</p>'}</div><div class="card"><h3>自分で設定した確認候補 · 最大3件</h3><p class="op-note">反証あり → 確認日到来 → 条件に進展 → 条件確認済み、の順。購入順位ではありません。</p>${queue.length?queue.map(c=>`<p class="op-log"><strong>${e(c.ticker)}</strong> · ${e(c.state)} · ${e(c.event||'根拠と価格条件を点検')} / ${e(c.date||'日付未設定')}</p>`).join(''):'<p class="op-empty">該当なし。未設定・欠損から候補を推定しません。</p>'}</div>
<div class="grid2"><section class="card"><h3>テーマの変化</h3><p class="op-note">${prev?`${e(prev.date)} → ${e(latest?.date)}（取得できた直前の履歴との比較）`:'比較用の履歴 '+(window.watchHistoryLoaded?'なし':'読み込み中')} / 自動取得・未検証</p>${diff.length?diff.map(d=>`<p class="op-log">${e(d.name)} (${e(d.ticker)})：${e(d.from)} → <strong>${e(d.to)}</strong></p>`).join(''):`<p class="op-empty">${prev?'象限の変化なし。':'比較結果は未判定。'}</p>`}<p class="op-note">ETFの相対的な値動きです。資金流入や企業利益の改善を直接確認したものではありません。</p></section><section class="card"><h3>判断カードの更新履歴</h3>${data.log.length?data.log.slice(0,5).map(l=>`<p class="op-log"><span class="op-note">${e(new Date(l.at).toLocaleString('ja-JP'))}</span><br>${e(l.text)}</p>`).join(''):'<p class="op-empty">まだ更新はありません。</p>'}</section></div>
`;
root.querySelectorAll('form').forEach(f=>{const draft=drafts.get(draftKey(f));if(!draft)return;for(const [k,v]of Object.entries(draft.values)){if(f.elements.namedItem(k))f.elements.namedItem(k).value=v;}if(draft.reportId!==undefined)f.dataset.report=draft.reportId;f.dataset.dirty='true';if(f.closest('details'))f.closest('details').open=true;});
root.querySelectorAll('form[data-review]').forEach(f=>f.onsubmit=ev=>{
  ev.preventDefault();if(storageError){message(storageError);return;}
  const values=Object.fromEntries(new FormData(f));
  const current=data.cards.find(c=>c.ticker===f.dataset.review);
  const reportId=f.dataset.report||null;
  if(values.judgment!=='未判断'&&!reportId){message('この銘柄のストーリー・市場データがないため、判断は未設定です。メモだけなら「未判断」のまま保存できます。');return;}
  const next={...current,judgment:values.judgment,note:values.note,reviewedReportId:values.judgment==='未判断'?null:reportId,updated:new Date().toISOString()};
  const updated={...data,cards:data.cards.map(c=>c.ticker===next.ticker?next:c),log:[{at:next.updated,text:`${next.ticker}：判断・メモを更新（${next.judgment}）`},...data.log].slice(0,200)};
  if(!validate(updated)){message('入力内容が無効です。');return;}
  if(persist(updated)){forgetDraft(f);pendingMarket=false;render();message(`${next.ticker} の判断・メモを保存しました。`);}
});
root.querySelectorAll('[data-open-review]').forEach(b=>b.onclick=()=>{lane=data.cards.find(c=>c.ticker===b.dataset.openReview)?.lane||'story';render();const f=root.querySelector(`form[data-review="${b.dataset.openReview}"]`);f?.querySelector('select')?.focus();});
root.querySelectorAll('[data-story]').forEach(b=>b.onclick=()=>{storyTicker=b.dataset.story;render();document.getElementById('story-detail')?.focus();});
root.querySelectorAll('[data-watch]').forEach(b=>b.onclick=()=>{
  if(storageError){message(storageError);return;}
  if(data.cards.some(c=>c.ticker===b.dataset.watch))return;
  if(data.cards.length>=100){message('監視銘柄は100件までです。');return;}
  if(persist({...data,cards:[...data.cards,seed(b.dataset.watch)]})){lane='story';render();message(`${b.dataset.watch} を監視に追加しました。`);}
});
root.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{
  const r=reportFor(b.dataset.copy);if(!r)return;
  try{await navigator.clipboard.writeText(R.briefing(r,discovery.date,discovery.previousDate));message('調査メモをコピーしました。');}
  catch{message('自動コピーできません。表示された調査メモを選択してコピーしてください。');}
});
root.querySelectorAll('form').forEach(f=>f.addEventListener('input',()=>{f.dataset.dirty='true';}));
root.querySelectorAll('details').forEach(d=>d.addEventListener('toggle',()=>{if(!d.open&&pendingMarket)refreshAnalysis();}));
root.querySelectorAll('[data-lane]').forEach(b=>b.onclick=()=>{lane=b.dataset.lane;render();});
root.querySelectorAll('form[data-ticker]').forEach(f=>f.onsubmit=ev=>{ev.preventDefault();if(storageError){message(storageError);return;}const original=data.cards.find(c=>c.ticker===f.dataset.ticker),next={...original,...Object.fromEntries(new FormData(f))};if(['条件に進展','条件を確認済み','反証あり'].includes(next.state)&&!next.evidence.trim()){message('状態の根拠・出典・確認日を入力してください。');return;}if(next.verified==='TradingView確認済み'&&!next.price.trim()){message('TradingViewの確認内容と確認日を価格条件に記録してください。');return;}const changed=['lane',...Object.keys(fields)].filter(k=>next[k]!==original[k]);if(!changed.length){forgetDraft(f);if(pendingMarket)refreshAnalysis();message('変更はありません。');return;}next.updated=new Date().toISOString();const log={at:next.updated,text:`${next.ticker}：${changed.map(k=>fields[k]||'運用の軸').join('・')} を更新（${original.state} → ${next.state}）`};if(persist({...data,cards:data.cards.map(c=>c.ticker===next.ticker?next:c),log:[log,...data.log].slice(0,200)})){forgetDraft(f);render();message(`${next.ticker} を保存しました。`);}});
root.querySelector('#op-add').onsubmit=ev=>{ev.preventDefault();if(storageError){message(storageError);return;}const ticker=new FormData(ev.target).get('ticker').trim().toUpperCase();if(!/^[A-Z0-9.^-]{1,12}$/.test(ticker)||data.cards.some(c=>c.ticker===ticker)||data.cards.length>=100){message('ティッカーが無効・登録済み、または100件の上限です。');return;}if(persist({...data,cards:[...data.cards,{...seed(ticker),lane}]})){forgetDraft(ev.target);render();}};
root.querySelector('#op-export').onclick=()=>{if(storageError){message('読み込みエラーのためバックアップ出力を停止しています。');return;}const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=`opportunity-watch-${today}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
root.querySelector('#op-import').onchange=async ev=>{const file=ev.target.files[0];if(!file)return;try{if(file.size>5000000)throw Error();const imported=JSON.parse(await file.text());if(!validate(imported))throw Error();if(!confirm('現在の判断カードをバックアップの内容で置き換えますか？'))return;if(persist(imported)){clearDrafts();render();message('バックアップを復元しました。');}}catch{message('復元できません。有効な機会ウォッチのJSONを選んでください。');}finally{ev.target.value='';}};
}
function view(name){const offense=name==='opportunity'||name.startsWith('review-');document.getElementById('opportunity').hidden=!offense;document.getElementById('content').hidden=offense;document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===(offense?'opportunity':'climate'))));}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{location.hash=b.dataset.view;view(b.dataset.view);});
window.addEventListener('hashchange',()=>view((location.hash==='#opportunity'||location.hash.startsWith('#review-'))?'opportunity':'climate'));
function refreshAnalysis(){
  if(document.querySelector('#opportunity form[data-dirty=true]')){pendingMarket=true;message('新しいデータを受信しました。編集中の内容を保存すると表示に反映されます。');return;}
  pendingMarket=false;render();
}
window.addEventListener('watch-data',refreshAnalysis);
render();view((location.hash==='#opportunity'||location.hash.startsWith('#review-'))?'opportunity':'climate');
})();
