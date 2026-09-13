"""
market_climate.py
==================
「地合い」計測スクリプト。オニミネサイト (oniminetrade.com) のトップページで
公開されているロジックの説明文をもとに、同じ考え方を自前のデータ (yfinance) で
再現する。オニミネの正確な内部実装や母集団(全銘柄)とは異なるため、完全一致は
しない。どこが「オニミネの公開説明どおり」で、どこが「こちらの解釈・近似」かは
コード内コメントに明記した。

出力する指標:
  1. 売り抜け日数 / 失速日数  (NASDAQ総合 ^IXIC, S&P500 ^GSPC)
     -> オニミネのトップページ注記の定義をそのまま実装。
  2. 主要指数のステージ状態 (50/150/200日線に対する位置)
  3. セクター・ローテーション (11 SPDRセクターETF, RRG方式: RS-Ratio / RS-Momentum)
  4. テーマ・ローテーション (代理ETFによる近似, 「産業セクター月間パフォーマンス」相当)
     -> オニミネの正確な369テーマ分類とは別物。半導体・クリーンエネ・宇宙防衛・
        原子力など、テーマ型ETFで代用できる範囲のみを近似的にカバーする。
  5. 市場の幅 (ブレッドス): 新高値/新安値銘柄数、出来高ブレッド、52週高値/安値
     2%以内の比率
     -> 母集団は universe.get_broad_market_tickers() (iShares IWV/Russell3000
        ベース、数千銘柄規模) を優先し、取得できない場合のみS&P500(約500銘柄)
        に自動でフォールバックする。オニミネの「約4461銘柄」と完全一致する
        母集団ではないため、水準を直接比較しないこと。
  6. Market Leader (個別銘柄RSランキング):
     -> 本物のIBD RSレーティングは再現できないため、ブレッドス母集団内での
        トレーリング1年リターンの百分位を代替指標(proxy)として使う
        (ffty_screener.compute_rs_proxy_percentiles と同じ考え方)。

実行環境: GitHub Actions 等、外部ネットワークに出られる環境を想定。
このリポジトリのサンドボックス内では yfinance 等の外部通信がブロックされて
いたため、ここではロジックのみ実装し、実データでの動作確認は行っていない。
初回実行時は必ず手元 (ローカル or Actions) で出力を目視確認すること。
特に広域ユニバース(universe.py)は数千銘柄をyfinanceで取得するため、実行時間
やレート制限の影響を初回実行で必ず確認すること。
"""

from __future__ import annotations

import datetime as dt
import io
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yfinance as yf

from universe import get_broad_market_tickers

try:
    from ffty_screener import compute_rs_proxy_percentiles
except ImportError:  # pragma: no cover - フォールバック(単体実行時など)
    compute_rs_proxy_percentiles = None

# ----------------------------------------------------------------------------
# 設定
# ----------------------------------------------------------------------------

NASDAQ_TICKER = "^IXIC"
SP500_TICKER = "^GSPC"
BENCHMARK_FOR_SECTORS = "SPY"

SECTOR_ETFS = {
    "XLK": "情報技術",
    "XLF": "金融",
    "XLE": "エネルギー",
    "XLV": "ヘルスケア",
    "XLI": "資本財",
    "XLP": "生活必需品",
    "XLY": "一般消費財",
    "XLU": "公益事業",
    "XLB": "素材",
    "XLC": "通信サービス",
    "XLRE": "不動産",
}

# オニミネの「15の大分類テーマ」(産業セクター月間パフォーマンス)を、入手できる
# 範囲のテーマ型ETFで近似する。オニミネ側の正確な構成銘柄・分類基準・テーマ数
# (15)とは異なる代理指標であり、テーマ名・分類自体もこちらの解釈である点に
# 注意。GICS 11セクターETF(SECTOR_ETFS)と重複しないテーマ型/サブセクター型
# ETFのみを選んでいる。
THEME_ETFS = {
    "SOXX": "半導体",
    "XOP": "エネルギー(探鉱・生産)",
    "ICLN": "クリーンエネルギー",
    "IYT": "産業・輸送",
    "FINX": "フィンテック",
    "KRE": "地銀",
    "ITA": "宇宙・防衛",
    "PICK": "素材・鉱業",
    "IBB": "バイオテクノロジー",
    "BOTZ": "AI・ロボティクス",
    "SRVR": "デジタルインフラ(データセンター)",
    "URA": "原子力(ウラン)",
}

