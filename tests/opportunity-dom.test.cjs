const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const {seed}=require('../docs/opportunity.js');
const PERSONAL='opportunity-watch-v1';
const tickerRow=(ticker,extra={})=>({ticker,rs_percentile:98,day_change_pct:4,one_month_pct:12,three_month_pct:20,above_sma50:true,...extra});
const snapshot=()=>({date:new Date().toISOString().slice(0,10),overall_trend_state:'correction',market_leaders:[tickerRow('DEMO')],trend_template_leaders:[],themes:{}});
function boot({personal,latest=snapshot(),stories=false}={}){
 const dom=new JSDOM(fs.readFileSync(path.join(__dirname,'../docs/index.html'),'utf8'),{url:'https://local.test/#opportunity',runScripts:'outside-only'});
 const w=dom.window,d=w.document;let calls=0;
 if(personal!==undefined)w.localStorage.setItem(PERSONAL,typeof personal==='string'?personal:JSON.stringify(personal));
 w.fetch=()=>{calls++;throw Error('Network is forbidden in the opportunity module');};w.confirm=()=>true;w.watchLatest=latest;
 for(const file of ['opportunity-rules.js',...(stories?['opportunity-stories-data.js','opportunity-stories.js']:[]),'opportunity.js'])w.eval(fs.readFileSync(path.join(__dirname,'../docs',file),'utf8'));
 return {dom,w,d,calls:()=>calls,close:()=>w.close()};
}
function fill(c,selector,value){const el=c.d.querySelector(selector);el.value=value;el.dispatchEvent(new c.w.Event('input',{bubbles:true}));}
function submit(c,selector){c.d.querySelector(selector).dispatchEvent(new c.w.Event('submit',{cancelable:true}));}
async function upload(c,value){const input=c.d.getElementById('op-import');const body=JSON.stringify(value);Object.defineProperty(input,'files',{value:[{size:body.length,text:async()=>body}],configurable:true});await input.onchange({target:input});}
test('discovery is useful with zero personal input and no network/AI/import workflow',()=>{
 const c=boot();try{assert.equal(c.d.querySelectorAll('.op-candidate').length,1);assert.match(c.d.querySelector('.op-candidate').textContent,/DEMO/);assert.equal(c.d.getElementById('op-ai-import'),null);assert.doesNotMatch(c.d.querySelector('#opportunity').textContent,/AI分析待ち/);assert.equal(c.calls(),0);assert.equal(c.w.localStorage.getItem(PERSONAL),null);}finally{c.close();}
});
test('unknown saved ticker is explicitly outside data coverage; old notes are intact',()=>{
 const c=boot({personal:{version:1,cards:[{...seed('NVDA'),story:'以前の仮説',note:'保存済み'}],log:[]}});try{assert.equal(c.d.querySelector('[name=story]').value,'以前の仮説');assert.match(c.d.querySelector('.op-analysis-empty').textContent,/データなし/);fill(c,'[data-review=NVDA] [name=note]','追記');submit(c,'[data-review=NVDA]');assert.equal(JSON.parse(c.w.localStorage.getItem(PERSONAL)).cards[0].story,'以前の仮説');}finally{c.close();}
});
test('watch button adds a discovered stock once; judgment is tied to snapshot',()=>{
 const c=boot();try{c.d.querySelector('[data-watch=DEMO]').click();assert.equal(c.d.querySelector('[data-watch=DEMO]').disabled,true);fill(c,'[data-review=DEMO] [name=judgment]','保留');submit(c,'[data-review=DEMO]');const cards=JSON.parse(c.w.localStorage.getItem(PERSONAL)).cards;assert.equal(cards.filter(x=>x.ticker==='DEMO').length,1);assert.match(cards.find(x=>x.ticker==='DEMO').reviewedReportId,/^rules-v1:/);}finally{c.close();}
});
test('missing data stays empty then updates automatically when the existing pipeline emits data',()=>{
 const c=boot({latest:null});try{assert.equal(c.d.querySelectorAll('.op-candidate').length,0);c.w.watchLatest=snapshot();c.w.dispatchEvent(new c.w.Event('watch-data'));assert.equal(c.d.querySelectorAll('.op-candidate').length,1);assert.equal(c.calls(),0);}finally{c.close();}
});
test('draft survives background updates, adding candidate, and saving a different card',()=>{
 const c=boot();try{fill(c,'[data-review=NVDA] [name=note]','編集中');c.w.watchLatest=snapshot();c.w.dispatchEvent(new c.w.Event('watch-data'));c.d.querySelector('[data-watch=DEMO]').click();fill(c,'[data-review=GOOGL] [name=note]','別の保存');submit(c,'[data-review=GOOGL]');assert.equal(c.d.querySelector('[data-review=NVDA] [name=note]').value,'編集中');}finally{c.close();}
});
test('backup download/restore and canceled restore preserve notes without any AI data',async()=>{
 const c=boot();try{fill(c,'[data-review=NVDA] [name=note]','バックアップ対象');submit(c,'[data-review=NVDA]');let blob;c.w.URL.createObjectURL=b=>{blob=b;return 'blob:test';};c.w.URL.revokeObjectURL=()=>{};c.w.HTMLAnchorElement.prototype.click=function(){};c.d.getElementById('op-export').click();const reader=new c.w.FileReader();const content=new Promise(resolve=>reader.onload=()=>resolve(reader.result));reader.readAsText(blob);const backup=JSON.parse(await content);assert.equal(backup.cards[0].note,'バックアップ対象');fill(c,'[data-review=NVDA] [name=note]','変更');submit(c,'[data-review=NVDA]');await upload(c,backup);assert.equal(c.d.querySelector('[data-review=NVDA] [name=note]').value,'バックアップ対象');c.w.confirm=()=>false;await upload(c,{version:1,cards:[],log:[]});assert.equal(c.d.querySelectorAll('[data-review]').length,3);}finally{c.close();}
});
test('corrupt storage is not overwritten and HTML notes are inert',()=>{
 const c=boot({personal:'{broken'});try{fill(c,'[data-review=NVDA] [name=note]','変更');submit(c,'[data-review=NVDA]');assert.equal(c.w.localStorage.getItem(PERSONAL),'{broken');}finally{c.close();}
 const d=boot();try{fill(d,'[data-review=NVDA] [name=note]','</textarea><img src=x onerror=alert(1)>');submit(d,'[data-review=NVDA]');assert.equal(d.d.querySelectorAll('#opportunity img').length,0);}finally{d.close();}
});
test('optional research copy fails gracefully when clipboard is unavailable',async()=>{
 const c=boot();try{await c.d.querySelector('[data-copy=DEMO]').onclick();assert.match(c.d.getElementById('op-status').textContent,/選択してコピー/);assert.match(c.d.querySelector('.op-brief').value,/DEMO/);}finally{c.close();}
});
test('story catalogue leads without market data; all companies have readable evidence and charts',()=>{
 const c=boot({stories:true,latest:null});try{
  assert.equal(c.d.querySelectorAll('.story-choice').length,5);
  assert.equal(c.d.querySelector('.story-detail').getAttribute('aria-label'),'SBUXの企業分析');
  assert.equal(c.d.querySelector('.op-market-extra').open,false);
  assert.equal(c.calls(),0);
  for(const ticker of ['GOOGL','AAPL','NVDA','AVGO','SBUX']){
   c.d.querySelector(`.story-choice[data-story=${ticker}]`).click();
   const story=c.d.querySelector('.story-detail');
   assert.match(story.textContent,/未判定/);assert.equal(story.querySelectorAll('figure').length,2);
   assert(story.querySelector('.story-sources a').href.startsWith('https://'));
   assert.doesNotMatch(story.innerHTML,/NaN|Infinity|undefined/);
  }
  assert.match(c.d.querySelector('.story-detail').textContent,/公式資料の照合待ち/);
  assert.equal(c.d.querySelectorAll('.story-detail .story-bar').length,1);
 }finally{c.close();}
});
test('story review works outside market coverage and stays linked to reviewed story through reload',()=>{
 const c=boot({stories:true,latest:null});try{
  fill(c,'[data-review=NVDA] [name=judgment]','納得');fill(c,'[data-review=NVDA] [name=note]','採算を追う');submit(c,'[data-review=NVDA]');
  const saved=JSON.parse(c.w.localStorage.getItem(PERSONAL));assert.equal(saved.cards[0].reviewedReportId,'story:NVDA:2027-Q2:20260918');
  const second=boot({stories:true,personal:saved,latest:null});try{assert.equal(second.d.querySelector('[data-review=NVDA] [name=note]').value,'採算を追う');assert.equal(second.d.querySelector('[data-review=NVDA] [name=judgment]').value,'納得');}finally{second.close();}
 }finally{c.close();}
});
test('switching companies preserves drafts; watch additions and review navigation respect existing lane',()=>{
 const c=boot({stories:true,personal:{version:1,cards:[{...seed('NVDA'),lane:'technical',story:'旧メモ'}],log:[]}});try{
  c.d.querySelector('[data-watch=SBUX]').click();
  fill(c,'[data-review=SBUX] [name=note]','途中のメモ');
  c.d.querySelector('.story-choice[data-story=NVDA]').click();
  assert.equal(c.d.querySelector('[data-review=SBUX] [name=note]').value,'途中のメモ');
  c.d.querySelector('[data-open-review=NVDA]').click();
  assert.equal(c.d.activeElement,c.d.querySelector('[data-review=NVDA] select'));
  assert.equal(c.d.querySelector('[name=story]').value,'旧メモ');
  c.d.querySelector('[data-lane=story]').click();assert.equal(c.d.querySelector('[data-review=SBUX] [name=note]').value,'途中のメモ');
 }finally{c.close();}
});
test('old rule judgment is retained with a visible review warning, and backup restore retains story judgment',async()=>{
 const original={version:1,cards:[{...seed('GOOGL'),judgment:'保留',note:'前の判断',reviewedReportId:'rules-v1:2026-09-17:GOOGL'}],log:[]};
 const c=boot({stories:true,personal:original});try{
  assert.match(c.d.querySelector('#review-GOOGL .op-alert').textContent,/別の資料/);
  assert.equal(c.d.querySelector('[name=judgment]').value,'保留');
  submit(c,'[data-review=GOOGL]');const backup=JSON.parse(c.w.localStorage.getItem(PERSONAL));
  assert.match(backup.cards[0].reviewedReportId,/^story:/);
  fill(c,'[data-review=GOOGL] [name=note]','変更');submit(c,'[data-review=GOOGL]');
  await upload(c,backup);assert.equal(c.d.querySelector('[name=note]').value,'前の判断');
  assert.equal(c.d.querySelector('[name=judgment]').value,'保留');
 }finally{c.close();}
});
test('growth math preserves missing/negative bases; charts do not turn missing figures into zero',()=>{
 const s=require('../docs/opportunity-stories.js');
 assert.equal(s.growth(100,120),19.999999999999996);assert.equal(s.growth(null,120),null);
 assert.equal(s.growth(-10,10),null);assert.equal(s.growth(0,10),null);assert.equal(s.margin(100,-10),-10);
 assert.equal(s.growth('100',120),null);
 const html=s.chart({revenue:[-10,20],period:'now',previousPeriod:'before'},'revenue','売上');
 assert.match(html,/is-signed/);assert.doesNotMatch(html,/width:-/);
 assert.match(s.freshness({publishedAt:'2020-01-01'}),/120日/);
 assert.match(s.freshness({publishedAt:'2099-01-01'}),/資料日/);
});
