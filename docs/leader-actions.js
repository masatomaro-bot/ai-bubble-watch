(function(root){
'use strict';
const P=root.IssuerProfiles,D=root.OpportunityDiscovery;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function render(rows,date){
 const groups={eligible:[],review:[],excluded:[]};
 for(const row of rows||[]){if(!/^[A-Z0-9.^-]{1,12}$/.test(row.ticker))continue;const p=P.get(row.ticker);groups[p.status].push({row,p});}
 const card=({row,p},actionable)=>`<article class="leader-company"><h4>${esc(row.ticker)} · ${esc(p.name)}</h4><p>${esc(p.business)}</p>
 <details><summary>事業基盤・確認資料</summary><p>${esc(p.base)}：${esc(p.reason)}</p><p>確認日 ${esc(p.checked||'未確認')} · 公開資料による暫定情報</p>${p.sources.map((url,i)=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">企業資料 ${i+1} ↗</a>`).join(' ／ ')}</details>
 ${D.researchControls(row.ticker,{date})}
 ${actionable?`<button type="button" data-leader-watch="${esc(row.ticker)}">${root.OpportunityWatch?.has(row.ticker)?'監視に登録済み':'監視に追加'}</button>`:'<p>候補への採用は保留しています。まず企業情報を確認してください。</p>'}
 <p class="leader-status" role="status"></p>
 <details><summary>抽出時の数値</summary><p>データ日 ${esc(date||'未取得')} · 自動取得・未検証</p><p>RS百分位 ${esc(row.rs_percentile??'未取得')} ／ 前日比 ${esc(row.day_change_pct??'未取得')}% ／ 1か月 ${esc(row.one_month_pct??'未取得')}% ／ 3か月 ${esc(row.three_month_pct??'未取得')}%</p></details></article>`;
 return `<section class="leader-actions"><p>一覧で見つけた企業の事業・決算・堀を調べ、追いたい企業を機会ウォッチに残せます。価格の強さだけでは、業績や競争優位は分かりません。</p><p class="sub">地域確認通過 ${groups.eligible.length}件 ／ 確認待ち ${groups.review.length}件 ／ 対象外 ${groups.excluded.length}件。市場全体の地合い集計は絞り込んでいません。</p>
 ${groups.eligible.map(x=>card(x,true)).join('')||'<p>地域確認を通過した企業はありません。</p>'}
 ${['review','excluded'].map(k=>groups[k].length?`<details class="leader-held"><summary>${k==='review'?'企業情報の確認待ち':'方針による対象外'} ${groups[k].length}件</summary>${groups[k].map(x=>card(x,false)).join('')}</details>`:'').join('')}
 <details><summary>地域の確認方針と更新について</summary><p>中国本土・香港に事業・経営の中核がある企業は対象外。登記地や米国上場だけでは判断しません。中国への販売や一部拠点の存在だけとは区別します。不明な企業は確認待ちです。通過は中国リスクがないという保証ではありません。</p><p>株価リストは既存の日次更新を利用します。社名・事業説明・地域は出典を照合して登録した情報です。未登録企業は自動で推測せず、確認日から180日を超えた情報は再確認待ちにします。決算分析の自動更新は未実装です。</p></details><a href="#opportunity">機会ウォッチで監視企業を見る →</a></section>`;
}
function mount(){document.querySelectorAll('[data-leader-list]').forEach(el=>{if(!el.dataset.mounted){el.innerHTML=render(root.watchLatest?.[el.dataset.leaderList],root.watchLatest?.date);el.dataset.mounted='true';}});}
root.LeaderActions={render};
root.addEventListener('watch-data',()=>{document.querySelectorAll('[data-leader-list]').forEach(el=>delete el.dataset.mounted);mount();});
// The market view is rendered after the first watch-data event.
new MutationObserver(mount).observe(document.getElementById('content'),{childList:true});
mount();
document.addEventListener('click',async ev=>{
 const b=ev.target.closest('button');if(!b||!b.closest('.leader-actions'))return;
 if(b.dataset.leaderWatch){const result=root.OpportunityWatch?.add(b.dataset.leaderWatch)||{ok:false,message:'監視機能を読み込めません。再読み込みしてください。'};b.closest('.leader-company').querySelector('.leader-status').textContent=result.message;sync();}
 if(b.dataset.companyCopy){const scope=b.closest('[data-research-controls]'),area=scope.querySelector('textarea'),status=scope.querySelector('[role=status]');try{await navigator.clipboard.writeText(area.value);status.textContent='コピーしました。ChatGPTに貼り付けて送信してください。';}catch{area.focus();area.select();status.textContent='選択された質問を⌘C（WindowsはCtrl+C）でコピーしてください。';}}
});
function sync(){document.querySelectorAll('[data-leader-watch]').forEach(b=>b.textContent=root.OpportunityWatch?.has(b.dataset.leaderWatch)?'監視に登録済み':'監視に追加');}
root.addEventListener('watchlist-changed',sync);
})(window);
