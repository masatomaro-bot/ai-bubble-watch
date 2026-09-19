/* Deterministic explanations over existing snapshots. No network or AI calls. */
(function(root){
'use strict';
const fields=['rs_percentile','day_change_pct','one_month_pct','three_month_pct','above_sma50'];
const finite=x=>typeof x==='number'&&Number.isFinite(x);
const validDate=x=>typeof x==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(x)&&Number.isFinite(Date.parse(x))&&new Date(x).toISOString().slice(0,10)===x;
const pct=x=>finite(x)?`${x>0?'+':''}${x.toFixed(2)}%`:'未取得';
function rows(snapshot,names=['market_leaders','trend_template_leaders']){
  const map=new Map(),bad=new Set();
  for(const name of names){
    for(const row of Array.isArray(snapshot?.[name])?snapshot[name]:[]){
      if(!row||typeof row.ticker!=='string'||!/^[A-Z0-9.^-]{1,12}$/.test(row.ticker))continue;
      const prior=map.get(row.ticker);
      if(prior&&fields.some(k=>prior[k]!==row[k]))bad.add(row.ticker);
      map.set(row.ticker,{...row,template:name==='trend_template_leaders'||!!prior?.template});
    }
  }
  for(const [ticker,row]of map){
    if(fields.slice(0,4).some(k=>row[k]!=null&&!finite(row[k]))||
      (row.above_sma50!=null&&typeof row.above_sma50!=='boolean')||
      (finite(row.rs_percentile)&&(row.rs_percentile<0||row.rs_percentile>100))||
      (finite(row.day_change_pct)&&Math.abs(row.day_change_pct)>50)||
      (finite(row.one_month_pct)&&Math.abs(row.one_month_pct)>200)||
      (finite(row.three_month_pct)&&Math.abs(row.three_month_pct)>500))bad.add(ticker);
  }
  for(const ticker of bad)map.delete(ticker);
  return {map,bad};
}
function derive(latest,previous,today=new Date().toISOString().slice(0,10)){
  const empty={date:null,previousDate:null,candidates:[],all:[],byTicker:{},excluded:[],coverage:0,stale:false,notice:'市場データを読み込み中、または取得できていません。'};
  if(!latest||!validDate(latest.date))return empty;
  const age=validDate(today)?(Date.parse(today)-Date.parse(latest.date))/86400000:0;
  if(age<0)return {...empty,notice:'市場データの日付が未来になっています。日付を確認するまで候補を表示しません。'};
  const current=rows(latest),gap=previous&&validDate(previous.date)?(Date.parse(latest.date)-Date.parse(previous.date))/86400000:0;
  const comparable=gap>0&&gap<=7;
  const before=comparable?rows(previous):{map:new Map(),bad:new Set()};
  const results=[];
  for(const [ticker,row]of current.map){
    const prev=before.map.get(ticker),signals=[];
    const add=(rank,text,caution=false)=>signals.push({rank,text,caution});
    if(prev?.above_sma50===false&&row.above_sma50===true)add(80,'50日移動平均線の下から上へ変化しました。');
    if(prev?.above_sma50===true&&row.above_sma50===false)add(90,'50日移動平均線の上から下へ変化しました。',true);
    if(comparable&&!before.bad.has(ticker)){
      const oldTable=previous.trend_template_leaders;
      if(row.template&&Array.isArray(oldTable)&&oldTable.length&& !oldTable.some(x=>x?.ticker===ticker))
        add(70,'トレンド条件合格の上位リストに、比較日にはなく今回掲載されました。合格した初日とは限りません。');
      else if(!prev&&Array.isArray(previous.market_leaders)&&previous.market_leaders.length)
        add(65,'取得した上位リストに、比較日にはなく今回掲載されました。市場全体での初登場を意味しません。');
    }
    if(prev&&finite(prev.rs_percentile)&&finite(row.rs_percentile)){
      const delta=row.rs_percentile-prev.rs_percentile;
      if(Math.abs(delta)>=1)add(delta<0?61:60,`RS百分位が${prev.rs_percentile.toFixed(1)}から${row.rs_percentile.toFixed(1)}へ${delta>0?'上昇':'低下'}しました（${delta>0?'+':''}${delta.toFixed(1)}ポイント）。`,delta<0);
    }
    if(finite(row.day_change_pct)&&row.day_change_pct<=-3)add(50,`前日比${pct(row.day_change_pct)}。下落の材料と持続性を確認する候補です。`,true);
    if(finite(row.day_change_pct)&&row.day_change_pct>=3&&row.above_sma50===true&&finite(row.rs_percentile)&&row.rs_percentile>=90)
      add(40,`前日比${pct(row.day_change_pct)}、50日線より上、RS百分位${row.rs_percentile.toFixed(1)}。強い値動きの背景を確認する候補です。`);
    const caution=signals.some(s=>s.caution)||row.above_sma50===false;
    const limitations=['出来高増加・高値更新・決算内容・割安さは、このデータからは判定していません。'];
    if(!prev)limitations.push('同じ銘柄の比較データがなく、50日線やRSの変化は未判定です。');
    if(finite(row.one_month_pct)&&row.one_month_pct<0&&finite(row.day_change_pct)&&row.day_change_pct>0)
      limitations.push(`当日は上昇していますが、1か月では${pct(row.one_month_pct)}です。短期反発だけの可能性があります。`);
    if(row.above_sma50===false)limitations.push('株価は50日線より下です。RSが高いだけでは上昇傾向とはいえません。');
    const record={ticker,id:`rules-v1:${latest.date}:${ticker}`,row,signals,caution,score:Math.max(0,...signals.map(s=>s.rank)),limitations,
      next:caution?'次の終値で50日線との位置を確認し、企業IRで下落材料・決算の変化がないか確認する。':'上昇が次の終値でも続くか、チャートで出来高が増えているか、企業IRで決算の裏付けがあるか確認する。'};
    results.push(record);
  }
  const all=results.filter(x=>x.signals.length).sort((a,b)=>b.score-a.score||(b.row.rs_percentile??-1)-(a.row.rs_percentile??-1)||a.ticker.localeCompare(b.ticker));
  return {date:latest.date,previousDate:comparable?previous.date:null,all,candidates:all.slice(0,3),byTicker:Object.fromEntries(results.map(r=>[r.ticker,r])),excluded:[...current.bad].sort(),coverage:current.map.size,stale:age>4,
    notice:age>4?'データ日から4日を超えています。過去データの参考表示です。':comparable?'取得できた直前の履歴との比較です。':'比較可能な履歴がないため、リスト初登場・50日線変化・RS変化は判定しません。'};
}
function briefing(result,date,previousDate){
  return [`${result.ticker} の調査用メモ（ルールによる抽出・AI分析ではありません）`,`データ日：${date} / 比較日：${previousDate||'なし'}`,
    ...result.signals.map(s=>`見る理由：${s.text}`),`前日比：${pct(result.row.day_change_pct)} / 1か月：${pct(result.row.one_month_pct)} / 3か月：${pct(result.row.three_month_pct)}`,
    ...result.limitations.map(s=>`未確認・注意：${s}`),`次の確認：${result.next}`,
    '深掘りする場合：企業の直近一次資料を確認し、この値動きが売上・利益の変化を伴うか、反証とともに説明してください。データの欠損から推定しないでください。'].join('\n');
}
const api={derive,briefing,pct,rows,validDate};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.OpportunityRules=api;
})(typeof window!=='undefined'?window:this);
