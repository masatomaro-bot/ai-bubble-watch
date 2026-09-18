/* Build user-editable research questions locally. No API calls or saved personal notes. */
(function(root){
'use strict';
const topics={
 overview:['現在の状態','事業の強み、直近の変化、ファンダメンタル（売上・利益・財務・株価評価）とテクニカルをまとめてください。'],
 ceo:['CEO交代で何が変わった？','現在と前任のCEO、就任日を確認し、交代前後の戦略・店舗/製品・人員・投資配分と実績の変化を比較してください。経営者の発言と実行済みの施策を分けてください。'],
 revenue:['売上が落ちた理由は？','そもそも減収しているかを最新決算で確認してください。対象期間を明示し、客数/数量、客単価/価格、為替、店舗数、事業売却・連結範囲の変更に分解してください。既存店売上と連結売上を混同しないでください。'],
 japan:['日本事業を売るとどうなる？','Starbucksの日本事業売却について、報道・交渉・正式発表・完了のどの段階かを日付と出典付きで確認してください。売却が未確定なら仮定として扱ってください。売却代金という現金収入、一時的な売却益、売却後に減る連結売上、残るロイヤルティや持分利益を区別し、「売れば売上が立つのか」に答えてください。金額や条件が未公表なら推測で埋めないでください。'],
 fundamentals:['業績と株価評価','直近の売上・営業利益・利益率・キャッシュフローを前年同期と比較してください。成長の源泉と一時要因を分け、現在株価に対する評価を利益予想の根拠付きで検討してください。'],
 technical:['チャートと売買の条件','最新の株価・出来高・50日/200日移動平均・支持線/抵抗線・直近決算日の位置関係を確認してください。株式分割調整、株価の日時、データ出典を明示し、データがなければ数値を作らないでください。']
};
function promptFor(context,topic,story,market,today){
 const date=today||new Date().toLocaleDateString('sv-SE');
 const common='日本語で、企業のストーリーを理解して投資判断したい個人投資家向けに説明してください。ウェブで最新情報を確認し、決算・企業IRなど一次資料を優先。参照日・対象期間・出典リンクを付け、事実と推定を分けてください。検索できない場合はその旨を明記し、現在の数値を作らないでください。';
 if(context==='market')return `質問作成日：${date}\n米国株の現在の地合いを調べてください。\n${common}\n金利、指数、市場の広がり、業種別の強弱を整理し、成長企業へ投資する追い風・逆風を説明してください。ファンダメンタルとテクニカルを分け、次に確認するイベントと見方を変える条件を示してください。\n画面の参考情報（最新とは限りません）：市場データ日 ${market?.date||'未取得'} / 地合い ${market?.overall_trend_state||'未取得'}。この表示をそのまま事実とせず確認してください。`;
 const question=topics[topic]?.[1]||topics.overview[1];
 const facts=story?`\n画面に収録した過去資料：${story.period} / 発表 ${story.publishedAt} / ${story.sourceLevel}\nストーリーの仮説：${story.title}\n${story.facts.slice(0,2).join('\n')}\n参考出典：${story.sources.map(s=>s.url).join('\n')}\nこの収録内容は最新とは限りません。未照合の値も含みます。最新資料で検証してください。`:'';
 return `質問作成日：${date}\n対象：${story?.name||context} (${context})\n${common}\n\n私が知りたいこと：${question}\n\n回答は「何が変わったか → なぜそうなったか → 今後の売上・利益にどう影響するか → ストーリーの支持材料と反証 → 次に確認する条件」の順。数値は比較表、十分な実データがあれば簡単なチャートを添えてください。${facts}`;
}
function chatLink(text){const url=new URL('https://chatgpt.com/');url.searchParams.set('q',text);return url.href.length<=16000?url.href:'https://chatgpt.com/';}
if(typeof module!=='undefined'&&module.exports)module.exports={topics,promptFor,chatLink};
if(typeof document==='undefined')return;
const panel=document.getElementById('research-panel');if(!panel)return;
const editor=panel.querySelector('textarea'),status=panel.querySelector('[role=status]'),link=panel.querySelector('[data-chat-open]'),drafts=new Map();
let context='market',topic='overview',trigger=null;
const key=()=>context+':'+topic;
function update(){
 const text=editor.value.trim();link.textContent=text?'ChatGPTでこの質問を開く ↗':'質問を入力してください';
 if(!text){link.removeAttribute('href');link.setAttribute('aria-disabled','true');return;}
 link.href=chatLink(text);link.removeAttribute('aria-disabled');
 panel.querySelector('[data-chat-hint]').textContent=link.href==='https://chatgpt.com/'?'質問が長いため、全文をコピーしてChatGPTに貼り付けてください。':'質問が引き継がれない場合は「質問をコピー」を押し、ChatGPTに貼り付けてください。';
}
function show(nextContext,nextTopic,button){
 if(!panel.hidden)drafts.set(key(),editor.value);
 context=nextContext;topic=nextTopic;trigger=button||trigger;
 const story=root.OpportunityStories?.get(context);
 panel.querySelector('h2').textContent=context==='market'?'地合いをChatGPTで深掘り':`${story?.name||context} (${context}) をChatGPTで深掘り`;
 const presets=panel.querySelector('[data-chat-topics]');presets.replaceChildren();
 if(context!=='market')for(const [id,[label]] of Object.entries(topics)){
  if(id==='japan'&&context!=='SBUX')continue;
  const b=document.createElement('button');b.type='button';b.className='op-btn';b.textContent=label;b.setAttribute('aria-pressed',String(id===topic));b.onclick=()=>show(context,id);presets.append(b);
 }
 editor.value=drafts.has(key())?drafts.get(key()):promptFor(context,topic,story,root.watchLatest);
 status.textContent='';panel.hidden=false;update();editor.focus();
}
editor.addEventListener('input',()=>{drafts.set(key(),editor.value);update();});
link.addEventListener('click',ev=>{if(!editor.value.trim()){ev.preventDefault();return;}status.textContent='回答はChatGPT側で確認してください。質問が表示されない場合はコピーして貼り付けてください。';});
panel.querySelector('[data-chat-copy]').onclick=async()=>{
 try{await navigator.clipboard.writeText(editor.value);status.textContent='質問をコピーしました。ChatGPTに貼り付けられます。';}
 catch{editor.focus();editor.select();status.textContent='自動コピーできません。選択された質問をコピーしてください（PCはCtrl+C）。';}
};
panel.querySelector('[data-chat-close]').onclick=()=>{drafts.set(key(),editor.value);panel.hidden=true;trigger?.focus();};
document.addEventListener('click',ev=>{const b=ev.target.closest('[data-chat-context]');if(b)show(b.dataset.chatContext,b.dataset.chatTopic||'overview',b);});
})(typeof window!=='undefined'?window:this);
