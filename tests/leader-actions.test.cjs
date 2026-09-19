const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const P=require('../docs/issuer-profiles.js');
const D=require('../docs/opportunity-discovery.js');
const row=ticker=>({ticker,rs_percentile:98,above_sma50:true,day_change_pct:1,one_month_pct:10,three_month_pct:20});
test('geography gate precedes shortlist; unknown, offshore HK, US-headquartered China production are not admitted',()=>{
 const input={date:'2026-09-17',market_leaders:['MGRT','AXTI','ANL','UNKNOWN','IMMX','EDRY'].map(row)};
 const before=JSON.stringify(input),r=D.select(input,null,'2026-09-19');
 assert.deepEqual(r.candidates.map(x=>x.ticker),['EDRY','IMMX']);
 assert.deepEqual(r.regionExcluded.map(x=>x.ticker),['MGRT','AXTI']);
 assert.deepEqual(r.regionReview.map(x=>x.ticker),['ANL','UNKNOWN']);
 assert.equal(JSON.stringify(input),before);
 assert.equal(P.get('EDRY','2026-09-19').status,'eligible');
 assert.equal(P.get('MU','2026-09-19').status,'eligible');
 assert.equal(P.get('IMMX','2027-09-19').status,'review');
 assert.equal(P.get('IMMX','2026-01-01').status,'review');
});
function boot(personal){
 const w=new JSDOM(fs.readFileSync('docs/index.html','utf8'),{url:'https://local.test/',runScripts:'outside-only'}).window;
 if(personal)w.localStorage.setItem('opportunity-watch-v1',personal);
 w.watchLatest={date:new Date().toISOString().slice(0,10),market_leaders:['MGRT','UNKNOWN','IMMX','EDRY'].map(row),trend_template_leaders:[row('IMMX')],themes:{}};
 for(const f of ['opportunity-rules','issuer-profiles','opportunity-discovery','opportunity','leader-actions'])w.eval(fs.readFileSync(`docs/${f}.js`,'utf8'));
 w.document.getElementById('content').innerHTML='<div data-leader-list="market_leaders"></div><div data-leader-list="trend_template_leaders"></div>';
 w.dispatchEvent(new w.Event('watch-data'));
 return w;
}
test('leaders share watchlist, do not duplicate a ticker, and preserve unsaved notes',()=>{
 const w=boot();try{
 const d=w.document,note=d.querySelector('[data-review=NVDA] [name=note]');note.value='編集中の仮説';note.dispatchEvent(new w.Event('input',{bubbles:true}));
 assert.equal(d.querySelectorAll('[data-leader-watch=MGRT]').length,0);
 assert.equal(d.querySelectorAll('[data-leader-watch=UNKNOWN]').length,0);
 d.querySelector('[data-leader-watch=IMMX]').click();d.querySelectorAll('[data-leader-watch=IMMX]')[1].click();
 const cards=JSON.parse(w.localStorage.getItem('opportunity-watch-v1')).cards;
 assert.equal(cards.filter(c=>c.ticker==='IMMX').length,1);
 assert.equal(d.querySelector('[data-review=NVDA] [name=note]').value,'編集中の仮説');
 assert.match(d.querySelector('.leader-actions').textContent,/Immix Biopharma/);
 assert.equal(d.querySelectorAll('.op-fundamental-candidate').length,2);
 assert(![...d.querySelectorAll('.op-candidate h3')].some(el=>/MGRT|UNKNOWN/.test(el.textContent)));
 }finally{w.close();}
});
test('research links identify the correct company and duplicate-card copy fallback stays local',async()=>{
 const w=boot();try{
 const cards=w.document.querySelectorAll('.leader-company');
 for(const card of cards){const ticker=card.querySelector('h4').textContent.split(' · ')[0],url=new URL(card.querySelector('.op-research-primary').href);assert(url.searchParams.get('q').includes(`米国上場銘柄 ${ticker}`));}
 const copies=w.document.querySelectorAll('.leader-actions [data-company-copy=IMMX]');copies[1].click();await new Promise(r=>setImmediate(r));
 assert.equal(copies[0].closest('[data-research-controls]').querySelector('[role=status]').textContent,'');
 assert.match(copies[1].closest('[data-research-controls]').querySelector('[role=status]').textContent,/コピー/);
 }finally{w.close();}
});
test('corrupt saved data is protected when adding from market leaders',()=>{
 const w=boot('{broken');try{w.document.querySelector('[data-leader-watch=IMMX]').click();assert.equal(w.localStorage.getItem('opportunity-watch-v1'),'{broken');assert.match(w.document.querySelector('[data-leader-watch=IMMX]').closest('article').textContent,/保存を停止/);}finally{w.close();}
});