DIST_LOOKBACK_DAYS = 25       # オニミネ注記: 直近25営業日
DIST_EXPIRY_RALLY_PCT = 0.05  # オニミネ注記: 終値が当該日比+5%で除外
DIST_DOWN_THRESHOLD = -0.002  # オニミネ注記: 前日比-0.2%以下
STALL_UP_THRESHOLD = 0.002    # オニミネ注記: +0.2%未満の小幅高
# 「安値圏引け」の閾値はオニミネ側で具体的な数値が公開されていないため、
# ここでは「当日レンジの下位25%以内で引けた」を独自定義として採用する(要調整)。
STALL_CLOSE_NEAR_LOW_RATIO = 0.25

BREADTH_NEAR_PCT = 0.02  # 「52週高値/安値の2%以内」


# ----------------------------------------------------------------------------
# 1. 売り抜け日数 / 失速日数
# ----------------------------------------------------------------------------

@dataclass
class DistributionResult:
    distribution_days: int
    stalling_days: int
    distribution_dates: list = field(default_factory=list)
    stalling_dates: list = field(default_factory=list)


def compute_distribution_and_stalling_days(
    df: pd.DataFrame,
    lookback: int = DIST_LOOKBACK_DAYS,
    expiry_rally_pct: float = DIST_EXPIRY_RALLY_PCT,
) -> DistributionResult:
    """
    df: yfinance の日足データ (列: Open, High, Low, Close, Volume)。
        直近 lookback 営業日+アルファを含んでいること。
    """
    df = df.copy().dropna(subset=["Close", "Volume"])
    if len(df) < lookback + 2:
        raise ValueError("データ不足: lookback+2営業日以上のデータが必要")

    df["pct_change"] = df["Close"].pct_change()
    df["vol_increase"] = df["Volume"] > df["Volume"].shift(1)
    day_range = (df["High"] - df["Low"]).replace(0, np.nan)
    df["close_pos_in_range"] = (df["Close"] - df["Low"]) / day_range
    df["close_pos_in_range"] = df["close_pos_in_range"].fillna(0.5)

    recent = df.iloc[-lookback:]
    latest_close = df["Close"].iloc[-1]

    dist_mask = (recent["pct_change"] <= DIST_DOWN_THRESHOLD) & recent["vol_increase"]
    stall_mask = (
        (recent["pct_change"] >= 0)
        & (recent["pct_change"] < STALL_UP_THRESHOLD)
        & recent["vol_increase"]
        & (recent["close_pos_in_range"] <= STALL_CLOSE_NEAR_LOW_RATIO)
    )

    # +5%ラリーによる除外 (当日終値 -> 直近終値が+5%以上なら無効化)
    def not_expired_by_rally(day_close: float) -> bool:
        return latest_close < day_close * (1 + expiry_rally_pct)

    dist_dates = [
        d for d, ok in zip(recent.index[dist_mask], recent.loc[dist_mask, "Close"].apply(not_expired_by_rally))
        if ok
    ]
    stall_dates = [
        d for d, ok in zip(recent.index[stall_mask], recent.loc[stall_mask, "Close"].apply(not_expired_by_rally))
        if ok
    ]

    return DistributionResult(
        distribution_days=len(dist_dates),
        stalling_days=len(stall_dates),
        distribution_dates=[d.strftime("%Y-%m-%d") for d in dist_dates],
        stalling_dates=[d.strftime("%Y-%m-%d") for d in stall_dates],
    )


# ----------------------------------------------------------------------------
# 2. 指数ステージ状態
# ----------------------------------------------------------------------------

def compute_index_stage(df: pd.DataFrame) -> dict:
    close = df["Close"]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma150 = close.rolling(150).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    price = close.iloc[-1]
    sma200_1m_ago = close.rolling(200).mean().iloc[-22] if len(close) >= 222 else np.nan

    return {
        "price": round(float(price), 2),
        "sma50": round(float(sma50), 2) if pd.notna(sma50) else None,
        "sma150": round(float(sma150), 2) if pd.notna(sma150) else None,
        "sma200": round(float(sma200), 2) if pd.notna(sma200) else None,
        "above_sma50": bool(price > sma50) if pd.notna(sma50) else None,
        "above_sma150": bool(price > sma150) if pd.notna(sma150) else None,
        "above_sma200": bool(price > sma200) if pd.notna(sma200) else None,
        "sma200_rising": bool(sma200 > sma200_1m_ago) if pd.notna(sma200_1m_ago) else None,
    }


