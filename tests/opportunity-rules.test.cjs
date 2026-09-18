const {test}=require('node:test');
const assert=require('node:assert/strict');
const {derive,briefing}=require('../docs/opportunity-rules.js');
const row=(ticker,extra={})=>({ticker,rs_percentile:95,day_change_pct:0,one_month_pct:10,three_month_pct:20,above_sma50:true,...extra});
const snap=(date,rows,other=[])=>({date,market_leaders:rows,trend_template_leaders:other});
const run=(latest,prev)=>derive(latest,prev,'2026-09-18');
test('missing, invalid and future dates do not invent candidates',()=>{
  for(const s of [null,{},snap('2026-02-30',[row('AAA')]),snap('2026-09-19',[row('AAA',{day_change_pct:9})])])assert.equal(run(s,null).candidates.length,0);
});
test('same state is not a recovery; a genuine crossing is explained',()=>{
  const cur=snap('2026-09-17',[row('AAA')]);
  assert.equal(run(cur,snap('2026-09-16',[row('AAA')])).all.length,0);
  const x=run(cur,snap('2026-09-16',[row('AAA',{above_sma50:false})]));assert.match(x.candidates[0].signals[0].text,/下から上/);
});
test('missing and string values cannot become numbers or crossings',()=>{
  const x=run(snap('2026-09-17',[row('AAA',{day_change_pct:null,rs_percentile:null,above_sma50:null})]),snap('2026-09-16',[row('AAA')]));assert.equal(x.all.length,0);
  const y=run(snap('2026-09-17',[row('BAD',{day_change_pct:'5'})]),null);assert.deepEqual(y.excluded,['BAD']);
});
test('new listing is identified only with usable prior table, not a first-ever pass',()=>{
  const s=snap('2026-09-17',[row('AAA')],[row('AAA')]);
  assert.equal(run(s,null).all.length,0);
  assert.equal(run(s,snap('2026-09-16',[],[])).all.length,0);
  const r=run(s,snap('2026-09-16',[row('BBB')],[row('BBB')]));assert.match(r.candidates[0].signals[0].text,/合格した初日とは限りません/);
});
test('same-date, reversed and long-gap histories cannot produce change signals',()=>{
  for(const date of ['2026-09-17','2026-09-18','2026-09-01'])assert.equal(run(snap('2026-09-17',[row('AAA')]),snap(date,[row('AAA',{above_sma50:false})])).all.length,0);
});
test('extreme returns and conflicting duplicate rows are withheld, including prior bad data',()=>{
  const x=run(snap('2026-09-17',[row('BAD',{one_month_pct:300}),row('CON')],[row('CON',{day_change_pct:5})]),null);assert.deepEqual(x.excluded,['BAD','CON']);
  const s=snap('2026-09-17',[row('AAA')]);const p=snap('2026-09-16',[row('AAA',{one_month_pct:300})]);assert.equal(run(s,p).all.length,0);
});
test('daily advance needs both trend and RS evidence; downside is explicitly caution',()=>{
  const x=run(snap('2026-09-17',[row('UP',{day_change_pct:3}),row('LOW',{day_change_pct:4,rs_percentile:80}),row('DOWN',{day_change_pct:-3}),row('UNK',{day_change_pct:4,above_sma50:null})]),null);
  assert.deepEqual(x.all.map(r=>r.ticker),['DOWN','UP']);assert.equal(x.all[0].caution,true);
});
test('candidate list is capped at three, deduplicated, and deterministic',()=>{
  const data=['DDD','CCC','BBB','AAA'].map(t=>row(t,{day_change_pct:4}));const x=run(snap('2026-09-17',data,[data[0]]),null);
  assert.equal(x.coverage,4);assert.equal(x.all.length,4);assert.deepEqual(x.candidates.map(r=>r.ticker),['AAA','BBB','CCC']);
});
test('staleness and unknown watchlist names are explicit',()=>{
  const x=run(snap('2026-09-01',[row('AAA',{day_change_pct:4})]),null);assert.equal(x.stale,true);assert.equal(x.byTicker.NVDA,undefined);
});
test('briefing contains dates and evidence but no invented volume or profit claims',()=>{
  const x=run(snap('2026-09-17',[row('AAA',{day_change_pct:4,one_month_pct:-10})]),null);const t=briefing(x.candidates[0],x.date,x.previousDate);
  assert.match(t,/2026-09-17/);assert.match(t,/比較日：なし/);assert.match(t,/短期反発/);assert.match(t,/出来高増加.*判定していません/);assert.match(t,/AI分析ではありません/);
});
