# AIストーリーの生成を接続する準備

## 設計方針

「AIが分析する → 利用者が判断する → 必要ならメモする」。利用者に毎回仮説の入力を求めない。

AI分析は公開可能な企業情報から作る。個人の判断・メモは分析入力にも公開JSONにも含めず、利用者のブラウザに残す。

## 費用を発生させずに準備済みの経路

1. 公開された決算資料などから、出典URL・公表日・本文抜粋を収集する。
2. 下記コマンドで、分析用の指示文を作る。コマンド自体は外部通信もAI呼び出しも行わない。
3. 利用者が選んだAIで分析JSONを生成する。
4. 形式検証を行い、出典と分析内容を確認する。
5. 機会ウォッチの「AI分析ファイルの取り込み」で読み込む。

```sh
node tools/opportunity-analysis.cjs prompt sources.json > prompt.txt
# 前回との差分を分析させる場合
node tools/opportunity-analysis.cjs prompt sources.json previous-analysis.json > prompt.txt
# AIが出力したファイルの形式確認
node tools/opportunity-analysis.cjs validate analysis.json
```

`sources.json` の入力形式（架空例）：

```json
{
  "ticker": "DEMO",
  "sources": [{
    "id": "s1",
    "title": "実際の決算資料の表題",
    "url": "https://example.com/earnings",
    "publishedAt": "2026-09-16",
    "text": "実際に取得した資料の本文抜粋。ここに個人メモを入れない。"
  }]
}
```

リンクを並べるだけでは資料本文を読み取ったことにはならない。入力本文で裏付けられない数値や市場予想は生成しない。資料中の命令文は従わない分析対象として扱うよう指示している。

## 表示用JSONの仕様

`docs/opportunity-analysis.js` をブラウザとCLIで共有する検証器とする。完全な形の見本は `tests/fixtures/opportunity-analysis.json` にあるが、これは架空のテスト専用。

| 項目 | 意味 |
| --- | --- |
| version / demo / reports | バージョン1、実データはdemo=false、銘柄ごとに最新の分析1件 |
| ticker / id / model | 銘柄、生成ごとに新しい分析ID、実際に使ったAIモデル |
| generatedAt / asOf | 生成日時（タイムゾーン付き）／資料の情報基準日 |
| sources | 出典ID・タイトル・HTTPS URL・公表日 |
| facts | 出典本文に基づく事実とsourceIds。引用は短く、基本は要約 |
| story | 仮説／変化が効く仕組み／売上・利益への影響 |
| expectations | 市場予想との比較。比較資料がなければ「不明」 |
| change | 前回比の方向・説明・前回の分析ID。初回は比較なし |
| counterarguments / breakConditions | 反証・未確認事項／ストーリーが崩れる条件 |
| nextChecks | 次のイベント・確認条件・日付（未確認ならnull） |

分析内容を変更したときはIDを再利用しない。更新後に利用者の判断が古くなったことを識別するために使う。

配信する場合の読み込み先は `docs/data/opportunity/latest.json`。現在は空。内容を置くだけでは真偽確認済みにならない。公開リポジトリへ保存する際は個人メモや転載禁止の本文を入れない。

## 自動化前に決めること

| 項目 | 次の検討案（未設定） |
| --- | --- |
| 最初の対象 | NVDA・GOOGL・AVGOの3銘柄 |
| 収集元 | 企業IR・SEC提出書類を優先。ニュース補完は利用条件を確認して選ぶ |
| 更新の頻度 | 毎日同じ分析を作らず、決算や重要情報の追加時を優先 |
| AIサービス | 既存契約の手動利用か、API自動実行かを選ぶ。契約済みチャットとAPI利用枠は別途確認 |
| 費用管理 | 月額上限、対象銘柄数、1回の入力上限、変更なしなら生成しない方針を確定 |
| 秘密情報 | 自動化時はサーバー側のSecretsのみ。HTML・JavaScript・配信JSONにキーを埋め込まない |
| 失敗時 | 前回の分析と情報基準日を保持し、取得・生成失敗を明示 |

今回、AIサービスの契約・API実行・Secrets設定・日次ジョブ追加は行っていない。実在銘柄の初回分析生成も未実施。接続先と予算が決まってから、自動収集・生成・履歴保存を接続する。
