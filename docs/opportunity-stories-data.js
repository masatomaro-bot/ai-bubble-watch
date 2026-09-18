/* Reviewed snapshots. Values in USD millions unless the metric states otherwise.
 * Update sources and report IDs together; never replace missing figures with zero. */
(function(root){
'use strict';
const stories=[
  {
    ticker:'SBUX',name:'Starbucks',sector:'外食・居場所',kind:'回復を確かめる',
    id:'story:SBUX:2026-Q3:20260918',reviewedAt:'2026-09-18',publishedAt:'2026-07-29',period:'FY2026 Q3',previousPeriod:'FY2025 Q3',sourceLevel:'報道で確認・公式資料の照合待ち',
    title:'また通いたくなる店は、利益も取り戻せるか。',
    value:'コーヒーを買うだけでなく、ひと息つける居場所として選ばれる。その体験にお金を払ってもらう、という見方です。',
    business:'飲み物・食事を直営店で販売し、ライセンス店からも収益を得る。店舗の体験と、待たずに受け取れる便利さの両立を見ます。',
    chain:['店内の居心地・提供の速さを改善','また来る人と来店頻度が増える','既存店売上が伸び、店舗コストを吸収する'],
    thesis:'客数の回復が続き、人員や店舗への投資を上回る売上増が出れば、利益回復につながるという仮説です。長居できるだけで利益が増えるとは限りません。',
    facts:['世界・米国の既存店売上は前年同期比 +7.9%と報道。新店だけに頼らない回復を見る材料。','連結売上は約93.2億ドル、前年比 -1.4%と報道。中国事業の合弁化による連結範囲の変化を含みます。'],
    revenue:[null,9320],operating:[null,null],reportedRevenueGrowth:-1.4,
    extra:[{label:'世界の既存店売上',value:'+7.9%',note:'前年同期比・報道値'},{label:'調整後EPS',value:'$0.85',note:'Non-GAAP・報道値'}],
    interpretation:'既存店は伸びても、連結売上は減少。店舗の実力と事業売却の影響を分けて見る段階です。',
    risks:['値上げだけで売上が増え、来店回数が伸びない。','人件費・改装費がかさみ、客数回復が利益に結びつかない。'],
    next:'次の決算で客数・客単価の内訳と、一時的な利益を除いた店舗採算を確認する。',
    valuation:'現在株価・予想利益を照合していないため、回復期待が割高かどうかは未判定。',
    caveat:'公式決算表は未照合。前年同期の売上額・GAAP営業利益は未収録のため、推計して棒を描きません。',
    sources:[{label:'Reuters：2026-07-29 決算報道',url:'https://www.reuters.com/business/retail-consumer/starbucks-beats-quarterly-sales-estimates-2026-07-29/'},{label:'Barron’s：Q3決算・中国事業の影響',url:'https://www.barrons.com/articles/starbucks-earnings-stock-price-d139e699'}]
  },
  {
    ticker:'GOOGL',name:'Alphabet / Google',sector:'情報・広告・クラウド',kind:'成長の広がりを見る',
    id:'story:GOOGL:2026-Q2:20260918',reviewedAt:'2026-09-18',publishedAt:'2026-07-22',period:'2026 Q2',previousPeriod:'2025 Q2',sourceLevel:'公式決算資料',
    title:'情報への入口を、次の収益につなげられるか。',
    value:'知りたいことを探し、動画を見て、仕事にも使う。その日常の接点が広告主や企業にとって価値になる、という見方です。',
    business:'検索・YouTubeなどの広告、利用者向けサービス、企業向けクラウドで収益を得る。利用の多さを収益へ変える力が要点です。',
    chain:['検索・動画・業務で役立つ場面が増える','広告の接点と有料サービスの利用が広がる','広告・クラウドの売上と営業利益が増える'],
    thesis:'情報の探し方が変わっても利用者との接点を維持できれば、既存広告と企業向けサービスの両方で伸びるという仮説です。',
    facts:['検索等の売上は632.71億ドル、前年同期の541.90億ドルから増加。','Cloud売上は247.68億ドル、前年同期の136.24億ドルから増加。'],
    revenue:[96428,119796],operating:[31271,40770],
    extra:[{label:'検索等の売上成長',value:'+17%',note:'会社発表・前年同期比'},{label:'Cloud売上成長',value:'+82%',note:'会社発表・前年同期比'}],
    interpretation:'主力の検索とCloudがともに成長。純利益には大きな投資評価益があるため、下の図では営業利益で本業を比較します。',
    risks:['AIで情報取得が完結し、広告の収益性が下がる。','設備投資・減価償却の負担が増え、売上成長ほど現金が残らない。'],
    next:'検索の収益性とCloudの採算に加え、設備投資後に残る現金を次の決算で確認する。',
    valuation:'予想利益・現在株価の照合前。純利益の急増をそのまま持続的な成長とみなしてPERを判断しない。',
    caveat:'単一四半期の前年同期比較です。成長の加速・持続を判断するには追加の四半期が必要です。',
    sources:[{label:'Alphabet：2026 Q2 決算（SEC提出）',url:'https://www.sec.gov/Archives/edgar/data/1652044/000165204426000066/googexhibit991q22026.htm'}]
  },
  {
    ticker:'AAPL',name:'Apple',sector:'生活・デバイス',kind:'体験が継続収益になるか',
    id:'story:AAPL:2026-Q3:20260918',reviewedAt:'2026-09-18',publishedAt:'2026-07-30',period:'FY2026 Q3',previousPeriod:'FY2025 Q3',sourceLevel:'公式決算資料',
    title:'使い続けたい道具が、買い替えとサービスを生む。',
    value:'使いやすさと、機器を組み合わせたときの便利さ。「次もこれを使いたい」と思える体験が強みになる、という見方です。',
    business:'iPhoneなどの機器販売に、アプリ・クラウドなどのサービス収益が重なる。端末を売った後の利用にも着目します。',
    chain:['機器とサービスを一緒に使う体験が良くなる','継続利用・買い替え・サービス利用が増える','製品売上と継続的なサービス売上が伸びる'],
    thesis:'端末の魅力が利用者をつなぎ留め、その基盤からサービスも伸びれば、買い替え周期だけに依存しない成長につながるという仮説です。',
    facts:['iPhone売上542.52億ドルに対し、Services売上307.39億ドル。','Services売上は前年同期274.23億ドルから増加。製品以外の収益も確認できます。'],
    revenue:[94036,109417],operating:[28202,35695],
    extra:[{label:'iPhone売上',value:'542.5億ドル',note:'四半期実績'},{label:'Services売上',value:'307.4億ドル',note:'四半期実績'}],
    interpretation:'売上・営業利益ともに増加。ただし会社発表では関税還付が粗利益率を約2ポイント押し上げています。',
    risks:['魅力的な新製品でも買い替えが進まず、販売台数が伸びない。','部品費上昇や競争、サービスの規制が採算を圧迫する。'],
    next:'関税還付の一時効果を分けて、製品の成長とServicesの継続性を確認する。',
    valuation:'ブランドの強さと購入価格は別。現在株価・予想利益を未照合のため割安さは未判定。',
    caveat:'FY2026 Q3は2026-06-27終了の四半期。会社ごとに会計年度の区切りが異なります。',
    sources:[{label:'Apple：FY2026 Q3 決算発表',url:'https://www.apple.com/newsroom/2026/07/apple-reports-third-quarter-results/'},{label:'Apple：比較財務諸表（PDF）',url:'https://www.apple.com/newsroom/pdfs/fy2026q3/FY26_Q3_Consolidated_Financial_Statements.pdf'}]
  },
  {
    ticker:'NVDA',name:'NVIDIA',sector:'半導体・計算基盤',kind:'需要が利益に変わるか',
    id:'story:NVDA:2027-Q2:20260918',reviewedAt:'2026-09-18',publishedAt:'2026-08-26',period:'FY2027 Q2',previousPeriod:'FY2026 Q2',sourceLevel:'公式決算資料',
    title:'AIを動かしたい企業へ、計算の土台を届ける。',
    value:'計算チップだけでなく、接続やソフトウェアを含めて動かしやすい環境を提供する。その導入価値に着目します。',
    business:'クラウド企業などへ計算・ネットワーク基盤を販売。顧客がAIを使って稼げるほど、増設需要につながるという構造です。',
    chain:['顧客のAI利用・計算需要が増える','計算基盤の増設・更新が進む','出荷増と採算維持が売上・利益を押し上げる'],
    thesis:'顧客の投資が実際の収益につながり、増設が続くなら成長が持続するという仮説です。設備投資の大きさだけで最終需要を証明はできません。',
    facts:['Data Center売上890億ドル、前年同期比 +117%。','全社売上は前年同期467.43億ドルから962.21億ドルへ。'],
    revenue:[46743,96221],operating:[28440,63734],
    extra:[{label:'Data Center売上成長',value:'+117%',note:'会社発表・前年同期比'},{label:'全社粗利益率',value:'75.0%',note:'GAAP・四半期実績'}],
    interpretation:'売上以上に営業利益が増加しています。次は、顧客の採算と投資継続がこの成長を支えられるかを見ます。',
    risks:['顧客の投資回収が遅れ、増設注文が縮小する。','競合・顧客の自社チップ、供給や輸出の制約が成長を抑える。'],
    next:'顧客側のAI収益・設備投資と、NVIDIAの粗利益率・供給状況を組み合わせて確認する。',
    valuation:'高成長だけでは割安とは判断できません。現在株価・将来利益の期待との比較は未判定。',
    caveat:'FY2027 Q2は2026-07-26終了の四半期です。将来予想ではなく実績を描いています。',
    sources:[{label:'NVIDIA：FY2027 Q2 決算発表',url:'https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027'}]
  },
  {
    ticker:'AVGO',name:'Broadcom',sector:'半導体・業務ソフト',kind:'顧客の内製需要を取り込む',
    id:'story:AVGO:2026-Q3:20260918',reviewedAt:'2026-09-18',publishedAt:'2026-09-02',period:'FY2026 Q3',previousPeriod:'FY2025 Q3',sourceLevel:'公式決算資料',
    title:'自社専用チップを作りたい企業を、技術で支える。',
    value:'顧客が自分の用途に合った計算基盤を作るための、専用半導体とネットワーク技術。その難しい部分を担う価値に着目します。',
    business:'半導体と業務用ソフトを販売。専用AIチップ・接続技術の需要と、ソフト事業の収益を分けて見ます。',
    chain:['大手顧客が専用の計算基盤を拡張','カスタム半導体と接続部品の採用・出荷が増える','半導体売上が伸び、利益・現金を生む'],
    thesis:'顧客の内製化が設計パートナーへの需要を増やすなら成長機会になります。ただし、各案件を継続して獲得できることが前提です。',
    facts:['AI半導体売上167億ドル、前年同期比 +221%。','半導体売上208.39億ドル、インフラソフト売上87.52億ドル。'],
    revenue:[15952,29591],operating:[5887,15955],
    extra:[{label:'AI半導体売上成長',value:'+221%',note:'会社発表・前年同期比'},{label:'フリーキャッシュフロー',value:'136.65億ドル',note:'会社定義・四半期実績'}],
    interpretation:'AI半導体が伸びる一方、ソフトも収益源です。営業利益はGAAPで統一し、調整後の数値と混ぜていません。',
    risks:['大口顧客が設計先を分散し、次世代案件の取り分が減る。','案件の出荷時期や製品構成が変わり、利益率が低下する。'],
    next:'AI売上だけでなく、顧客分散・次世代設計の獲得状況と利益率を確認する。',
    valuation:'成長が強くても市場期待を下回る場合があります。現在株価・予想利益との比較は未判定。',
    caveat:'FY2026 Q3は2026-08-02終了。GAAP利益には償却等も含まれ、伸びのすべてを需要増とはみなしません。',
    sources:[{label:'Broadcom：FY2026 Q3 決算発表',url:'https://investors.broadcom.com/news-releases/news-release-details/broadcom-inc-announces-third-quarter-fiscal-year-2026-financial'}]
  }
];
if(typeof module!=='undefined'&&module.exports)module.exports=stories;
else root.OpportunityStoriesData=stories;
})(typeof window!=='undefined'?window:this);
