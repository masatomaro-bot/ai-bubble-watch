# ai-bubble-watch

- `index.html` — 静的ダッシュボード
- `pipeline/` — ポートフォリオ・ウォッチリスト銘柄の日次テクニカル指標を計算し
  Google Sheetsへ書き込むバッチ(GitHub Actionsで日次実行)。セットアップと
  仕様は [docs/PIPELINE.md](docs/PIPELINE.md) を参照。
- `backtest/` — VCPブレイクアウト戦略(O'Neil/Minervini式)を過去データで
  検証するバックテストエンジン(手元/CIで都度実行する研究用ツール)。
  仕様は [docs/BACKTEST.md](docs/BACKTEST.md) を参照。
