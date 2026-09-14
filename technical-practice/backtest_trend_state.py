"""
backtest_trend_state.py
========================
`market_climate.compute_trend_state` (O'Neil/IBD式フォロースルー・デイ判定)を、
指数の過去データに対して日ごとに計算し、その後の指数リターンとどう関係している
かを検証するスクリプト。

背景: セクター4分類(上昇/買い集め/中立/調整)の閾値は完全に自前設計で根拠が
ないという問題があった。FTDベースの3状態判定は原典の定義に近い形で実装した
ものの、それでも「本当にその後のリターンと関係があるか」は別問題であり、
検証せずに使うべきではない。このスクリプトは、少なくともその検証を行える
ようにするためのもの。

使い方:
    cd technical-practice
    python backtest_trend_state.py --ticker ^IXIC --period 5y --forward-days 20

出力: 状態(confirmed_uptrend / uptrend_under_pressure / correction)ごとの、
その後forward_days営業日のリターンの平均・中央値・勝率(プラスになった日の比率)。

注意:
- あくまで記述統計であり、取引シグナルとしての有効性を保証するものではない
- ルックアヘッドバイアスを避けるため、各日の状態はその日までのデータのみで
  計算する(将来のデータを混入させない)
- このリポジトリのサンドボックスは外部ネットワークに出られないため、
  実データでの検証は行えていない。GitHub Actions・手元PC・Google Colab等の
  ネットワークに出られる環境で実行すること
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from market_climate import compute_trend_state, download_history

# compute_trend_state は内部で直近65営業日程度しか見ないため、각 日について
# 全履歴を毎回渡す必要はない。直近WINDOW_SIZE件だけを渡すことで、日ごとの
# バックテストが O(n) で済むようにする(全履歴を毎回渡すとO(n^2)になり遅い)。
WINDOW_SIZE = 150
VALID_STATES = ("confirmed_uptrend", "uptrend_under_pressure", "correction")


def backtest_states_over_history(
    df: pd.DataFrame,
    forward_days: int = 20,
    min_history: int = 60,
    window_size: int = WINDOW_SIZE,
) -> pd.DataFrame:
    """dfの各日について、その日までのデータだけを使って地合い状態を計算し、
    その後forward_days営業日のリターンと組にしたDataFrameを返す。
    列: date, state, forward_return
    """
    close = df["Close"].dropna()
    n = len(close)

    records = []
    for t in range(min_history, n - forward_days):
        window_start = max(0, t + 1 - window_size)
        window_df = df.iloc[window_start : t + 1]
        state_result = compute_trend_state(window_df)
        if state_result.state not in VALID_STATES:
            continue
        fwd_return = float(close.iloc[t + forward_days] / close.iloc[t] - 1)
        records.append({"date": close.index[t], "state": state_result.state, "forward_return": fwd_return})

    return pd.DataFrame(records)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return pd.DataFrame(columns=["n", "mean_return_pct", "median_return_pct", "win_rate_pct"])

    grouped = results.groupby("state")["forward_return"]
    summary = pd.DataFrame({
        "n": grouped.count(),
        "mean_return_pct": (grouped.mean() * 100).round(2),
        "median_return_pct": (grouped.median() * 100).round(2),
        "win_rate_pct": (grouped.apply(lambda s: (s > 0).mean()) * 100).round(1),
    })
    return summary.reindex([s for s in VALID_STATES if s in summary.index])


def run_backtest(ticker: str, period: str, forward_days: int) -> pd.DataFrame:
    hist = download_history([ticker], period=period)
    df = hist.get(ticker)
    if df is None or df.empty:
        raise ValueError(f"{ticker} のデータが取得できなかった")
    return backtest_states_over_history(df, forward_days=forward_days)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", default="^IXIC", help="対象ティッカー(既定: ^IXIC NASDAQ総合)")
    parser.add_argument("--period", default="5y", help="取得期間(yfinance形式、既定: 5y)")
    parser.add_argument("--forward-days", type=int, default=20, help="判定後何営業日先のリターンを見るか(既定: 20)")
    args = parser.parse_args()

    results = run_backtest(args.ticker, args.period, args.forward_days)
    if results.empty:
        print("[warn] バックテスト対象データが0件でした(データ不足の可能性)", file=sys.stderr)
        return

    summary = summarize(results)
    print(f"# {args.ticker} 地合い状態別 {args.forward_days}営業日先リターン ({args.period})")
    print(summary.to_string())
    print()
    print("注: 記述統計であり取引シグナルの有効性を保証しない。nが極端に少ない状態は参考程度に。")


if __name__ == "__main__":
    main()
