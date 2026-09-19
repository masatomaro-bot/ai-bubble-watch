# ai-bubble-watch

- `index.html` — 静的ダッシュボード
- `pipeline/` — ポートフォリオ・ウォッチリスト銘柄の日次テクニカル指標を計算し
  Google Sheetsへ書き込むバッチ(GitHub Actionsで日次実行)。セットアップと
  仕様は [docs/PIPELINE.md](docs/PIPELINE.md) を参照。
- `backtest/` — VCPブレイクアウト戦略(O'Neil/Minervini式)を過去データで
  検証するバックテストエンジン(手元/CIで都度実行する研究用ツール)。
  仕様は [docs/BACKTEST.md](docs/BACKTEST.md) を参照。
- `technical-practice/` — 「地合い」(市場全体の状態)判定とFFTYトレンド
  テンプレートスクリーニングを日次実行するツール(GitHub Actionsで日次実行)。
  詳細は [technical-practice/README.md](technical-practice/README.md) を参照。
  `notebooks/market_climate_explorer.ipynb` はGoogle Colab上でロジックを
  対話的に確認・調整するためのノートブック。
- `docs/index.html` — 「地合いウォッチ」静的ダッシュボード(GitHub Pages想定)。
  `docs/data/history/*.json` (毎日のGitHub Actions実行でコミットされる)を
  読んで表示する。閲覧には[GitHub Pagesの有効化](technical-practice/README.md#github-pagesダッシュボードを有効にする)が必要(手動の一回設定)。

### 地合いの企業一覧から調査・監視へ

Market Leaders と O’Neil/Minervini 一覧は、正式社名・日本語の事業説明、企業ごとの ChatGPT 調査リンク、既存の機会ウォッチへの監視追加を表示します。価格条件や数値は折りたたみ内に置き、業績・堀が確認済みであるとは表示しません。

`docs/issuer-profiles.js` は公開一次資料を照合した企業情報です。株価リストの日次更新とは別管理で、企業情報や決算の自動取得・AI分析は行いません。初期登録は8社（2026-09-19照合）。未登録企業は確認待ちとし、ティッカー・上場市場・社名の印象から所在地を推定しません。

- 中国本土・香港に経営や中核事業がある場合は `excluded`。米国本社でも中核製造が中国の場合を含みます。
- 確認済みの事業基盤が方針を通過した場合は `eligible`。中国への販売・一部拠点の存在だけで一律除外しません。地政学リスクがないという意味ではありません。
- 同定、事業基盤、支配関係に不明点がある場合は `review`。未知の銘柄も必ずこちらへ送ります。
- 新しい企業を追加する際は、同一ティッカーの正式社名、事業、経営・中核事業の所在地をIR/SECなどで照合し、根拠URL・確認日・判定理由を併記します。堀や財務の評価を事業説明に推測で書き込みません。確認日から180日を超えた登録は自動的に再確認待ちとなります。

地域の判定は、企業の候補表示だけに適用し、市場全体のRSや地合い集計の母集団は変更しません。機会ウォッチの候補、新規リーダー、補助候補欄にも同じ方針を適用します。既存の監視メモは削除しません。

検証: `cd tests && npm ci && npm test`。企業の地域判定、候補の選定前の除外、未知企業・古い企業情報の保留、二つの一覧からの重複登録防止、未保存メモの保持、破損データの保護、質問リンクとコピー代替を検証します。
