# VCPバックテストエンジン

O'Neil/Minervini式VCPブレイクアウトのルールを過去データで検証し、勝率・期待値・
最大ドローダウン・連敗分布を数値化するための研究用ツール(`backtest/` 配下)。
日次でGoogle Sheetsに書き込む本番パイプライン(`pipeline/`, [docs/PIPELINE.md](PIPELINE.md))
とは独立しており、GitHub Actionsには組み込んでいない(手元/CIで都度実行する想定)。

## スコープと既知の限界

- **候補プール**: FFTY(Innovator IBD 50 ETF)の**現行**構成銘柄のみ
  (`config/ffty_universe.yaml`)。全市場スクリーニングは対象外。
- **生存バイアス**: 過去時点でのFFTY構成銘柄変遷データ(無償では入手困難)を
  使っていないため、「現在の構成銘柄だけで過去5年をテストする」形になって
  いる。過去に脱落した銘柄が母集団から漏れる分、結果は実際より良く出過ぎる
  傾向がある。**この構成である限り、バックテスト結果は"参考値"として扱う
  こと。**もし将来的に過去時点の構成銘柄データが入手できれば、
  `backtest/universe.py` の読み込み元を差し替えて年ごとのプールで
  バックテストし直すのが望ましい。
- **RS Rating条件は含めない**: `pipeline/indicators.py` のTrend Template(8条件)
  と異なり、本バックテストの トレンドテンプレートは5条件版(RS Rating 70+を
  除く)。過去時点で全市場横断のRS順位を再現するデータが無く、また対象が
  そもそもIBD 50スクリーニング済みのFFTY構成銘柄であるため優先度を下げた。
- **ステップ3(収縮パターン)は近似**: 実際のVCPパターン形状(ピボットの
  きれいさ、ベース回数)の目視判断の代わりに、値幅・出来高の「波ごとの
  収縮」を数値的に近似している(詳細は `backtest/signals.py` docstring)。

## 構成

```
backtest/
  universe.py    - config/ffty_universe.yaml の読み込み
  data.py        - yfinance一括取得 + data/cache/ へのparquetキャッシュ
  signals.py     - ステップ1(トレンドテンプレート)/2(ブレイクアウト)/3(収縮)のシグナル計算
  engine.py      - vectorbtによるバックテスト実行(エントリー/エグジット/サイジング)
  metrics.py     - 勝率・期待値・PF・最大DD・連敗分布の算出
  sensitivity.py - パラメータ(損切り幅・出来高倍率)の感度分析
  cli.py         - コマンドラインエントリポイント
config/ffty_universe.yaml - 対象銘柄プール(手動更新)
```

追加依存は `requirements.txt` ではなく `requirements-backtest.txt` に分離している
(vectorbt/numba/plotlyは重く、日次ダッシュボード更新には不要なため)。

```bash
pip install -r requirements.txt -r requirements-backtest.txt
```

## 進め方(推奨順序)

### 1. 対象銘柄の設定とデータ取得

`config/ffty_universe.yaml` を実際の現行FFTY構成銘柄で更新してから実行する
(初期状態はコード動作確認用のプレースホルダで、実際の構成銘柄ではない)。
Innovator ETFs公式サイトの保有銘柄ページ(`https://www.innovatoretfs.com/etf/?ticker=FFTY`)
を参照するか、配布されているCSVがあれば `backtest.universe.load_from_holdings_csv()`
で読み込める。

```bash
python -m backtest.cli fetch
```

過去5年分の日足を取得し `data/cache/` にparquetキャッシュする
(2回目以降は `--refresh` を付けない限りキャッシュを使う)。

### 2. シグナル一覧の目視チェック(最優先)

```bash
python -m backtest.cli signals --out signals.csv
```

トレンドテンプレート+ブレイクアウト+収縮パターンをすべて満たした
「シグナル発生日」を全銘柄分CSVに書き出す。**ここで実際にTradingView等で
チャートを開き、自分がVCPと判断する形と機械判定がどの程度一致するかを
目視で確認すること。**一致度が低い場合は `backtest/signals.py` の
`SignalConfig`(ピボット遡り日数、出来高倍率、波の数など)を調整してから
次のステップに進む。

### 3. バックテスト実行

```bash
python -m backtest.cli backtest --exit-rule ma25 --sizing equal_value
```

- `--exit-rule`: `stop_only`(損切りのみ) / `ma25`(損切り+25日線割れ) /
  `partial_tp`(損切り+建玉を2分割して半分は+20%利確、残りは25日線トレール)。
  損切り(`--stop-loss-pct`, デフォルト-7.5%)はどのモードでも常に有効。
- `--sizing`: `equal_value`(1トレード固定ドル額) / `percent_risk`
  (1トレードあたりリスクを資本の`--risk-pct`に固定し、ストップ幅から株数を逆算)。
  ルール自体の有効性と資金管理の効果を分離して比較する目的。

出力される指標: `n_trades`, `win_rate`, `avg_win`/`avg_loss`, `expectancy`
(ドル建て) / `expectancy_pct`(リターン%建て), `profit_factor`, `max_drawdown`,
`losing_streak_distribution`(連敗数ごとの発生回数), `max_losing_streak`,
`final_value`, `total_return_pct`。

### 4. 感度分析

```bash
python -m backtest.cli sensitivity --exit-rule ma25 --out sensitivity.csv
```

損切り幅(`stop_loss_pct`)と出来高倍率(`volume_multiplier`)の組み合わせを
総当たりし、指標の変化を一覧化する(`backtest/sensitivity.py` のグリッドは
関数引数で変更可能)。

## 先読みバイアス対策

- 移動平均(SMA)は当日終値を含む標準的な定義のまま使用(引け後に確定する
  値であり先読みではない)。
- ただしブレイクアウト判定の基準となる**出来高平均**と**ピボット高値**は、
  当日のデータを含めない(`shift(1)` してから rolling)。当日自身の出来高
  スパイクや終値が、それと比較される基準値そのものを歪めてしまうのを防ぐため。
- エントリーは「シグナル発生日(ブレイクアウト確認日)の**翌営業日始値**」。
  シグナル自体は当日引け確定後の情報のみで判定している。

## エンジンの近似・単純化(既知の妥協点)

- `partial_tp` モードはvectorbtにネイティブな「同一ポジションの部分決済」
  機能が無いため、同じシグナルに従う2枚(各50%サイズ)の建玉として近似
  している。レポート上のtrade件数は実質的な「1トレード2分割決済」の2倍に
  なる点に注意。
- `percent_risk` サイジングの1トレードあたりリスク額は「初期資本 ×
  risk_pct」で固定しており、口座残高の増減(複利)には追随しない単純化。
- ストップロス/利確はClose基準の近似(日中の高安値を使った厳密な指値/逆指値
  シミュレーションではない)。
- `freq="1D"`(暦日ベース)でリターンを年率換算しており、実際の取引日ベース
  とは若干ずれる(年率換算指標を追加する場合は要調整。現状の指標セットは
  年率換算を使っていないため実害は無い)。

## セクター/業種RSとの関係

`pipeline/indicators.py` に既にある `is_vcp_candidate`(最新1行のみの簡易判定)
とは別実装。日次ダッシュボードは「今日時点でVCP候補っぽいか」を出すのが目的、
本バックテストは「過去のシグナル発生日を全部洗い出して検証する」のが目的
であり、要求される時系列全体でのベクトル化(先読みバイアス対策込み)が
異なるため、あえてロジックを共有していない。