# ----------------------------------------------------------------------------
# 3. セクター・ローテーション (簡易RRG: RS-Ratio / RS-Momentum)
# ----------------------------------------------------------------------------

def compute_sector_rrg(
    sector_close: pd.Series,
    benchmark_close: pd.Series,
    rs_smooth_window: int = 10,
    mom_window: int = 5,
) -> dict:
    """
    JdK RRG方式の簡易版。
      RS       = sector_close / benchmark_close
      RS-Ratio = RSをrs_smooth_window期間で平滑化し、直近1年のz-scoreを
                 100を中心に正規化したもの
      RS-Mom   = RS-Ratioのmom_window期間変化率を同様に正規化したもの
    厳密な定義(相対力研究所のオリジナル計算式)とは異なる簡易近似である点に注意。
    """
    rs = (sector_close / benchmark_close).dropna()
    rs_smooth = rs.rolling(rs_smooth_window).mean().dropna()

    def normalize_to_100(series: pd.Series) -> pd.Series:
        window = series.tail(252) if len(series) > 252 else series
        mean, std = window.mean(), window.std()
        if std == 0 or pd.isna(std):
            return series * 0 + 100
        return 100 + (series - mean) / std

    rs_ratio = normalize_to_100(rs_smooth)
    rs_mom_raw = rs_ratio.pct_change(mom_window)
    rs_momentum = normalize_to_100(rs_mom_raw.dropna())

    latest_ratio = float(rs_ratio.iloc[-1]) if len(rs_ratio) else None
    latest_mom = float(rs_momentum.iloc[-1]) if len(rs_momentum) else None

    if latest_ratio is None or latest_mom is None:
        quadrant = "不明"
    elif latest_ratio >= 100 and latest_mom >= 100:
        quadrant = "主導"
    elif latest_ratio >= 100 and latest_mom < 100:
        quadrant = "鈍化"
    elif latest_ratio < 100 and latest_mom < 100:
        quadrant = "遅行"
    else:
        quadrant = "改善"

    return {
        "rs_ratio": round(latest_ratio, 2) if latest_ratio is not None else None,
        "rs_momentum": round(latest_mom, 2) if latest_mom is not None else None,
        "quadrant": quadrant,
    }


# ----------------------------------------------------------------------------
# 4. 市場の幅 (ブレッドス)
# ----------------------------------------------------------------------------

def compute_breadth_near_52w(price_frames: dict) -> dict:
    """
    price_frames: {ticker: DataFrame(Close, ...)} の辞書。約1年分のデータを想定。
    52週高値/安値の2%以内にいる銘柄の比率を計算する (母集団はここに渡した銘柄群)。
    """
    near_high = 0
    near_low = 0
    valid = 0
    for _ticker, df in price_frames.items():
        close = df["Close"].dropna()
        if len(close) < 200:
            continue
        high_52w = close.tail(252).max()
        low_52w = close.tail(252).min()
        last = close.iloc[-1]
        valid += 1
        if last >= high_52w * (1 - BREADTH_NEAR_PCT):
            near_high += 1
        if last <= low_52w * (1 + BREADTH_NEAR_PCT):
            near_low += 1

    return {
        "universe_size": valid,
        "near_52w_high": near_high,
        "near_52w_low": near_low,
        "near_high_pct": round(100 * near_high / valid, 1) if valid else None,
        "near_low_pct": round(100 * near_low / valid, 1) if valid else None,
    }


def compute_breadth_extended(price_frames: dict) -> dict:
    """
    厳密な新高値/新安値銘柄数、値上がり/値下がり銘柄数、出来高ブレッド
    (値上がり銘柄の出来高が全体に占める比率)を計算する。
    オニミネの「市場の灯」(新高値/新安値の推移)、「出来高ブレッド」表示に
    相当する自前実装。母集団はここに渡した銘柄群次第で、オニミネ側の
    「約4461銘柄」と完全一致するものではない。
    """
    new_highs = 0
    new_lows = 0
    advancers = 0
    decliners = 0
    unchanged = 0
    up_volume = 0.0
    down_volume = 0.0
    valid = 0

    for _ticker, df in price_frames.items():
        close = df["Close"].dropna()
        volume = df["Volume"].dropna()
        if len(close) < 200 or len(volume) < 2:
            continue

        last = close.iloc[-1]
        prev = close.iloc[-2]
        high_52w = close.tail(252).max()
        low_52w = close.tail(252).min()
        vol_today = volume.iloc[-1]

        valid += 1
        if last >= high_52w:
            new_highs += 1
        if last <= low_52w:
            new_lows += 1

        if last > prev:
            advancers += 1
            up_volume += float(vol_today)
        elif last < prev:
            decliners += 1
            down_volume += float(vol_today)
        else:
            unchanged += 1

    total_volume = up_volume + down_volume
    return {
        "universe_size": valid,
        "new_52w_highs": new_highs,
        "new_52w_lows": new_lows,
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "up_volume": up_volume,
        "down_volume": down_volume,
        "up_volume_pct": round(100 * up_volume / total_volume, 1) if total_volume else None,
    }


