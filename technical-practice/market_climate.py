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
  4. 市場の幅 (ブレッドス) 近似値: S&P500構成銘柄のうち52週高値/安値2%以内の比率
     -> オニミネは全米国株(公開情報では約4465銘柄)が母集団だが、ここではS&P500
        (約500銘柄) を代替母集団として使う近似値。母集団が違うため水準は
        オニミネの数字と直接比較できない点に注意。

実行環境: GitHub Actions 等、外部ネットワークに出られる環境を想定。
このリポジトリのサンドボックス内では yfinance 等の外部通信がブロックされて
いたため、ここではロジックのみ実装し、実データでの動作確認は行っていない。
初回実行時は必ず手元 (ローカル or Actions) で出力を目視確認すること。
"""

from __future__ import annotations

import datetime as dt
import io
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yfinance as yf

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
# 4. 市場の幅 (ブレッドス) 近似
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


# ----------------------------------------------------------------------------
# メイン処理
# ----------------------------------------------------------------------------

def run(breadth_universe: str = "sp500", max_breadth_tickers: int | None = None) -> dict:
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
    for etf, jp_name in SECTOR_ETFS.items():
        if etf not in sector_hist or sector_hist[etf].empty:
            continue
        rrg = compute_sector_rrg(sector_hist[etf]["Close"], benchmark_close)
        sector_results[etf] = {"name_jp": jp_name, **rrg}

    breadth = {}
    if breadth_universe == "sp500":
        tickers = get_sp500_tickers()
        if max_breadth_tickers:
            tickers = tickers[:max_breadth_tickers]
        if tickers:
            price_frames = download_history(tickers, period="1y")
            breadth = compute_breadth_near_52w(price_frames)

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
        "breadth_sp500_proxy": breadth,
    }
    return result


def flatten_for_sheet(result: dict) -> list:
    """Google Sheets への追記行 (1行) を作る。"""
    leading = [k for k, v in result["sectors"].items() if v["quadrant"] == "主導"]
    lagging = [k for k, v in result["sectors"].items() if v["quadrant"] == "遅行"]
    return [
        result["date"],
        result["nasdaq"]["distribution_days"],
        result["nasdaq"]["stalling_days"],
        result["sp500"]["distribution_days"],
        result["sp500"]["stalling_days"],
        result["nasdaq"]["above_sma50"],
        result["nasdaq"]["above_sma200"],
        result["breadth_sp500_proxy"].get("near_high_pct"),
        result["breadth_sp500_proxy"].get("near_low_pct"),
        ",".join(leading),
        ",".join(lagging),
    ]


SHEET_HEADER = [
    "date", "nasdaq_dist_days", "nasdaq_stall_days", "sp500_dist_days", "sp500_stall_days",
    "nasdaq_above_sma50", "nasdaq_above_sma200",
    "breadth_near_high_pct", "breadth_near_low_pct",
    "leading_sectors", "lagging_sectors",
]


if __name__ == "__main__":
    import json

    res = run()
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))

    # Google Sheets へ書き込む場合 (環境変数が設定されていれば)
    try:
        from sheets_writer import append_rows, ensure_worksheet
        import os

        sheet_id = os.environ.get("SPREADSHEET_ID")
        if sheet_id:
            ensure_worksheet(sheet_id, "地合いトラッカー", SHEET_HEADER)
            append_rows(sheet_id, "地合いトラッカー", [flatten_for_sheet(res)])
            print("[info] Google Sheetsへの書き込み完了", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Sheets書き込みスキップ: {e}", file=sys.stderr)
