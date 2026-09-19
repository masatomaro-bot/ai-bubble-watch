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
function researchPrompt(ticker,result){
 if(typeof ticker!=='string'||!/^[A-Z0-9.^-]{1,12}$/.test(ticker))throw Error('Invalid ticker');
 const r=result?.all?.find(x=>x.ticker===ticker);
 const context=r?`抽出日${result.date}。自動取得・未検証：RS百分位${r.row.rs_percentile}、1か月${R.pct(r.row.one_month_pct)}、3か月${R.pct(r.row.three_month_pct)}。これは価格条件の通過で、事業の優秀さや堀は未確認。`:'価格条件で選ばれた調査候補で、事業の優秀さや堀は未確認。';
 return `米国上場銘柄 ${ticker} を日本語で深掘りしてください。最初に正式社名・取引所・事業を照合し、同定できなければ断定しないでください。${context}
最新の企業IR・SEC開示を検索し、資料日・対象期間・出典リンクを示してください。検索できない場合はその旨を明示し、古い記憶を最新情報として扱わないでください。
結論を先に、その企業ならではの因果関係を段落で説明してください。50日線などのテクニカル説明は不要です。
何を誰に売り、どう利益が残るか。事業別売上・成長率・営業利益・利益率・営業CF・設備投資・現金・負債を直近と前年同期で比較し、数字の意味を説明してください。GAAPと調整後、一時要因を分け、未取得値を捏造・補間しないでください。
顧客が競合より選ぶ理由と、競合が模倣しにくい仕組みを具体的な証拠で検証してください。堀がなければないと述べ、強みが売上・利益につながる経路と崩れる条件を示してください。開発段階企業なら承認・商業化・資金繰り・希薄化、循環企業なら供給増と価格下落も調べてください。
成長の源泉、最も強い反証、現在株価に織り込まれた期待を検証し、最後に最有力シナリオとその理由、強気・中立・弱気、壊れる条件2〜3個を提示してください。事業評価と株価評価を分け、確率は根拠がある場合のみ数値化。売買指示は不要です。Web数値は暫定として扱い、事実と考察を区別してください。`;
}
function researchUrl(ticker,result){return 'https://chatgpt.com/?q='+encodeURIComponent(researchPrompt(ticker,result));}
function researchControls(ticker,result){return `<a class="op-btn op-research-primary" href="${esc(researchUrl(ticker,result))}" target="_blank" rel="noopener noreferrer">${esc(ticker)}の事業・決算・堀をChatGPTで調べる ↗</a><details class="op-research-fallback"><summary>質問が引き継がれない場合</summary><p class="op-note">下の質問をコピーし、ChatGPTの入力欄に貼り付けて送信してください。</p><textarea class="op-brief" data-company-prompt="${esc(ticker)}" aria-label="${esc(ticker)}の企業分析の質問" readonly>${esc(researchPrompt(ticker,result))}</textarea><button type="button" class="op-btn" data-company-copy="${esc(ticker)}">質問をコピー</button><p data-company-status="${esc(ticker)}" role="status"></p></details>`;}
function render(result,stories,cards){
 const list=xs=>`<ul>${xs.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`;
 return `<section class="op-discovery op-data-led" aria-label="データから選んだ調査候補"><h3>データから選んだ調査候補</h3>
 <p>市場で強さが見える企業について、その背景に売上・利益の改善と持続する競争優位があるかを調べます。候補入りだけでは、良い企業・割安・買い時とは判断しません。</p>
 <p class="op-note">データ日 ${esc(result.date||'未取得')} / 比較日 ${esc(result.previousDate||'比較不可')} / 自動取得・未検証</p>
 <p class="op-note">${result.scope==='broad'?'既存の日次処理で取得した市場データから、価格・売買代金などの条件を通過した範囲':result.scope==='legacy'?'旧データのため、RS上位20件とトレンド条件上位20件の範囲のみ':result.scope==='unsupported'?'未対応のデータ形式のため抽出を停止':'市場データを取得できていません'}：${result.coverage}銘柄。抽出条件に合う${result.all.length}件から最大3件を表示。</p>
 ${result.stale?'<p class="op-alert">データ日から4日を超えています。更新されるまで現在の候補は表示しません。</p>':''}
 <div class="op-grid">${result.candidates.map(r=>`<article class="card op-fundamental-candidate"><p class="op-tag">${r.persistent?'2時点で強さを確認':'継続性の確認待ち'} · 調査候補</p><h3>${esc(r.ticker)}</h3><p class="op-note">価格の抽出条件を通過。企業の実力はこれから確認します。</p>
 ${researchControls(r.ticker,result)}
 ${stories?.get(r.ticker)?`<button class="op-btn" data-story="${esc(r.ticker)}">保存済みの企業資料を確認</button>`:''}
 <button class="op-btn" data-watch="${esc(r.ticker)}" ${cards.some(c=>c.ticker===r.ticker)?'disabled':''}>${cards.some(c=>c.ticker===r.ticker)?'監視に登録済み':'監視に追加'}</button>
 <details class="op-selection-evidence"><summary>抽出条件・数値を確認</summary>${list(r.reasons)}<p>${esc(r.researchStatus)}</p></details></article>`).join('')||'<div class="card"><p>表示できる調査候補はありません。固定の企業紹介で候補を補充しません。</p></div>'}</div>
 <details class="card"><summary>選び方と、企業分析の合格条件</summary><p>入口の条件：RS百分位90以上、1か月・3か月ともプラス、50日線より上。当日3%以上下落した銘柄は注意欄へ分けます。2時点で条件を満たす企業を先に、次にRS百分位、同点はティッカー順に並べます。これは調べる順番で、期待収益の順位ではありません。閾値の投資成績は未検証です。</p><p>RSは広い市場内の年間騰落率の百分位です。監視銘柄だけで計算したGoogle SheetsのRSと混ぜません。母集団の構成が変われば順位も変わります。旧上位リストと新しい全件出力の切り替え時には過去比較を停止します。</p><p>企業分析では、①何を誰に売りどう儲けるか、②事業別の成長と利益への波及、③競争優位の根拠と反証、④投資負担とキャッシュフロー、⑤株価に必要とされる成長、⑥最有力シナリオ・方向感・壊れる条件2〜3個を、資料の日付と出典を付けて確認します。文章の長さや知名度で合格扱いにはしません。</p><p>決算資料を取得・分析して自動更新する機能は、まだありません。今回の日次更新は候補抽出までです。セクターETFの強さは市場の背景として利用し、個別企業への資金流入や堀の証拠とは扱いません。</p><a href="data/history/latest.json" target="_blank" rel="noopener">抽出に使ったデータを見る</a></details>
 ${result.cautions.length?`<details class="card"><summary>悪化・下落を確認する企業 ${result.cautions.length}件</summary>${list(result.cautions.map(r=>`${r.ticker}：${r.reason}`))}</details>`:''}
 ${result.excluded.length?`<p class="op-alert">数値の不整合・異常値・対象日不一致による保留：${esc(result.excluded.join(', '))}</p>`:''}</section>`;
}
const api={select,render,qualifies,researchPrompt,researchUrl};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.OpportunityDiscovery=api;
})(typeof window!=='undefined'?window:this);
