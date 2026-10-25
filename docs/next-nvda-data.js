/* 「次のNVDAを探す」機会ウォッチの境シグナル表と候補の基準状態。
   2026-09-27のチャットで決めた内容をそのまま載せる。点灯状況の更新は週次の
   スケジュール済みタスク(毎週月曜)の結果を見て、このファイルを書き換える。
   S6はマサトのTradingViewチャート確認後にのみ点灯する(日次データのRSラインは補助)。 */
(function (root) {
'use strict';

const SIGNALS = [
  { id: 'S1', name: '新用途の売上が旧用途を逆転', what: 'セグメント別売上の主役交代', how: '決算資料(四半期ごと)' },
  { id: 'S2', name: '会社自身が呼び名を変える', what: 'IRの自己紹介文の変更、セグメント再編、新セグメントの開示', how: '決算リリース冒頭の一文' },
  { id: 'S3', name: '顧客がその会社を起点に設計する', what: '他社が「○○上に構築」と発表する、その会社の規格が採用される', how: 'ニュース(人の目で判定)' },
  { id: 'S4', name: '社内技術の外販・第三者顧客の獲得', what: '自社用だった基盤を他社が買い始める', how: '決算説明会・8-K' },
  { id: 'S5', name: '機関側の呼び名が変わる', what: 'アナリストのカバー担当の変更、AIテーマETFへの組み入れ、報道での形容詞の変化', how: 'Bloomberg/FT/SA' },
  { id: 'S6', name: '株価が物語を先取りする', what: 'RSライン(対NASDAQ)の新高値、倍率の切り上がり', how: 'マサトのTradingViewチャート' },
];

const RULE = 'S1〜S5のうち2つ点灯で「境接近」、3つ以上＋S6で「境通過」。S6はチャート確認後にのみ点灯。';

const BASE_DATE = '2026-09-27';

const CANDIDATES = [
  { t: 'ARM', name: 'Arm Holdings', status: '境通過候補', lit: ['S2', 'S3', 'S4'],
    biz: 'スマホ向けに作ったCPUの設計図(命令セット)をチップメーカーにライセンスし、出荷1個ごとにロイヤルティを取るIP企業。完成チップの直販も始めた。',
    watch: 'データセンター向けロイヤルティの構成比(S1)' },
  { t: 'GOOGL', name: 'Alphabet', status: '境接近', lit: ['S2', 'S4'],
    biz: '検索広告で稼ぎ、社内用に作ったTPUとクラウドをAI計算基盤として外部に広げている。',
    watch: 'クラウドと検索の差(S1)。基準銘柄(物差し)として置く' },
  { t: 'NET', name: 'Cloudflare', status: '観察中→境接近の手前', lit: ['S2'],
    biz: 'Webサイトの配信高速化と防御のために作った世界規模のネットワークを、AIエージェント時代の「インターネットの関所」に変えようとしている。',
    watch: 'AI関連売上の分離開示(S1)' },
  { t: 'ALAB', name: 'Astera Labs', status: '観察中(テストケース)', lit: [],
    biz: 'AIサーバー内のチップ同士をつなぐ接続用半導体を売る。部品メーカーが基盤になりうるかを試す検証役。',
    watch: 'S3のみ(業界がALAB製品を前提に設計し始めるか)' },
];

const api = { SIGNALS, RULE, BASE_DATE, CANDIDATES };
if (typeof module !== 'undefined' && module.exports) module.exports = api;
else root.NextNvdaData = api;
})(typeof window !== 'undefined' ? window : globalThis);
