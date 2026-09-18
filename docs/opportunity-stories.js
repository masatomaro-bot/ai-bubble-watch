(function(root){
'use strict';
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const valid=x=>typeof x==='number'&&Number.isFinite(x);
function growth(previous,current){return valid(previous)&&previous>0&&valid(current)?(current/previous-1)*100:null;}
function margin(revenue,operating){return valid(revenue)&&revenue>0&&valid(operating)?operating/revenue*100:null;}
const pct=x=>valid(x)?`${x>0?'+':''}${x.toFixed(1)}%`:'未収録';
const amount=x=>valid(x)?`${(x/100).toLocaleString('ja-JP',{maximumFractionDigits:1})}億ドル`:'未収録';
function get(ticker){return (root.OpportunityStoriesData||[]).find(s=>s.ticker===ticker);}
function sourceLinks(s){return s.sources.filter(x=>/^https:\/\//.test(x.url)).map(x=>`<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.label)} ↗</a>`).join('');}
function chart(s,key,label){
  const values=s[key],max=Math.max(1,...values.filter(valid).map(Math.abs)),signed=values.some(x=>valid(x)&&x<0);
  return `<figure class="story-chart"><figcaption>${esc(label)} <span>実績・億ドル / ゼロ基準</span></figcaption>${values.map((v,i)=>`<div class="story-bar-row"><span>${esc(i?s.period:s.previousPeriod)}</span><strong>${amount(v)}</strong><div class="story-track ${signed?'is-signed':''}" aria-hidden="true">${valid(v)?`<span class="story-bar ${i?'current':'previous'} ${v<0?'negative':''}" style="width:${Math.abs(v)/max*(signed?50:100)}%;left:${signed?(v<0?50-Math.abs(v)/max*50:50):0}%"></span>`:''}</div></div>`).join('')}<p class="op-note">${signed?'中央がゼロ。左が赤字、右が黒字。':'棒の長さはこの指標内の比較。'} 未収録はゼロではありません。</p></figure>`;
}
function freshness(s,now=Date.now()){
 const t=Date.parse(s.publishedAt+'T00:00:00Z');
 if(!Number.isFinite(t)||t>now)return '資料日を確認してください。現在の判断には使わず、出典を照合してください。';
 return now-t>120*86400000?'決算発表から120日以上経過しています。次の決算を確認するまで過去の参考情報としてお読みください。':'';
}
const focusMetrics={
 SBUX:[['既存店の客数・客単価','値上げによる増収か、また通う人が増えたのかを見る。'],['店舗の営業利益率','人件費・改装費を吸収できるか。一時利益を分ける。'],['連結範囲と継続収益','事業売却の代金・売却益・失う売上・残るロイヤルティを分ける。']],
 GOOGL:[['検索・Cloudの売上成長','主力と次の成長源を分けて見る。'],['Cloudの営業利益率','成長が利益につながっているかを見る。'],['設備投資とフリーキャッシュフロー','投資後に残る現金を確認。投資評価益と本業の利益を分ける。']],
 AAPL:[['製品別売上とServices売上','買い替え需要と継続利用の収益を分ける。'],['粗利益率・営業利益率','一時的な還付などを除いて採算を見る。'],['営業キャッシュフロー','会計上の増益が現金の増加を伴うか確認。']],
 NVDA:[['Data Center売上成長','需要拡大が出荷・売上へつながっているかを見る。'],['粗利益率','製品移行・価格・供給コストによる変化を見る。'],['在庫・売掛金と営業キャッシュフロー','売上に対して在庫や未回収代金が膨らんでいないか確認。']],
 AVGO:[['AI半導体とソフトの売上','成長の源泉を事業ごとに分ける。'],['営業利益率と利益の調整項目','GAAPと調整後利益の差を確認。'],['フリーキャッシュフローと負債','成長投資と債務返済を支える現金を見る。']]
};
function researchLinks(s){return `<section class="story-research" aria-label="${esc(s.ticker)}の調査リンク"><h4>注目する財務と、調べる入口</h4><dl class="story-focus">${(focusMetrics[s.ticker]||[]).map(([label,why])=>`<div><dt>${esc(label)}</dt><dd>${esc(why)}</dd></div>`).join('')}</dl><p class="op-note">確認する項目の案内です。最新値は決算資料で確認してください。</p><nav class="op-actions" aria-label="${esc(s.ticker)}の外部リンク"><a class="op-btn" href="https://chatgpt.com/" target="_blank" rel="noopener noreferrer">ChatGPTを開く ↗</a><a class="op-btn" href="https://www.tradingview.com/symbols/NASDAQ-${encodeURIComponent(s.ticker)}/" target="_blank" rel="noopener noreferrer">${esc(s.ticker)}のチャート ↗</a>${s.sources.filter(x=>/^https:\/\//.test(x.url)).map(x=>`<a class="op-btn" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.label)} ↗</a>`).join('')}</nav><p class="op-note">質問文はご自身でChatGPTに入力してください。この会話へ戻る場合は、開いている会話のタブを使ってください。</p></section>`;}
function summary(s){return `<div class="story-saved-summary"><p class="op-tag">${esc(s.name)} · ${esc(s.period)} のストーリー</p><h4>${esc(s.title)}</h4><p>${esc(s.interpretation)}</p><button type="button" class="op-btn" data-story="${esc(s.ticker)}">ストーリーと成長を見る</button></div>`;}
function render(ticker,cards){
 const all=root.OpportunityStoriesData||[],s=get(ticker)||all[0];
 if(!s)return '<section class="card"><h3>企業ストーリーを読み込めませんでした</h3><p>画面を再読み込みしてください。保存済みメモは下で確認できます。</p></section>';
 const revenueGrowth=growth(...s.revenue),profitGrowth=growth(...s.operating),oldMargin=margin(s.revenue[0],s.operating[0]),newMargin=margin(s.revenue[1],s.operating[1]);
 const revenueText=revenueGrowth===null&&valid(s.reportedRevenueGrowth)?pct(s.reportedRevenueGrowth):pct(revenueGrowth);
 const age=freshness(s),registered=cards.some(c=>c.ticker===s.ticker);
 return `<section class="story-library" aria-label="企業のストーリーと成長">
 <div class="story-section-heading"><div><p class="op-eyebrow">BUSINESS → GROWTH → EVIDENCE</p><h3>わかる企業から、成長の機会を探す</h3></div><span class="story-count">収録 ${all.length} 社</span></div>
 <p class="op-note">企業を選ぶだけで読めます。収録企業は調査対象で、買い推奨の順位ではありません。</p>
 <div class="story-selector" role="group" aria-label="ストーリーを読む企業">${all.map(x=>`<button type="button" class="story-choice" data-story="${esc(x.ticker)}" aria-pressed="${x.ticker===s.ticker}"><strong>${esc(x.ticker)}</strong><span>${esc(x.name)}</span><small>${esc(x.sector)}</small></button>`).join('')}</div>
 <article class="story-detail card" id="story-detail" tabindex="-1" aria-label="${esc(s.ticker)}の企業分析">
 <header class="story-heading"><div><p class="op-tag">${esc(s.sector)} / ${esc(s.kind)}</p><h3>${esc(s.name)} <span>${esc(s.ticker)}</span></h3></div><span class="story-state">${revenueGrowth!==null&&profitGrowth!==null?(revenueGrowth>0&&profitGrowth>0?'実績：増収・増益':'実績を個別に確認'):'実績：一部照合待ち'}</span></header>
 <h4 class="story-title">${esc(s.title)}</h4><p class="story-value">${esc(s.value)}</p>
 <p class="op-note">資料：${esc(s.period)} / 発表 ${esc(s.publishedAt)} / 編集確認 ${esc(s.reviewedAt)} · ${esc(s.sourceLevel)}</p>
 ${age?`<p class="op-alert">${esc(age)}</p>`:''}
 ${researchLinks(s)}
 <div class="story-columns"><section><h4>01　何を売って、どう儲ける？</h4><p>${esc(s.business)}</p><h4>02　ここから伸びる筋道 <span class="op-note">編集した仮説</span></h4><ol class="story-chain">${s.chain.map(x=>`<li>${esc(x)}</li>`).join('')}</ol><p>${esc(s.thesis)}</p></section>
 <section class="story-numbers"><h4>03　数字で確かめる <span class="op-note">四半期実績</span></h4><div class="story-metrics"><div><span>売上成長・前年同期比</span><strong>${revenueText}</strong><small>${revenueGrowth===null?'報道値・比較元の金額は未照合':'決算額から計算'}</small></div><div><span>営業利益成長・前年同期比</span><strong>${pct(profitGrowth)}</strong><small>GAAP（会計基準に沿った実績）</small></div><div><span>営業利益率・今回</span><strong>${valid(newMargin)?newMargin.toFixed(1)+'%':'未収録'}</strong><small>前年同期 ${valid(oldMargin)?oldMargin.toFixed(1)+'%':'未収録'}</small></div>${s.extra.map(x=>`<div><span>${esc(x.label)}</span><strong>${esc(x.value)}</strong><small>${esc(x.note)}</small></div>`).join('')}</div>
 ${chart(s,'revenue','売上')}${chart(s,'operating','営業利益（GAAP）')}
 <p class="op-note">前年同期との比較で、前四半期比や将来予測ではありません。2時点だけでは成長の加速・減速は断定しません。</p></section></div>
 <section class="story-evidence"><h4>この数字から何が言える？</h4><ul>${s.facts.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p><strong>読み取り：</strong>${esc(s.interpretation)}</p><p class="op-note">${esc(s.caveat)}</p></section>
 <div class="story-columns story-checks"><section><h4>04　ストーリーが崩れる条件</h4><ul>${s.risks.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section><section><h4>05　次に確かめること</h4><p>${esc(s.next)}</p><p class="story-valuation"><strong>今の価格で買える？ — 未判定</strong><br>${esc(s.valuation)}</p></section></div>
 <div class="story-sources"><strong>根拠を読む</strong>${sourceLinks(s)}</div>
 <div class="op-actions"><button type="button" class="op-btn" data-watch="${esc(s.ticker)}" ${registered?'disabled':''}>${registered?'監視に登録済み':'このストーリーを監視に追加'}</button>${registered?`<button type="button" class="op-btn" data-open-review="${esc(s.ticker)}">判断・メモへ</button>`:''}</div>
 <p class="op-note">文章と決算数値は資料を確認して編集したものです。毎日の株価更新では書き換わりません。読み直す際は資料日と出典を確認してください。</p>
 </article></section>`;
}
const api={get,render,summary,growth,margin,freshness,chart};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.OpportunityStories=api;
})(typeof window!=='undefined'?window:this);