# ----------------------------------------------------------------------------
# 5. セクター温度感の多数決 (RISK-ON/RISK-OFF 判定)
# ----------------------------------------------------------------------------
#
# オニミネは「11セクターを上昇/買い集め/中立/調整の4分類にし、多数決で本日の
# 地合いを判定する」という考え方を公開しているが、各分類の具体的な閾値
# (どこからが「調整」か等)は非公開。以下は完全に自前の解釈・設計であり、
# オニミネの実際の判定と一致する保証はない。
#   - 上昇   : 価格が50日線・200日線の両方より上 かつ 相対力(RS)が直近上昇中
#   - 調整   : 価格が50日線・200日線の両方より下 かつ 相対力(RS)が直近下降中
#   - 買い集め: 価格はまだ弱い(50/200日線の一方または両方より下)が、相対力は
#              直近上昇に転じている ("資金が入り始めている"という解釈)
#   - 中立   : 上記のいずれにも当てはまらない状態
RS_TREND_WINDOW = 20  # 相対力(RS)の直近変化を見る期間(営業日)


def classify_sector_temperature(sector_close: pd.Series, benchmark_close: pd.Series) -> str:
    if len(sector_close) < 200:
        return "不明"

    price = sector_close.iloc[-1]
    sma50 = sector_close.rolling(50).mean().iloc[-1]
    sma200 = sector_close.rolling(200).mean().iloc[-1]
    if pd.isna(sma50) or pd.isna(sma200):
        return "不明"

    rs = (sector_close / benchmark_close).dropna()
    if len(rs) <= RS_TREND_WINDOW:
        return "不明"
    rs_change = rs.pct_change(RS_TREND_WINDOW).iloc[-1]
    if pd.isna(rs_change):
        return "不明"

    above_both = price > sma50 and price > sma200
    below_both = price < sma50 and price < sma200
    rs_rising = rs_change > 0

    if above_both and rs_rising:
        return "上昇"
    if below_both and not rs_rising:
        return "調整"
    if rs_rising and not above_both:
        return "買い集め"
    return "中立"


def majority_vote_market_regime(sector_temperatures: dict) -> dict:
    """セクター温度感の多数決でRISK-ON/RISK-OFF/MIXEDを判定する。
    sector_temperatures: {etf: "上昇"|"買い集め"|"中立"|"調整"|"不明"}
    """
    from collections import Counter

    valid = {k: v for k, v in sector_temperatures.items() if v != "不明"}
    counts = Counter(valid.values())
    total = len(valid)

    if total == 0:
        return {"counts": {}, "total": 0, "judgement": "不明"}

    risk_off_votes = counts.get("調整", 0)
    risk_on_votes = counts.get("上昇", 0) + counts.get("買い集め", 0)

    if risk_off_votes > total / 2:
        judgement = "RISK-OFF"
    elif risk_on_votes > total / 2:
        judgement = "RISK-ON"
    else:
        judgement = "MIXED"

    return {"counts": dict(counts), "total": total, "judgement": judgement}


# ----------------------------------------------------------------------------
# データ取得ヘルパー
# ----------------------------------------------------------------------------

