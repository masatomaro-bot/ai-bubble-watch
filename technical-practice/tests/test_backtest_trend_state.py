"""backtest_trend_state.py の単体テスト。合成データでロジックのみ検証する
(このサンドボックスは外部ネットワークに出られないため、実データでの
バックテストはGitHub Actions/手元/Colab等で別途行うこと)。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from backtest_trend_state import VALID_STATES, backtest_states_over_history, summarize


def _make_price_df(closes, volumes=None):
    n = len(closes)
    idx = pd.bdate_range(start="2023-01-01", periods=n)
    closes = np.array(closes, dtype=float)
    if volumes is None:
        volumes = np.full(n, 1_000_000.0)
    return pd.DataFrame({
        "Open": closes, "High": closes * 1.01, "Low": closes * 0.99,
        "Close": closes, "Volume": volumes,
    }, index=idx)


def _ftd_then_uptrend_series(n: int = 300):
    """day0-119: 下落。day120-124: 反発+FTD。以降: 緩やかな上昇継続。"""
    closes = [150 - i * (50 / 119) for i in range(120)]
    closes += [103.0, 103.5, 103.2, 103.6, 105.5]
    volumes = [1_000_000.0] * 120 + [1_000_000.0, 1_000_000.0, 1_000_000.0, 1_000_000.0, 1_500_000.0]
    remaining = n - len(closes)
    for _ in range(remaining):
        closes.append(closes[-1] * 1.0015)
        volumes.append(500_000.0)
    return _make_price_df(closes, volumes=volumes)


def test_backtest_states_over_history_returns_valid_states_and_columns():
    df = _ftd_then_uptrend_series(300)
    results = backtest_states_over_history(df, forward_days=20, min_history=60)

    assert not results.empty
    assert list(results.columns) == ["date", "state", "forward_return"]
    assert set(results["state"].unique()) <= set(VALID_STATES)
    # FTD(day124)より後の日は上昇トレンド継続なので、confirmed_uptrendが
    # 少なくとも一定数出現するはず
    assert (results["state"] == "confirmed_uptrend").sum() > 0


def test_summarize_produces_stats_per_state():
    df = _ftd_then_uptrend_series(300)
    results = backtest_states_over_history(df, forward_days=20, min_history=60)
    summary = summarize(results)

    assert set(summary.columns) == {"n", "mean_return_pct", "median_return_pct", "win_rate_pct"}
    assert (summary["n"] > 0).all()
    # 一貫した上昇継続シナリオなので、confirmed_uptrend状態の平均フォワード
    # リターンはプラスになるはず
    if "confirmed_uptrend" in summary.index:
        assert summary.loc["confirmed_uptrend", "mean_return_pct"] > 0


def test_summarize_empty_input_returns_empty_frame():
    empty = pd.DataFrame(columns=["date", "state", "forward_return"])
    summary = summarize(empty)
    assert summary.empty


def test_backtest_avoids_lookahead_bias():
    # 全体300日のうち先頭200日分だけを渡しても、共通する日付における状態は
    # 変わらないはず(未来のデータが過去の判定に混入していないことの回帰テスト)。
    df_full = _ftd_then_uptrend_series(300)
    df_prefix = df_full.iloc[:200]

    full_results = backtest_states_over_history(df_full, forward_days=20, min_history=60)
    prefix_results = backtest_states_over_history(df_prefix, forward_days=20, min_history=60)

    common_dates = set(full_results["date"]) & set(prefix_results["date"])
    assert len(common_dates) > 0

    full_by_date = full_results.set_index("date")["state"]
    prefix_by_date = prefix_results.set_index("date")["state"]
    for d in common_dates:
        assert full_by_date[d] == prefix_by_date[d]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
