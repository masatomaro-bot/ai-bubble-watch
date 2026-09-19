const {test}=require('node:test');
const assert=require('node:assert/strict');
const {select,render}=require('../docs/opportunity-discovery.js');
const row=(ticker,extra={})=>({ticker,rs_percentile:95,day_change_pct:0,one_month_pct:10,three_month_pct:20,above_sma50:true,...extra});
const snap=(date,rows)=>({date,market_leaders:rows,trend_template_leaders:[]});
const run=(s,p)=>select(s,p,'2026-09-19');
const broad=(date,rows,method='broad-close-return-252-percentile-v1')=>({date,opportunity_universe:{method,source:'broad',rows:rows.map(r=>({...r,observed_date:date}))}});
test('steady strength can qualify without a one-day jump; falls and rebounds do not',()=>{
 const r=run(snap('2026-09-17',[row('STEADY'),row('FALL',{day_change_pct:-4}),row('BOUNCE',{day_change_pct:8,one_month_pct:-5}),row('WEAK',{above_sma50:false})]));
 assert.deepEqual(r.all.map(x=>x.ticker),['STEADY']);assert.equal(r.cautions.length,2);
});
test('repeat qualification gets priority; never infer continuous daily strength',()=>{
 const r=run(snap('2026-09-17',[row('NEW',{rs_percentile:99}),row('REPEAT')]),snap('2026-09-16',[row('REPEAT')]));
 assert.equal(r.candidates[0].ticker,'REPEAT');assert.equal(r.candidates[1].persistent,false);assert.match(r.candidates[0].reasons.join(''),/全日を確認した意味ではありません/);
});
test('missing values, conflicts and stale observation dates never qualify',()=>{
 assert.equal(run(snap('2026-09-17',[row('NULL',{three_month_pct:null}),row('STRING',{rs_percentile:'95'})])).all.length,0);
 const conflict=snap('2026-09-17',[row('BAD')]);conflict.trend_template_leaders=[row('BAD',{day_change_pct:5})];assert.deepEqual(run(conflict).excluded,['BAD']);
 const b=broad('2026-09-17',[row('OLD')]);b.opportunity_universe.rows[0].observed_date='2026-09-16';assert.deepEqual(run(b).excluded,['OLD']);
});
test('future, invalid and stale snapshots have no actionable candidate list',()=>{
 for(const date of ['2026-02-30','2026-09-20','2026-09-01'])assert.equal(run(snap(date,[row('AAA')])).candidates.length,0);
});
test('new universe is authoritative, empty means empty; format and source transitions stop comparison',()=>{
 const b=broad('2026-09-17',[]);b.market_leaders=[row('LEGACY')];assert.equal(run(b).all.length,0);
 const c=broad('2026-09-17',[row('AAA')]);assert.equal(run(c,snap('2026-09-16',[row('AAA')])).comparable,false);
 assert.equal(run(broad('2026-09-17',[row('AAA')],'unknown')).all.length,0);
 const p=broad('2026-09-16',[row('AAA')]);p.opportunity_universe.source='other';assert.equal(run(c,p).comparable,false);
 assert.equal(run(c,broad('2026-09-16',[row('AAA')])).candidates[0].persistent,true);
});
test('deterministic shortlist is capped; no fallback to fixed stories',()=>{
 const r=run(snap('2026-09-17',['DDD','BBB','CCC','AAA'].map(t=>row(t))));assert.deepEqual(r.candidates.map(x=>x.ticker),['AAA','BBB','CCC']);
 assert.match(render(run(null),{get:()=>({ticker:'SBUX'})},[]),/固定の企業紹介で候補を補充しません/);
 assert.match(render(r,null,[]),/業績・堀・株価への織り込みは未検証/);
});

test('research URL round-trips ticker, dated public figures and fundamental instructions',()=>{
 const {researchPrompt,researchUrl}=require('../docs/opportunity-discovery.js');
 const result=run(snap('2026-09-17',[row('MGRT')]));
 const prompt=researchPrompt('MGRT',result),url=new URL(researchUrl('MGRT',result));
 assert.equal(url.origin,'https://chatgpt.com');assert.equal(url.searchParams.get('q'),prompt);
 for(const text of ['MGRT','2026-09-17','正式社名','SEC','前年同期','模倣','最有力シナリオ','未確認','テクニカル説明は不要'])assert(prompt.includes(text));
 assert.throws(()=>researchPrompt('<img>'),/Invalid ticker/);
 assert(researchUrl('MGRT',result).length<10000);
});