def get_sp500_tickers() -> list:
    """Wikipediaの一覧ページから S&P500 構成銘柄ティッカーを取得する。
    (ブレッドス計算の母集団として使用。取得失敗時は空リストを返す)

    User-Agentを付けずにリクエストすると403 Forbiddenで弾かれることがある
    ため、ブラウザ相当のUser-Agentを明示して取得する。
    """
    import urllib.request

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read()
        tables = pd.read_html(io.BytesIO(html))
        tickers = tables[0]["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
        return tickers
    except Exception as e:  # noqa: BLE001
        print(f"[warn] S&P500銘柄リスト取得失敗: {e}", file=sys.stderr)
        return []


def download_history(tickers: list, period: str = "2y") -> dict:
    """複数ティッカーをまとめて取得し、{ticker: DataFrame} の辞書で返す。"""
    if not tickers:
        return {}
    raw = yf.download(tickers, period=period, interval="1d", group_by="ticker",
                       auto_adjust=False, progress=False, threads=True)
    result = {}
    if len(tickers) == 1:
        result[tickers[0]] = raw
        return result
    for t in tickers:
        try:
            result[t] = raw[t].dropna(how="all")
        except (KeyError, Exception):  # noqa: BLE001
            continue
    return result


# 広域ユニバース(数千銘柄)を一度にyf.downloadへ渡すと、タイムアウトや
# 部分的な取得失敗が起きやすいため、chunk_size件ずつに分けて取得する。
# 各チャンクの間に小休止を入れ、Yahoo Finance側への負荷を抑える
# (実際にどの程度の待機が必要かはこのサンドボックスでは検証できておらず、
#  初回実行時にレート制限(429など)が出ないか確認すること)。
BREADTH_DOWNLOAD_CHUNK_SIZE = 250
BREADTH_DOWNLOAD_SLEEP_SEC = 1.0


def download_history_chunked(
    tickers: list,
    period: str = "1y",
    chunk_size: int = BREADTH_DOWNLOAD_CHUNK_SIZE,
    sleep_sec: float = BREADTH_DOWNLOAD_SLEEP_SEC,
) -> dict:
    result: dict = {}
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        try:
            result.update(download_history(chunk, period=period))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] チャンク取得失敗 ({i}〜{i + len(chunk)}件目): {e}", file=sys.stderr)
        if i + chunk_size < len(tickers) and sleep_sec:
            time.sleep(sleep_sec)
    return result


def get_breadth_universe(universe: str, max_tickers: int | None = None) -> tuple[list, str]:
    """ブレッドス計算用のティッカーユニバースを返す。

    universe="broad": iShares IWV(Russell3000)ベースの広域ユニバースを試み、
      取得できなければ自動的にS&P500にフォールバックする。
    universe="sp500": 最初からS&P500のみを使う(軽量・お試し用)。
    """
    if universe == "broad":
        tickers, source = get_broad_market_tickers(max_tickers=max_tickers)
        if tickers:
            return tickers, source
        print("[warn] 広域ユニバース取得失敗のためS&P500にフォールバック", file=sys.stderr)

    from universe import sample_tickers

    tickers = get_sp500_tickers()
    return sample_tickers(tickers, max_tickers), "sp500"


# ----------------------------------------------------------------------------
# メイン処理
# ----------------------------------------------------------------------------

MARKET_LEADER_TOP_N = 20  # Market Leader (RSランキング上位) の出力件数


