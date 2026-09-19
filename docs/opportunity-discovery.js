/* Research selection only. No investment probabilities or generated financial facts. */
(function(root){
'use strict';
const R=typeof module!=='undefined'&&module.exports?require('./opportunity-rules.js'):root.OpportunityRules;
const METHOD='broad-close-return-252-percentile-v1';
const finite=x=>typeof x==='number'&&Number.isFinite(x);
function universe(snapshot){
 const u=snapshot?.opportunity_universe;
 if(u!=null){
  if(u.method!==METHOD||!Array.isArray(u.rows))return {map:new Map(),bad:new Set(),scope:'unsupported',key:null};
  const result=R.rows({universe:u.rows},['universe']);
  for(const [ticker,row]of result.map)if(row.observed_date!==snapshot.date){result.map.delete(ticker);result.bad.add(ticker);}
  return {...result,scope:'broad',key:`${u.method}:${u.source}`,rankedCount:u.ranked_count};
 }
 return {...R.rows(snapshot),scope:'legacy',key:`legacy-top-lists:${snapshot?.breadth_universe_source||'unknown'}`};
}
function qualifies(r){return !!r&&finite(r.day_change_pct)&&finite(r.rs_percentile)&&r.rs_percentile>=90&&r.above_sma50===true&&finite(r.one_month_pct)&&r.one_month_pct>0&&finite(r.three_month_pct)&&r.three_month_pct>0;}
function select(latest,previous,today=new Date().toISOString().slice(0,10)){
 const empty={date:null,previousDate:null,candidates:[],all:[],cautions:[],excluded:[],coverage:0,scope:'none',stale:false,comparable:false};
 if(!R.validDate(latest?.date)||!R.validDate(today)||latest.date>today)return empty;
 const current=universe(latest),prior=universe(previous);
 const gap=R.validDate(previous?.date)?(Date.parse(latest.date)-Date.parse(previous.date))/86400000:0;
 const comparable=!!current.key&&current.key===prior.key&&gap>0&&gap<=7;
 const stale=(Date.parse(today)-Date.parse(latest.date))/86400000>4;
 const all=[],cautions=[];
 for(const [ticker,row]of current.map){
  const before=comparable?prior.map.get(ticker):null;
  if(row.above_sma50===false||(finite(row.day_change_pct)&&row.day_change_pct<=-3)){
   cautions.push({ticker,row,reason:row.above_sma50===false?'50日線より下':'当日3%以上の下落'});continue;
  }
  if(!qualifies(row))continue;
  const persistent=qualifies(before);
  const reasons=[`市場内RS百分位 ${row.rs_percentile.toFixed(1)}（年間騰落率による順位）`,`1か月 ${R.pct(row.one_month_pct)}・3か月 ${R.pct(row.three_month_pct)}。両期間とも上昇`,`50日移動平均線より上`,persistent?`${previous.date}と${latest.date}の2時点で同じ条件を満たす（間の全日を確認した意味ではありません）`:'比較可能な過去の条件充足を確認できないため、継続性は未確認'];
  all.push({ticker,row,persistent,reasons,id:`discovery-v1:${latest.date}:${ticker}`,researchStatus:'業績・堀・株価への織り込みは未検証'});
 }
 all.sort((a,b)=>Number(b.persistent)-Number(a.persistent)||b.row.rs_percentile-a.row.rs_percentile||a.ticker.localeCompare(b.ticker));
 return {...empty,date:latest.date,previousDate:comparable?previous.date:null,comparable,stale,scope:current.scope,coverage:current.map.size,rankedCount:current.rankedCount,excluded:[...current.bad].sort(),all,candidates:stale?[]:all.slice(0,3),cautions};
}
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function render(result,stories,cards){
 const list=xs=>`<ul>${xs.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`;
 return `<section class="op-discovery op-data-led" aria-label="データから選んだ調査候補"><h3>データから選んだ調査候補</h3>
 <p>市場で強さが見える企業について、その背景に売上・利益の改善と持続する競争優位があるかを調べます。候補入りだけでは、良い企業・割安・買い時とは判断しません。</p>
 <p class="op-note">データ日 ${esc(result.date||'未取得')} / 比較日 ${esc(result.previousDate||'比較不可')} / 自動取得・未検証</p>
 <p class="op-note">${result.scope==='broad'?'既存の日次処理で取得した市場データから、価格・売買代金などの条件を通過した範囲':result.scope==='legacy'?'旧データのため、RS上位20件とトレンド条件上位20件の範囲のみ':result.scope==='unsupported'?'未対応のデータ形式のため抽出を停止':'市場データを取得できていません'}：${result.coverage}銘柄。抽出条件に合う${result.all.length}件から最大3件を表示。</p>
 ${result.stale?'<p class="op-alert">データ日から4日を超えています。更新されるまで現在の候補は表示しません。</p>':''}
 <div class="op-grid">${result.candidates.map(r=>`<article class="card op-fundamental-candidate"><p class="op-tag">${r.persistent?'2時点で強さを確認':'継続性の確認待ち'} · 調査候補</p><h3>${esc(r.ticker)}</h3><h4>なぜ、この企業を取り上げるのか</h4>${list(r.reasons)}<p><strong>${esc(r.researchStatus)}</strong></p>
 <h4>次に検証すること</h4><p>直近決算と前年同期を照合し、需要や単価の変化が売上、利益、現金収入へどう伝わったかを調べます。企業が語る成長と、実績で確認できる成長を分けます。</p><p>競合より選ばれる理由が、価格・顧客の継続利用・コストのどこに表れているかを確認します。その優位性を競合が崩せる条件と、成長に必要な追加投資も検証します。</p>
 ${stories?.get(r.ticker)?`<p>既存の企業資料があります。今回の選定理由との整合性や鮮度は、まだ再検証していません。</p><button class="op-btn" data-story="${esc(r.ticker)}">保存済みの企業資料を確認</button>`:'<p class="op-note">この銘柄の企業分析は未収録です。株価データから業績や堀を推定して埋めることはしません。</p>'}
 <button class="op-btn" data-watch="${esc(r.ticker)}" ${cards.some(c=>c.ticker===r.ticker)?'disabled':''}>${cards.some(c=>c.ticker===r.ticker)?'監視に登録済み':'監視に追加'}</button> <a class="op-btn" href="https://chatgpt.com/" target="_blank" rel="noopener noreferrer">ChatGPTを開く ↗</a></article>`).join('')||'<div class="card"><p>表示できる調査候補はありません。固定の企業紹介で候補を補充しません。</p></div>'}</div>
 <details class="card"><summary>選び方と、企業分析の合格条件</summary><p>入口の条件：RS百分位90以上、1か月・3か月ともプラス、50日線より上。当日3%以上下落した銘柄は注意欄へ分けます。2時点で条件を満たす企業を先に、次にRS百分位、同点はティッカー順に並べます。これは調べる順番で、期待収益の順位ではありません。閾値の投資成績は未検証です。</p><p>RSは広い市場内の年間騰落率の百分位です。監視銘柄だけで計算したGoogle SheetsのRSと混ぜません。母集団の構成が変われば順位も変わります。旧上位リストと新しい全件出力の切り替え時には過去比較を停止します。</p><p>企業分析では、①何を誰に売りどう儲けるか、②事業別の成長と利益への波及、③競争優位の根拠と反証、④投資負担とキャッシュフロー、⑤株価に必要とされる成長、⑥最有力シナリオ・方向感・壊れる条件2〜3個を、資料の日付と出典を付けて確認します。文章の長さや知名度で合格扱いにはしません。</p><p>決算資料を取得・分析して自動更新する機能は、まだありません。今回の日次更新は候補抽出までです。セクターETFの強さは市場の背景として利用し、個別企業への資金流入や堀の証拠とは扱いません。</p><a href="data/history/latest.json" target="_blank" rel="noopener">抽出に使ったデータを見る</a></details>
 ${result.cautions.length?`<details class="card"><summary>悪化・下落を確認する企業 ${result.cautions.length}件</summary>${list(result.cautions.map(r=>`${r.ticker}：${r.reason}`))}</details>`:''}
 ${result.excluded.length?`<p class="op-alert">数値の不整合・異常値・対象日不一致による保留：${esc(result.excluded.join(', '))}</p>`:''}</section>`;
}
const api={select,render,qualifies};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.OpportunityDiscovery=api;
})(typeof window!=='undefined'?window:this);
