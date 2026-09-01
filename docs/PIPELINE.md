# 日次パイプライン

ポートフォリオ・ウォッチリスト銘柄の日次テクニカル指標を自動計算し、Google Sheetsに
書き込むバッチ。毎朝、そのSheetsをAIに読ませて市場解説を生成する運用を想定している。

構成: yfinance(データ取得) → Python(指標計算) → Google Sheets(gspread) → GitHub Actions(cron実行)

## セットアップ

### 1. Google側の準備

1. Google Cloud Consoleでプロジェクトを作成し、**Google Sheets API** と
   **Google Drive API** を有効化する。
2. サービスアカウントを作成し、JSON形式の鍵をダウンロードする。
3. 書き込み先のGoogle Sheetsを新規作成し、サービスアカウントのメールアドレス
   (`xxxx@xxxx.iam.gserviceaccount.com`)を編集者として共有する。
4. スプレッドシートのURLから `SPREADSHEET_ID` (`/d/` と `/edit` の間の文字列)を控える。

### 2. GitHub Secretsの設定

リポジトリの Settings > Secrets and variables > Actions に以下を登録する。

| Secret名 | 内容 |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | ダウンロードしたサービスアカウント鍵JSONの中身をそのまま貼り付け |
| `SPREADSHEET_ID` | 書き込み先スプレッドシートのID |

### 3. ウォッチリストの設定

`config/watchlist.yaml` を実際の保有・監視銘柄に置き換える。`sector` / `industry` は
省略すると実行時にyfinanceから自動取得する。

### 4. 実行

- 自動: `.github/workflows/daily-pipeline.yml` が平日22:00 UTC(米国市場クローズ後)に実行する。
- 手動: GitHub ActionsのUIから `workflow_dispatch` で即時実行できる。
- ローカル:

  ```bash
  pip install -r requirements.txt
  export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat service-account.json)"
  export SPREADSHEET_ID="..."
  python -m pipeline.run
  ```

## 出力シート

### Watchlist_Latest(1銘柄1行、毎日上書き)

Date, Ticker, Holding, Sector, Industry, Close, DayChangePct, RelVolume, SMA50, SMA150, SMA200,
PctFrom52wHigh, PctFrom52wLow, RSRating, SectorRSRating, IndustryRSRating, VCPCandidate,
TrendTemplatePassCount, TrendTemplatePass

`Holding` は `config/watchlist.yaml` の `holding: true` 設定を反映したもの。
TRUEが実際に保有しているポートフォリオ銘柄、FALSEが観察のみ(未保有)の銘柄。

### Sector_RS(セクター/業種1行、毎日上書き)

Date, GroupType(Sector/Industry), GroupName, RSRating, MemberCount

### Breadth_History(1日1行、毎日追記)

Date, PctAbove50DMA, PctAbove200DMA, NewHighs, NewLows, Advancers, Decliners,
DistDays_<指数名>(設定した市場指数ごとに列が増える)

## 指標の計算方法と留意点

- **RS Rating**: IBDのRS Rating方式(直近1四半期40% + 以降3四半期を各20%で加重した
  リターン)をベンチマーク(`SPY`)超過分で算出し、**ウォッチリスト内でのパーセンタイル
  順位**を1〜99にスケールしたもの。全市場スクリーニングは対象外という設計方針のため、
  母集団は全市場ではなくウォッチリストである点に注意(全市場基準のIBD RS Ratingとは
  数値が一致しない)。
- **セクターRS / 業種RS**: 同様の加重リターンをセクター/業種ごとに平均し、グループ間の
  パーセンタイル順位でRS化したもの。
- **Trend Template**: Mark Minervini の8条件判定(価格>150DMA>200DMA、200DMAが上向き、
  50DMAが150DMA/200DMAより上、価格>50DMA、52週安値から+30%以上、52週高値から-25%以内、
  RS Rating 70以上)。200日分のデータが揃わない銘柄はNoneになる。
- **VCP候補判定**: 「52週高値の25%以内」「50DMA上」「直近10日の値動きのボラティリティが
  直近50日の70%未満」「直近10日平均出来高が直近50日平均の85%未満」の全条件を満たすかの
  簡易判定。実際のパターン形状(ピボット、ベース回数、形の綺麗さ)はTradingViewでの
  目視判断に委ねる前提であり、これは「候補として拾う」ためのフィルタに過ぎない。
- **Market Breadth**: 全市場のAD Lineではなく、ウォッチリスト内の集計値(50DMA/200DMA
  上の銘柄比率、新高値/新安値銘柄数、値上がり/値下がり銘柄数)。全市場スクリーニングを
  しない設計方針との整合を優先した近似。
- **Distribution Day**: 主要指数(デフォルトはS&P500・Nasdaq Composite)自体の値動きから、
  直近25営業日以内の「前日比-0.2%以上の下落 かつ 出来高増加」の日数をカウント(O'Neil方式)。

## ファンダメンタルズについて

EPS成長率・売上成長率などのファンダメンタルズはこのパイプラインの対象外。従来通り、
Seeking Alpha等の一次情報をAIとの対話で読んで解釈する運用とする。