def run(
    breadth_universe: str = "broad",
    max_breadth_tickers: int | None = None,
) -> dict:
    """
    breadth_universe: "broad"(既定) = iShares IWV(Russell3000)ベースの広域
      ユニバースを試み、失敗時はS&P500に自動フォールバック。
      "sp500" = 最初からS&P500のみ(軽量・お試し用、CIの初回動作確認などに)。
    max_breadth_tickers: 検証用に母集団を絞りたい場合の上限(Noneで無制限)。
      "broad"を数千銘柄そのまま毎日実行するとyfinanceの負荷・実行時間が
      読めないため、初回はこれを例えば500などに絞って実行時間を確認してから
      段階的に広げることを推奨する。
    """
    today = dt.date.today().isoformat()

    idx_hist = download_history([NASDAQ_TICKER, SP500_TICKER], period="6mo")
    nasdaq_df, sp500_df = idx_hist.get(NASDAQ_TICKER), idx_hist.get(SP500_TICKER)

    nasdaq_dist = compute_distribution_and_stalling_days(nasdaq_df)
    sp500_dist = compute_distribution_and_stalling_days(sp500_df)

    stage_hist = download_history([NASDAQ_TICKER, SP500_TICKER], period="1y")
    nasdaq_stage = compute_index_stage(stage_hist[NASDAQ_TICKER])
    sp500_stage = compute_index_stage(stage_hist[SP500_TICKER])

    sector_tickers = list(SECTOR_ETFS.keys()) + [BENCHMARK_FOR_SECTORS]
    sector_hist = download_history(sector_tickers, period="1y")
    benchmark_close = sector_hist[BENCHMARK_FOR_SECTORS]["Close"]

    sector_results = {}
    sector_temperatures = {}
    for etf, jp_name in SECTOR_ETFS.items():
        if etf not in sector_hist or sector_hist[etf].empty:
            continue
        etf_close = sector_hist[etf]["Close"]
        rrg = compute_sector_rrg(etf_close, benchmark_close)
        temperature = classify_sector_temperature(etf_close, benchmark_close)
        sector_results[etf] = {"name_jp": jp_name, "temperature": temperature, **rrg}
        sector_temperatures[etf] = temperature

    market_regime = majority_vote_market_regime(sector_temperatures)

    # テーマ・ローテーション (代理ETF, GICS 11セクターと重複しない範囲)
    theme_tickers = list(THEME_ETFS.keys())
    theme_hist = download_history(theme_tickers, period="1y")
    theme_results = {}
    for etf, jp_name in THEME_ETFS.items():
        if etf not in theme_hist or theme_hist[etf].empty:
            continue
        close = theme_hist[etf]["Close"]
        rrg = compute_sector_rrg(close, benchmark_close)
        monthly_return = (
            round(100 * (close.iloc[-1] / close.iloc[-22] - 1), 2) if len(close) > 22 else None
        )
        theme_results[etf] = {"name_jp": jp_name, "monthly_return_pct": monthly_return, **rrg}

    # ブレッドス(市場の幅) + Market Leader(個別RSランキング)
    breadth_tickers, breadth_source = get_breadth_universe(breadth_universe, max_breadth_tickers)
    breadth_near_52w = {}
    breadth_extended = {}
    leaders = []
    if breadth_tickers:
        # 52週(約252営業日)ブレッドス計算とMarket LeaderのRS百分位
        # (compute_rs_proxy_percentilesは既定でlookback_days=252営業日分の
        # データを要求する)の両方に足りるよう、"1y"ではなく"2y"で取得する。
        # "1y"だと実際の営業日数が252を僅かに下回ることがあり、その場合
        # percentilesが全銘柄で計算されず market_leaders が空になる不具合が
        # 実機検証(2026-09-13)で確認されたための修正。
        price_frames = download_history_chunked(breadth_tickers, period="2y")
        breadth_near_52w = compute_breadth_near_52w(price_frames)
        breadth_extended = compute_breadth_extended(price_frames)

        if compute_rs_proxy_percentiles is not None and price_frames:
            percentiles = compute_rs_proxy_percentiles(price_frames)
            ranked = sorted(percentiles.items(), key=lambda kv: kv[1], reverse=True)
            for ticker, pct in ranked[:MARKET_LEADER_TOP_N]:
                close = price_frames[ticker]["Close"].dropna()
                if len(close) < 2:
                    continue
                day_change = round(100 * (close.iloc[-1] / close.iloc[-2] - 1), 2)
                one_month = (
                    round(100 * (close.iloc[-1] / close.iloc[-22] - 1), 2) if len(close) > 22 else None
                )
                three_month = (
                    round(100 * (close.iloc[-1] / close.iloc[-63] - 1), 2) if len(close) > 63 else None
                )
                leaders.append({
                    "ticker": ticker,
                    "rs_percentile": pct,
                    "day_change_pct": day_change,
                    "one_month_pct": one_month,
                    "three_month_pct": three_month,
                })

    result = {
        "date": today,
        "nasdaq": {
            "distribution_days": nasdaq_dist.distribution_days,
            "stalling_days": nasdaq_dist.stalling_days,
            "distribution_dates": nasdaq_dist.distribution_dates,
            "stalling_dates": nasdaq_dist.stalling_dates,
            **nasdaq_stage,
        },
        "sp500": {
            "distribution_days": sp500_dist.distribution_days,
            "stalling_days": sp500_dist.stalling_days,
            "distribution_dates": sp500_dist.distribution_dates,
            "stalling_dates": sp500_dist.stalling_dates,
            **sp500_stage,
        },
        "sectors": sector_results,
        "market_regime": market_regime,
        "themes": theme_results,
        "breadth_universe_source": breadth_source,
        "breadth_near_52w": breadth_near_52w,
        "breadth_extended": breadth_extended,
        "market_leaders": leaders,
    }
    return result


