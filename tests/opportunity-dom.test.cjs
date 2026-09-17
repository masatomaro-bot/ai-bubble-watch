const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const {seed}=require('../docs/opportunity.js');
const fixture=require('./fixtures/opportunity-analysis.json');
const PERSONAL='opportunity-watch-v1',AI='opportunity-analysis-v1';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function reportFeed(){const x=structuredClone(fixture);x.demo=false;x.reports[0].ticker='NVDA';return x;}
async function boot({personal,feed,fail=false}={}){
  const dom=new JSDOM(fs.readFileSync(path.join(__dirname,'../docs/index.html'),'utf8'),{url:'https://local.test/#opportunity',runScripts:'outside-only'});
  const w=dom.window,d=w.document;
  if(personal!==undefined)w.localStorage.setItem(PERSONAL,typeof personal==='string'?personal:JSON.stringify(personal));
  w.fetch=async()=>{if(fail)throw Error('offline');return {ok:true,json:async()=>feed||{version:1,demo:false,reports:[]}};};
  w.confirm=()=>true;
  for(const file of ['opportunity-analysis.js','opportunity.js'])w.eval(fs.readFileSync(path.join(__dirname,'../docs',file),'utf8'));
  await tick();
  return {dom,w,d,close:()=>dom.window.close()};
}
function fill(ctx,selector,value){const el=ctx.d.querySelector(selector);el.value=value;el.dispatchEvent(new ctx.w.Event('input',{bubbles:true}));}
function submit(ctx,selector){ctx.d.querySelector(selector).dispatchEvent(new ctx.w.Event('submit',{cancelable:true}));}
async function upload(ctx,id,value){const input=ctx.d.getElementById(id);const body=JSON.stringify(value);Object.defineProperty(input,'files',{value:[{size:body.length,text:async()=>body}],configurable:true});await input.onchange({target:input});}
test('empty feed does not invent analysis; legacy notes survive a new optional note',async()=>{
  const old={version:1,cards:[{...seed('NVDA'),story:'以前の仮説'}],log:[]};const c=await boot({personal:old});
  try{
    assert.match(c.d.querySelector('.op-analysis-empty').textContent,/AI分析待ち/);
    assert.equal(c.d.querySelector('[name=story]').value,'以前の仮説');
    fill(c,'[data-review=NVDA] [name=note]','新しいメモ');submit(c,'[data-review=NVDA]');
    const saved=JSON.parse(c.w.localStorage.getItem(PERSONAL)).cards[0];assert.equal(saved.story,'以前の仮説');assert.equal(saved.note,'新しいメモ');
  }finally{c.close();}
});
test('AI report, citations, and judgment render without required personal thesis',async()=>{
  const c=await boot({feed:reportFeed()});try{
    assert.match(c.d.querySelector('.op-analysis').textContent,/変化が効く仕組み/);
    assert.equal(c.d.querySelector('.op-analysis a').href,'https://example.com/earnings');
    fill(c,'[data-review=NVDA] [name=judgment]','納得');submit(c,'[data-review=NVDA]');
    const saved=JSON.parse(c.w.localStorage.getItem(PERSONAL)).cards[0];assert.equal(saved.judgment,'納得');assert.equal(saved.reviewedReportId,fixture.reports[0].id);assert.equal(saved.story,'');
  }finally{c.close();}
});
test('analysis import preserves personal storage and marks changed reports for review',async()=>{
  const f=reportFeed(),personal={version:1,cards:[{...seed('NVDA'),judgment:'納得',note:'消さない',reviewedReportId:f.reports[0].id}],log:[]};
  const c=await boot({personal,feed:f});try{
    const before=c.w.localStorage.getItem(PERSONAL);f.reports[0].id='second-analysis';
    await upload(c,'op-ai-import',f);assert.equal(c.w.localStorage.getItem(PERSONAL),before);
    assert.match(c.d.querySelector('.op-analysis').textContent,/再確認が必要/);assert.equal(c.d.querySelector('[name=note]').value,'消さない');
  }finally{c.close();}
});
test('malformed/demo reports and canceled imports cannot replace valid data',async()=>{
  const c=await boot();try{
    await upload(c,'op-ai-import',reportFeed());const before=c.w.localStorage.getItem(AI);
    const bad=reportFeed();bad.reports[0].sources[0].url='javascript:alert(1)';await upload(c,'op-ai-import',bad);assert.equal(c.w.localStorage.getItem(AI),before);
    await upload(c,'op-ai-import',fixture);assert.equal(c.w.localStorage.getItem(AI),before);
    c.w.confirm=()=>false;const newer=reportFeed();newer.reports[0].id='canceled';await upload(c,'op-ai-import',newer);assert.equal(c.w.localStorage.getItem(AI),before);
  }finally{c.close();}
});
test('HTML in AI text and personal notes is displayed as text',async()=>{
  const f=reportFeed();f.reports[0].headline='<img src=x onerror=alert(1)>';const c=await boot({feed:f});try{
    assert.equal(c.d.querySelectorAll('.op-card img').length,0);assert.match(c.d.querySelector('.op-analysis h4').textContent,/<img/);
    fill(c,'[data-review=NVDA] [name=note]','</textarea><script>alert(1)</script>');submit(c,'[data-review=NVDA]');
    assert.equal(c.d.querySelectorAll('#opportunity script').length,0);
  }finally{c.close();}
});
test('background data and saving another card do not erase a draft or change its report identity',async()=>{
  const c=await boot({feed:reportFeed()});try{
    fill(c,'[data-review=NVDA] [name=note]','編集中');
    c.w.watchLatest={date:'2026-09-17',overall_trend_state:'correction',themes:{}};c.w.dispatchEvent(new c.w.Event('watch-data'));
    assert.equal(c.d.querySelector('[data-review=NVDA] [name=note]').value,'編集中');
    fill(c,'[data-review=GOOGL] [name=note]','別の保存');submit(c,'[data-review=GOOGL]');
    assert.equal(c.d.querySelector('[data-review=NVDA] [name=note]').value,'編集中');
    const f=reportFeed();f.reports[0].id='newer';await upload(c,'op-ai-import',f);
    fill(c,'[data-review=NVDA] [name=judgment]','納得');submit(c,'[data-review=NVDA]');
    assert.match(c.d.querySelector('.op-analysis').textContent,/再確認が必要/);
  }finally{c.close();}
});
test('backup download contains personal fields, and restore preserves independent AI data',async()=>{
  const c=await boot({feed:reportFeed()});try{
    fill(c,'[data-review=NVDA] [name=judgment]','保留');fill(c,'[data-review=NVDA] [name=note]','バックアップ対象');submit(c,'[data-review=NVDA]');
    let blob;c.w.URL.createObjectURL=b=>{blob=b;return 'blob:test';};c.w.URL.revokeObjectURL=()=>{};c.w.HTMLAnchorElement.prototype.click=function(){};
    c.d.getElementById('op-export').click();const reader=new c.w.FileReader();const content=new Promise(resolve=>reader.onload=()=>resolve(reader.result));reader.readAsText(blob);const backup=JSON.parse(await content);
    assert.equal(backup.cards[0].note,'バックアップ対象');assert.equal(backup.cards[0].judgment,'保留');assert.equal(backup.reports,undefined);
    await upload(c,'op-ai-import',reportFeed());const aiBefore=c.w.localStorage.getItem(AI);
    fill(c,'[data-review=NVDA] [name=note]','変更後');submit(c,'[data-review=NVDA]');
    await upload(c,'op-import',backup);assert.equal(c.d.querySelector('[data-review=NVDA] [name=note]').value,'バックアップ対象');assert.equal(c.w.localStorage.getItem(AI),aiBefore);
    c.w.confirm=()=>false;await upload(c,'op-import',{version:1,cards:[],log:[]});assert.equal(c.d.querySelectorAll('.op-card').length,3);
  }finally{c.close();}
});
test('invalid personal storage is not overwritten, and offline feed is explicit',async()=>{
  const c=await boot({personal:'{broken',fail:true});try{
    assert.match(c.d.querySelector('.op-hero').textContent,/取得できません/);
    fill(c,'[data-review=NVDA] [name=note]','上書きしない');submit(c,'[data-review=NVDA]');assert.equal(c.w.localStorage.getItem(PERSONAL),'{broken');
  }finally{c.close();}
});
