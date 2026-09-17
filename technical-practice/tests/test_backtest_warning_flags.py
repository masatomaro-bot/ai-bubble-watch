"""backtest_warning_flags.py の単体テスト。合成データでロジックのみ検証する
(このサンドボックスは外部ネットワークに出られないため、実データでの
バックテストはGitHub Actions等で別途行うこと)。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from backtest_warning_flags import (
    _rrg_quadrant_series,
    backtest_defensive_rotation,
    backtest_elevated_distribution,
    summarize,
)


def _make_price_df(closes, volumes=None, highs=None, lows=None, start="2020-01-01"):
    n = len(closes)
    idx = pd.bdate_range(start=start, periods=n)
    closes = np.array(closes, dtype=float)
    if highs is None:
        highs = closes * 1.01
    if lows is None:
        lows = closes * 0.99
    if volumes is None:
        volumes = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": volumes}, index=idx
    )


def test_backtest_elevated_distribution_detects_heavy_distribution_period():
    n = 400
    closes = [100.0] * n
    volumes = [1_000_000.0] * n
    # day200-206: 7日連続の売り抜け日(下落+出来高増)を作る
    for i in range(200, 207):
        closes[i] = closes[i - 1] * 0.99
        volumes[i] = volumes[i - 1] * 1.5
    for i in range(207, n):
        closes[i] = closes[i - 1] * 1.0005  # その後は緩やかな横ばい上昇

    df = _make_price_df(closes, volumes=volumes)
    results = backtest_elevated_distribution(df, forward_days=20, min_history=60)

    assert not results.empty
    assert list(results.columns) == ["date", "active", "forward_return"]
    # 売り抜け日が集中した直後の期間はactive=Trueになっているはず
    assert results["active"].sum() > 0


def test_backtest_elevated_distribution_avoids_lookahead_bias():
    n = 300
    closes = [100.0] * n
    volumes = [1_000_000.0] * n
    for i in range(150, 156):
        closes[i] = closes[i - 1] * 0.99
        volumes[i] = volumes[i - 1] * 1.5
    for i in range(156, n):
        closes[i] = closes[i - 1] * 1.001
    df_full = _make_price_df(closes, volumes=volumes)
    df_prefix = df_full.iloc[:250]

    full_results = backtest_elevated_distribution(df_full, forward_days=20, min_history=60)
    prefix_results = backtest_elevated_distribution(df_prefix, forward_days=20, min_history=60)

    full_by_date = full_results.set_index("date")["active"]
    prefix_by_date = prefix_results.set_index("date")["active"]
    common_dates = set(full_by_date.index) & set(prefix_by_date.index)
    assert len(common_dates) > 0
    for d in common_dates:
        assert full_by_date[d] == prefix_by_date[d]


def test_rrg_quadrant_series_no_lookahead():
    n = 400
    rng = np.random.default_rng(0)
    sector_close = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.01, n)), index=pd.bdate_range("2020-01-01", periods=n))
    benchmark_close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n)), index=sector_close.index)

    full = _rrg_quadrant_series(sector_close, benchmark_close)
    prefix = _rrg_quadrant_series(sector_close.iloc[:300], benchmark_close.iloc[:300])

    common_dates = full.index.intersection(prefix.index)
    assert len(common_dates) > 0
    assert (full.loc[common_dates] == prefix.loc[common_dates]).all()


def test_backtest_defensive_rotation_detects_rotation_scenario():
    # 前半(day0-199)はベンチマークと横ばいで足並みを揃え、後半(day200-399)で
    # ディフェンシブが対ベンチマークで加速的に上昇・グロースが加速的に下落する
    # 「明確なレジーム転換」を作る。線形の値動きだとRS-momentumが早期に横ばいに
    # 収束して象限判定が動かないため、複利(pct_change)ベースで加速をつける。
    n = 400
    idx = pd.bdate_range("2020-01-01", periods=n)
    flat_returns = np.zeros(200)
    accel_up = np.linspace(0.0, 0.01, 200)  # 徐々に加速する上昇
    accel_down = np.linspace(0.0, -0.01, 200)  # 徐々に加速する下落

    defensive_returns = np.concatenate([flat_returns, accel_up])
    growth_returns = np.concatenate([flat_returns, accel_down])
    defensive_close = pd.Series(100 * np.cumprod(1 + defensive_returns), index=idx)
    growth_close = pd.Series(100 * np.cumprod(1 + growth_returns), index=idx)
    benchmark_close = pd.Series([100.0] * n, index=idx)

    sector_hist = {
        "XLP": pd.DataFrame({"Close": defensive_close}),
        "XLV": pd.DataFrame({"Close": defensive_close}),
        "XLU": pd.DataFrame({"Close": defensive_close}),
        "XLK": pd.DataFrame({"Close": growth_close}),
        "XLY": pd.DataFrame({"Close": growth_close}),
    }
    index_close = pd.Series(100 * np.cumprod(1 + np.concatenate([flat_returns, accel_down])), index=idx)

    results = backtest_defensive_rotation(sector_hist, benchmark_close, index_close, forward_days=20)

    assert not results.empty
    assert list(results.columns) == ["date", "active", "forward_return"]
    # 明確なレジーム転換シナリオなので、後半のどこかで点灯しているはず
    assert results["active"].sum() > 0


def test_summarize_produces_stats_by_active_state():
    df = pd.DataFrame({
        "date": pd.bdate_range("2020-01-01", periods=6),
        "active": [True, True, False, False, False, True],
        "forward_return": [0.05, 0.03, -0.01, 0.02, 0.01, -0.02],
    })
    summary = summarize(df)
    assert set(summary.index) <= {"点灯", "消灯"}
    assert set(summary.columns) == {"n", "mean_return_pct", "median_return_pct", "win_rate_pct"}


def test_summarize_empty_input_returns_empty_frame():
    empty = pd.DataFrame(columns=["date", "active", "forward_return"])
    summary = summarize(empty)
    assert summary.empty


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