def flatten_for_sheet(result: dict) -> list:
    """Google Sheets への追記行 (1行) を作る。"""
    leading_sectors = [k for k, v in result["sectors"].items() if v["quadrant"] == "主導"]
    lagging_sectors = [k for k, v in result["sectors"].items() if v["quadrant"] == "遅行"]
    leading_themes = [k for k, v in result["themes"].items() if v["quadrant"] == "主導"]
    lagging_themes = [k for k, v in result["themes"].items() if v["quadrant"] == "遅行"]
    top_leaders = ",".join(l["ticker"] for l in result["market_leaders"][:10])

    regime = result["market_regime"]
    ext = result["breadth_extended"]
    near = result["breadth_near_52w"]

    return [
        result["date"],
        result["nasdaq"]["distribution_days"],
        result["nasdaq"]["stalling_days"],
        result["sp500"]["distribution_days"],
        result["sp500"]["stalling_days"],
        result["nasdaq"]["above_sma50"],
        result["nasdaq"]["above_sma200"],
        regime.get("judgement"),
        regime.get("counts", {}).get("上昇", 0),
        regime.get("counts", {}).get("買い集め", 0),
        regime.get("counts", {}).get("中立", 0),
        regime.get("counts", {}).get("調整", 0),
        result["breadth_universe_source"],
        ext.get("universe_size"),
        ext.get("new_52w_highs"),
        ext.get("new_52w_lows"),
        ext.get("advancers"),
        ext.get("decliners"),
        ext.get("up_volume_pct"),
        near.get("near_high_pct"),
        near.get("near_low_pct"),
        ",".join(leading_sectors),
        ",".join(lagging_sectors),
        ",".join(leading_themes),
        ",".join(lagging_themes),
        top_leaders,
    ]


SHEET_HEADER = [
    "date", "nasdaq_dist_days", "nasdaq_stall_days", "sp500_dist_days", "sp500_stall_days",
    "nasdaq_above_sma50", "nasdaq_above_sma200",
    "market_regime", "sector_count_up", "sector_count_accum", "sector_count_neutral", "sector_count_down",
    "breadth_universe_source", "breadth_universe_size",
    "breadth_new_52w_highs", "breadth_new_52w_lows",
    "breadth_advancers", "breadth_decliners", "breadth_up_volume_pct",
    "breadth_near_high_pct", "breadth_near_low_pct",
    "leading_sectors", "lagging_sectors",
    "leading_themes", "lagging_themes",
    "top_market_leaders",
]


LEADER_SHEET_HEADER = ["date", "ticker", "rs_percentile", "day_change_pct", "one_month_pct", "three_month_pct"]


def flatten_leaders_for_sheet(result: dict) -> list[list]:
    return [
        [result["date"], l["ticker"], l["rs_percentile"], l["day_change_pct"], l["one_month_pct"], l["three_month_pct"]]
        for l in result["market_leaders"]
    ]


if __name__ == "__main__":
    import json
    import os

    # 運用中に母集団を調整できるよう環境変数で上書き可能にしておく。
    # BREADTH_UNIVERSE: "broad"(既定) または "sp500"
    # MAX_BREADTH_TICKERS: 検証用に母集団件数を絞りたい場合の上限(未設定なら無制限)
    breadth_universe_env = os.environ.get("BREADTH_UNIVERSE", "broad")
    max_tickers_env = os.environ.get("MAX_BREADTH_TICKERS")
    max_tickers = int(max_tickers_env) if max_tickers_env else None

    res = run(breadth_universe=breadth_universe_env, max_breadth_tickers=max_tickers)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))

    # Google Sheets へ書き込む場合 (環境変数が設定されていれば)
    try:
        from sheets_writer import append_rows, ensure_worksheet

        sheet_id = os.environ.get("SPREADSHEET_ID")
        if sheet_id:
            ensure_worksheet(sheet_id, "地合いトラッカー", SHEET_HEADER)
            append_rows(sheet_id, "地合いトラッカー", [flatten_for_sheet(res)])

            leader_rows = flatten_leaders_for_sheet(res)
            if leader_rows:
                ensure_worksheet(sheet_id, "Market Leaders", LEADER_SHEET_HEADER)
                append_rows(sheet_id, "Market Leaders", leader_rows)

            print("[info] Google Sheetsへの書き込み完了", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Sheets書き込みスキップ: {e}", file=sys.stderr)
