"""
backtest_warning_flags.py
==========================
compute_warning_flags()(警戒チェックリスト、market_climate.py参照)の
妥当性を検証するためのバックテスト。backtest_trend_state.pyと同じ考え方:
「点灯した日のその後のリターンが、点灯していない日と比べてどう違うか」を
記述統計として出す。取引シグナルとしての有効性を保証するものではない。

【重要な制約・検証できていない範囲】
警戒チェックリスト5項目のうち、このスクリプトで検証できるのは
指数・セクターETFという少数銘柄のデータだけで過去に遡って再計算できる
以下の2項目のみ:

  - elevated_distribution (売り抜け日数が多い)
  - defensive_rotation (ディフェンシブ優位・グロース劣位のローテーション)

残り3項目 (breadth_thrust_divergence, new_lows_exceed_highs,
leader_breakdown) は、数千銘柄の広域ユニバースの「その日時点での」
スナップショット(52週高値/安値、50日線上比率等)が必要で、日次パイプライン
(docs/data/history/)は2026-09-14から蓄積を始めたばかりのため、過去に
遡ったブレッドス計算はできない。今のところ未検証のまま。将来、履歴が
十分に蓄積された時点で、蓄積済みのdocs/data/history/*.jsonを直接使って
別途検証する必要がある。

使い方:
    cd technical-practice
    python backtest_warning_flags.py --index-ticker ^GSPC --period 5y --forward-days 20
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from market_climate import (
    BENCHMARK_FOR_SECTORS,
    DEFENSIVE_SECTOR_ETFS,
    GROWTH_SECTOR_ETFS,
    IMPROVING_QUADRANTS,
    SECTOR_ETFS,
    WARNING_DISTRIBUTION_DAYS_THRESHOLD,
    WEAKENING_QUADRANTS,
    compute_distribution_and_stalling_days,
    download_history,
)

DIST_WINDOW_SIZE = 60  # compute_distribution_and_stalling_daysのlookback(25日)+余裕
RRG_ZSCORE_WINDOW = 252  # compute_sector_rrgの正規化窓と同じ(先読みなしのrolling版)
RRG_SMOOTH_WINDOW = 10
RRG_MOM_WINDOW = 5


def backtest_elevated_distribution(
    index_df: pd.DataFrame, forward_days: int = 20, min_history: int = 60
) -> pd.DataFrame:
    """指数の売り抜け日数(直近25営業日)がWARNING_DISTRIBUTION_DAYS_THRESHOLD
    以上だった日のフラグ点灯/非点灯と、その後forward_days営業日のリターンを
    組にして返す。列: date, active, forward_return"""
    close = index_df["Close"].dropna()
    n = len(close)
    records = []
    for t in range(min_history, n - forward_days):
        window_start = max(0, t + 1 - DIST_WINDOW_SIZE)
        window_df = index_df.iloc[window_start : t + 1]
        try:
            dist = compute_distribution_and_stalling_days(window_df)
        except ValueError:
            continue
        active = dist.distribution_days >= WARNING_DISTRIBUTION_DAYS_THRESHOLD
        fwd_return = float(close.iloc[t + forward_days] / close.iloc[t] - 1)
        records.append({"date": close.index[t], "active": active, "forward_return": fwd_return})
    return pd.DataFrame(records)


def _rrg_quadrant_series(
    sector_close: pd.Series,
    benchmark_close: pd.Series,
    smooth_window: int = RRG_SMOOTH_WINDOW,
    mom_window: int = RRG_MOM_WINDOW,
    zscore_window: int = RRG_ZSCORE_WINDOW,
) -> pd.Series:
    """compute_sector_rrgと同じ考え方のRS-Ratio/RS-Momentumを、各日について
    「その日までのデータだけ」を使うrolling版で計算し、日ごとの象限を
    時系列で返す(先読みバイアスを避けるため、正規化のmean/stdは
    rolling(zscore_window)を使う。compute_sector_rrg本体は毎回全体の
    tail(252)を使うため、厳密には近似だが先読みは発生しない)。"""
    rs = (sector_close / benchmark_close).dropna()
    rs_smooth = rs.rolling(smooth_window).mean().dropna()

    def normalize_rolling(series: pd.Series) -> pd.Series:
        mean = series.rolling(zscore_window, min_periods=2).mean()
        std = series.rolling(zscore_window, min_periods=2).std()
        out = 100 + (series - mean) / std
        out[(std == 0) | std.isna()] = 100
        return out

    rs_ratio = normalize_rolling(rs_smooth)
    rs_mom_raw = rs_ratio.pct_change(mom_window)
    rs_momentum = normalize_rolling(rs_mom_raw.dropna())

    combined = pd.DataFrame({"rs_ratio": rs_ratio, "rs_momentum": rs_momentum}).dropna()

    def quadrant_of(row) -> str:
        if row["rs_ratio"] >= 100 and row["rs_momentum"] >= 100:
            return "主導"
        if row["rs_ratio"] >= 100 and row["rs_momentum"] < 100:
            return "鈍化"
        if row["rs_ratio"] < 100 and row["rs_momentum"] < 100:
            return "遅行"
        return "改善"

    return combined.apply(quadrant_of, axis=1)


def backtest_defensive_rotation(
    sector_hist: dict, benchmark_close: pd.Series, index_close: pd.Series, forward_days: int = 20
) -> pd.DataFrame:
    """ディフェンシブ優位・グロース劣位のローテーションが点灯した日の、
    指数のその後forward_days営業日のリターンを検証する。列: date, active, forward_return"""
    quadrant_series = {}
    for etf in set(DEFENSIVE_SECTOR_ETFS) | set(GROWTH_SECTOR_ETFS):
        close = sector_hist.get(etf)
        if close is None:
            continue
        quadrant_series[etf] = _rrg_quadrant_series(close["Close"].dropna(), benchmark_close)

    common_dates = None
    for s in quadrant_series.values():
        common_dates = s.index if common_dates is None else common_dates.intersection(s.index)
    if common_dates is None or len(common_dates) == 0:
        return pd.DataFrame(columns=["date", "active", "forward_return"])

    index_close_aligned = index_close.reindex(common_dates).dropna()
    records = []
    dates = list(index_close_aligned.index)
    for i, date in enumerate(dates):
        if i + forward_days >= len(dates):
            break
        defensive_quads = [quadrant_series[etf].get(date) for etf in DEFENSIVE_SECTOR_ETFS if etf in quadrant_series]
        growth_quads = [quadrant_series[etf].get(date) for etf in GROWTH_SECTOR_ETFS if etf in quadrant_series]
        defensive_improving = sum(1 for q in defensive_quads if q in IMPROVING_QUADRANTS)
        growth_weakening = sum(1 for q in growth_quads if q in WEAKENING_QUADRANTS)
        active = bool(
            defensive_quads and growth_quads
            and defensive_improving >= len(defensive_quads) / 2
            and growth_weakening >= len(growth_quads) / 2
        )
        fwd_return = float(index_close_aligned.iloc[i + forward_days] / index_close_aligned.iloc[i] - 1)
        records.append({"date": date, "active": active, "forward_return": fwd_return})
    return pd.DataFrame(records)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return pd.DataFrame(columns=["n", "mean_return_pct", "median_return_pct", "win_rate_pct"])
    grouped = results.groupby("active")["forward_return"]
    summary = pd.DataFrame({
        "n": grouped.count(),
        "mean_return_pct": (grouped.mean() * 100).round(2),
        "median_return_pct": (grouped.median() * 100).round(2),
        "win_rate_pct": (grouped.apply(lambda s: (s > 0).mean()) * 100).round(1),
    })
    summary.index = summary.index.map({True: "点灯", False: "消灯"})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index-ticker", default="^GSPC", help="対象指数(既定: ^GSPC S&P500)")
    parser.add_argument("--period", default="5y", help="取得期間(yfinance形式、既定: 5y)")
    parser.add_argument("--forward-days", type=int, default=20, help="判定後何営業日先のリターンを見るか(既定: 20)")
    args = parser.parse_args()

    tickers = [args.index_ticker, BENCHMARK_FOR_SECTORS] + list(SECTOR_ETFS.keys())
    hist = download_history(tickers, period=args.period)

    index_df = hist.get(args.index_ticker)
    if index_df is None or index_df.empty:
        print(f"[error] {args.index_ticker} のデータが取得できなかった", file=sys.stderr)
        sys.exit(1)
    benchmark_close = hist.get(BENCHMARK_FOR_SECTORS)
    if benchmark_close is None or benchmark_close.empty:
        print(f"[error] {BENCHMARK_FOR_SECTORS} のデータが取得できなかった", file=sys.stderr)
        sys.exit(1)
    benchmark_close = benchmark_close["Close"].dropna()

    print(f"# elevated_distribution ({args.index_ticker}, {args.period}, forward={args.forward_days}営業日)")
    dist_results = backtest_elevated_distribution(index_df, forward_days=args.forward_days)
    if dist_results.empty:
        print("[warn] データ不足", file=sys.stderr)
    else:
        print(summarize(dist_results).to_string())
    print()

    print(f"# defensive_rotation ({args.index_ticker}, {args.period}, forward={args.forward_days}営業日)")
    sector_hist = {etf: hist[etf] for etf in SECTOR_ETFS if etf in hist and not hist[etf].empty}
    rotation_results = backtest_defensive_rotation(
        sector_hist, benchmark_close, index_df["Close"].dropna(), forward_days=args.forward_days
    )
    if rotation_results.empty:
        print("[warn] データ不足", file=sys.stderr)
    else:
        print(summarize(rotation_results).to_string())
    print()
    print(
        "注: 記述統計であり取引シグナルの有効性を保証しない。残り3項目"
        "(breadth_thrust_divergence, new_lows_exceed_highs, leader_breakdown)は"
        "広域ユニバースの過去スナップショットがないため検証できていない。"
    )


if __name__ == "__main__":
    main()
