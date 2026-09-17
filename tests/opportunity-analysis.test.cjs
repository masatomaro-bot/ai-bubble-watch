const {test}=require('node:test');
const assert=require('node:assert/strict');
const {validateFeed,stale,changedSinceReview}=require('../docs/opportunity-analysis.js');
const {validate,seed}=require('../docs/opportunity.js');
const {prompt}=require('../tools/opportunity-analysis.cjs');
const fixture=require('./fixtures/opportunity-analysis.json');
const sample=()=>structuredClone(fixture);
test('valid report and empty waiting feed',()=>{
  assert.equal(validateFeed(sample()),true);
  assert.equal(validateFeed({version:1,demo:false,reports:[]}),true);
});
test('invalid structures return false without throwing',()=>{
  for(const x of [null,{},[],{version:1,demo:false,reports:[null]}])assert.equal(validateFeed(x),false);
  assert.equal(validate({version:1,cards:[null],log:[]}),false);
});
test('unknown references, unsafe URLs, future sources and invalid dates are rejected',()=>{
  for(const mutate of [r=>r.facts[0].sourceIds=['missing'],r=>r.sources[0].url='javascript:alert(1)',r=>r.sources[0].url='https://user:pass@example.com',r=>r.sources[0].publishedAt='2026-09-18',r=>r.asOf='2026-02-30',r=>r.expectations={status:'比較材料あり',text:'test',sourceIds:[]},r=>r.change={direction:'強まった',summary:'test',previousReportId:null}]){
    const f=sample();mutate(f.reports[0]);assert.equal(validateFeed(f),false);
  }
});
test('duplicate tickers and sources are rejected',()=>{
  const f=sample();f.reports.push(structuredClone(f.reports[0]));assert.equal(validateFeed(f),false);
  const g=sample();g.reports[0].sources.push(g.reports[0].sources[0]);assert.equal(validateFeed(g),false);
});
test('old backups remain valid and review fields survive JSON backup',()=>{
  const old={version:1,cards:[{...seed('NVDA'),story:'以前の仮説'}],log:[]};assert.equal(validate(old),true);
  old.cards[0]={...old.cards[0],judgment:'保留',note:'確認する',reviewedReportId:'r1'};
  assert.equal(validate(JSON.parse(JSON.stringify(old))),true);
  old.cards[0].judgment='買い推奨';assert.equal(validate(old),false);
});
test('freshness uses the information date, and new analysis requires re-review',()=>{
  const r=sample().reports[0];assert.equal(stale(r,'2026-09-24'),false);assert.equal(stale(r,'2026-09-25'),true);
  assert.equal(changedSinceReview({judgment:'納得',reviewedReportId:r.id},r),false);
  assert.equal(changedSinceReview({judgment:'保留',reviewedReportId:'old'},r),true);
  assert.equal(changedSinceReview({},r),false);
});
test('offline prompt contains evidence and explicit uncertainty requirements',()=>{
  const s=sample().reports[0].sources[0];const result=prompt({ticker:'DEMO',sources:[{...s,text:'架空の入力資料'}]},null);
  assert.match(result,/イベント→メカニズム→売上・利益/);assert.match(result,/資料本文.*信頼しない/);assert.match(result,/架空の入力資料/);
  assert.throws(()=>prompt({ticker:'DEMO',sources:[]},null));
});
