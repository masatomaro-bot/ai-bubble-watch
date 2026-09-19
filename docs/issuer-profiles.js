/* Reviewed public issuer facts, not a security master or financial endorsement. */
(function(root){
'use strict';
const checked='2026-09-19';
const profiles={
 MGRT:{name:'Mega Fortune Company Limited',business:'香港の顧客にIoTの導入・運用サービスを提供する企業。ケイマンの持株会社を通じて上場しています。',status:'excluded',base:'香港',reason:'実際の事業を香港の子会社が担うため、対象外。登記地はケイマンです。',sources:['https://www.sec.gov/Archives/edgar/data/2033377/000149315225016325/ex99-1.htm']},
 AXTI:{name:'AXT, Inc.',business:'光通信などに使う半導体基板を製造。インジウムリンなどの材料を扱い、中国の子会社が製造を担います。',status:'excluded',base:'米国本社／中国製造',reason:'本社は米国ですが、中核の製造拠点が中国にあるため、対象外。',sources:['https://www.axt.com/']},
 ANL:{name:'Adlai Nortye Ltd.',business:'がん治療薬を開発する臨床段階のバイオ企業。中国と米国に拠点があります。',status:'review',base:'中国・米国／中核は追加確認',reason:'両国の拠点は確認できましたが、事業・経営の中核と支配関係の追加確認が必要です。',sources:['https://www.adlainortye.com/','https://www.adlainortye.com/index.php/contact']},
 IMMX:{name:'Immix Biopharma, Inc.',business:'免疫細胞を使うCAR-T療法を開発。ALアミロイドーシスなどが対象で、治験・承認と資金繰りを調べる開発段階の企業です。',status:'eligible',base:'米国／イスラエル由来の技術',reason:'米国本社と米国での臨床開発を公式IRで照合。技術のライセンス元はイスラエルです。',sources:['https://immixbio.com/investors/']},
 MRNA:{name:'Moderna, Inc.',business:'mRNAを使う医薬品を開発する企業。研究成果が承認・製品売上につながる仕組みと、研究費の負担を調べます。',status:'eligible',base:'米国／世界展開',reason:'公式IRで米国法人・ケンブリッジ本社と事業を照合。海外事業の個別リスクは別途確認します。',sources:['https://investors.modernatx.com/','https://investors.modernatx.com/investor-faqs']},
 EDRY:{name:'EuroDry Ltd.',business:'鉄鉱石・石炭・穀物などを運ぶ外航ばら積み船の企業。運賃と船の稼働率、維持・更新費用が利益を左右します。',status:'eligible',base:'ギリシャ拠点／マーシャル登記',reason:'公式資料でギリシャの事業所と外航海運事業を照合。登記地だけで中国企業とは判定しません。',sources:['https://www.eurodry.gr/','https://www.eurodry.gr/contacts/contact-corp.html']},
 MU:{name:'Micron Technology, Inc.',business:'DRAM・NANDなどのメモリーを扱う半導体企業。AI向け需要に加え、製品価格と設備投資が利益にどう影響するかを調べます。',status:'eligible',base:'米国／世界に製造・販売拠点',reason:'米国を基盤に世界で事業を展開。中国との取引・拠点の存在だけで一律除外はしません。',sources:['https://www.micron.com/about','https://www.micron.com/about/locations']},
 BE:{name:'Bloom Energy Corporation',business:'データセンターや工場などに、その場所で発電する燃料電池設備を提供。設備販売と保守で利益が残るかを調べます。',status:'eligible',base:'米国／海外展開',reason:'公式サイトで米国本社とデラウェアの製造拠点を照合。海外事業もあります。',sources:['https://www.bloomenergy.com/company/','https://www.bloomenergy.com/contact/']}
};
for(const p of Object.values(profiles))p.checked=checked;
function get(ticker,today=new Date().toISOString().slice(0,10)){
 const p=Object.hasOwn(profiles,ticker)?profiles[ticker]:null;
 if(!p)return {name:'正式社名は確認待ち',business:'企業の同定と事業内容を一次資料で確認してから、調査候補に加えます。',status:'review',base:'未確認',reason:'企業情報・事業基盤の確認資料が未登録です。',sources:[],checked:null};
 const age=(Date.parse(today)-Date.parse(p.checked))/86400000;
 if(!Number.isFinite(age)||age<0||age>180)return {...p,status:'review',reason:'企業情報の確認日から180日を超えたか、日付が不正です。再確認するまで保留。'};
 return {...p};
}
const api={get};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.IssuerProfiles=api;
})(typeof window!=='undefined'?window:this);
