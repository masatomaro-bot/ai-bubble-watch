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
