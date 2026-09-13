"""
合成データ(ダミー価格)による計算ロジックの単体テスト。
このサンドボックスは外部ネットワーク(yfinance等)に出られないため、
実データでの動作確認はできていない。ここでは「関数の計算ロジック自体に
バグがないか」だけを、手作りのDataFrameで検証する。

実行方法:
    cd technical-practice
    python -m pytest tests/ -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from market_climate import (
    compute_distribution_and_stalling_days,
    compute_index_stage,
    compute_sector_rrg,
    compute_breadth_near_52w,
    compute_breadth_extended,
    classify_sector_temperature,
    majority_vote_market_regime,
)
from ffty_screener import compute_trend_template, compute_rs_proxy_percentiles
from universe import _parse_ishares_holdings_csv, _parse_nasdaq_listed_txt


def make_price_df(closes, volumes=None, highs=None, lows=None, start="2024-01-01"):
    n = len(closes)
    idx = pd.bdate_range(start=start, periods=n)
    closes = np.array(closes, dtype=float)
    if highs is None:
        highs = closes * 1.01
    if lows is None:
        lows = closes * 0.99
    if volumes is None:
        volumes = np.full(n, 1_000_000.0)
    return pd.DataFrame({
        "Open": closes,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    }, index=idx)


def test_distribution_day_detected():
    # 30日分、うち1日だけ -1% かつ出来高増、という単純ケース
    n = 30
    closes = [100.0] * n
    volumes = [1_000_000.0] * n
    # 25日目 (0-indexed 24) を売り抜け日にする
    closes[24] = closes[23] * (1 - 0.01)
    volumes[24] = volumes[23] * 1.5

    df = make_price_df(closes, volumes=volumes)
    result = compute_distribution_and_stalling_days(df, lookback=25)
    assert result.distribution_days == 1
    assert result.stalling_days == 0


def test_distribution_day_expires_after_5pct_rally():
    n = 30
    closes = [100.0] * n
    volumes = [1_000_000.0] * n
    closes[5] = closes[4] * (1 - 0.01)
    volumes[5] = volumes[4] * 1.5
    # その後+6%上昇させて無効化させる
    for i in range(6, n):
        closes[i] = closes[5] * 1.06

    df = make_price_df(closes, volumes=volumes)
    result = compute_distribution_and_stalling_days(df, lookback=25)
    assert result.distribution_days == 0


def test_stalling_day_detected():
    n = 30
    closes = [100.0] * n
    volumes = [1_000_000.0] * n
    highs = [c * 1.02 for c in closes]
    lows = [c * 0.98 for c in closes]

    # 10日目: +0.1%上昇、出来高増、安値圏(レンジ下位)引け
    i = 10
    closes[i] = closes[i - 1] * 1.001
    volumes[i] = volumes[i - 1] * 1.3
    # close位置 = (close - low) / (high - low) を0.1(レンジ下位10%)にする:
    # low を close のすぐ下、high をだいぶ上に置く
    rng = closes[i] * 0.06
    lows[i] = closes[i] - rng * 0.1
    highs[i] = closes[i] + rng * 0.9

    df = make_price_df(closes, volumes=volumes, highs=highs, lows=lows)
    result = compute_distribution_and_stalling_days(df, lookback=25)
    assert result.stalling_days == 1


def test_index_stage_uptrend():
    n = 260
    closes = np.linspace(100, 200, n)  # きれいな右肩上がり
    df = make_price_df(list(closes))
    stage = compute_index_stage(df)
    assert stage["above_sma50"] is True
    assert stage["above_sma150"] is True
    assert stage["above_sma200"] is True
    assert stage["sma200_rising"] is True


def test_trend_template_all_pass_for_strong_uptrend():
    n = 260
    # 52週安値の1.5倍まで滑らかに上昇させ、直近も高値圏を維持
    closes = np.linspace(50, 150, n)
    df = make_price_df(list(closes))
    tmpl = compute_trend_template(df)
    assert tmpl["c1_price_above_150_200"] is True
    assert tmpl["c2_150_above_200"] is True
    assert tmpl["c4_50_above_150_200"] is True
    assert tmpl["c5_price_above_50"] is True
    assert tmpl["c6_price_25pct_above_52w_low"] is True
    assert tmpl["c7_price_within_25pct_of_52w_high"] is True
    assert tmpl["pass_count_without_rs"] == 7


def test_trend_template_fails_for_downtrend():
    n = 260
    closes = np.linspace(150, 50, n)  # 右肩下がり
    df = make_price_df(list(closes))
    tmpl = compute_trend_template(df)
    assert tmpl["c1_price_above_150_200"] is False
    assert tmpl["pass_count_without_rs"] <= 2


def test_rs_proxy_percentile_ranks_strong_stock_highest():
    n = 260
    weak = make_price_df(list(np.linspace(100, 105, n)))
    strong = make_price_df(list(np.linspace(100, 300, n)))
    mid = make_price_df(list(np.linspace(100, 150, n)))

    percentiles = compute_rs_proxy_percentiles({"WEAK": weak, "STRONG": strong, "MID": mid})
    assert percentiles["STRONG"] > percentiles["MID"] > percentiles["WEAK"]


def test_breadth_near_52w_high():
    n = 260
    at_high = make_price_df(list(np.linspace(100, 200, n)))  # 直近が最高値圏
    at_low = make_price_df(list(np.linspace(200, 100, n)))   # 直近が最安値圏

    breadth = compute_breadth_near_52w({"HIGH_STOCK": at_high, "LOW_STOCK": at_low})
    assert breadth["universe_size"] == 2
    assert breadth["near_52w_high"] == 1
    assert breadth["near_52w_low"] == 1


def test_sector_rrg_returns_valid_quadrant():
    # 単調な相対的アウトパフォームだと相対力の"伸び率"が逓減し鈍化判定になる
    # ケースもあるため(数学的に正しい挙動)、ここでは「関数がエラーなく
    # 4象限のいずれかを返すこと」だけを検証する。
    n = 300
    idx = pd.bdate_range("2023-01-01", periods=n)
    benchmark = pd.Series(np.linspace(100, 150, n), index=idx)
    outperformer = pd.Series(np.linspace(100, 220, n), index=idx)

    rrg = compute_sector_rrg(outperformer, benchmark)
    assert rrg["quadrant"] in {"主導", "改善", "鈍化", "遅行"}
    assert rrg["rs_ratio"] is not None
    assert rrg["rs_momentum"] is not None


def test_sector_rrg_improving_for_late_acceleration():
    # 前半はベンチマークとほぼ同じ動き、終盤に急加速するセクター
    # -> 直近の相対力が急伸しているので "改善" または "主導" になるはず
    n = 300
    idx = pd.bdate_range("2023-01-01", periods=n)
    benchmark_vals = np.linspace(100, 150, n)
    outperformer_vals = benchmark_vals.copy()
    accel_start = int(n * 0.85)
    boost = np.linspace(0, 40, n - accel_start)
    outperformer_vals[accel_start:] += boost

    benchmark = pd.Series(benchmark_vals, index=idx)
    outperformer = pd.Series(outperformer_vals, index=idx)

    rrg = compute_sector_rrg(outperformer, benchmark)
    assert rrg["quadrant"] in {"主導", "改善"}


def test_breadth_extended_counts_new_highs_lows_and_volume():
    n = 260
    # 直近の終値が過去252日の最大値になるよう明確に右肩上がりにする
    up = make_price_df(list(np.linspace(100, 200, n)), volumes=[1_000_000.0] * (n - 1) + [2_000_000.0])
    # 直近の終値が過去252日の最小値になるよう右肩下がりにする
    down = make_price_df(list(np.linspace(200, 100, n)), volumes=[1_000_000.0] * (n - 1) + [500_000.0])

    ext = compute_breadth_extended({"UP": up, "DOWN": down})
    assert ext["universe_size"] == 2
    assert ext["new_52w_highs"] == 1
    assert ext["new_52w_lows"] == 1
    assert ext["advancers"] == 1
    assert ext["decliners"] == 1
    # UPの出来高2,000,000 / (2,000,000+500,000) = 80%
    assert ext["up_volume_pct"] == pytest.approx(80.0)


def test_classify_sector_temperature_up_for_strong_uptrend():
    n = 300
    idx = pd.bdate_range("2023-01-01", periods=n)
    # ベンチマークより明確に強く、かつ50/200日線を上回る右肩上がり
    benchmark = pd.Series(np.linspace(100, 130, n), index=idx)
    sector = pd.Series(np.linspace(100, 220, n), index=idx)
    assert classify_sector_temperature(sector, benchmark) == "上昇"


def test_classify_sector_temperature_down_for_weak_downtrend():
    n = 300
    idx = pd.bdate_range("2023-01-01", periods=n)
    benchmark = pd.Series(np.linspace(100, 130, n), index=idx)
    sector = pd.Series(np.linspace(100, 40, n), index=idx)
    assert classify_sector_temperature(sector, benchmark) == "調整"


def test_majority_vote_risk_off_when_majority_down():
    temps = {f"S{i}": "調整" for i in range(7)}
    temps.update({f"S{i}": "上昇" for i in range(7, 9)})
    temps["S9"] = "中立"
    temps["S10"] = "買い集め"
    result = majority_vote_market_regime(temps)
    assert result["judgement"] == "RISK-OFF"
    assert result["total"] == 11


def test_majority_vote_risk_on_when_majority_up_or_accumulating():
    temps = {f"S{i}": "上昇" for i in range(5)}
    temps.update({f"S{i}": "買い集め" for i in range(5, 8)})
    temps.update({f"S{i}": "調整" for i in range(8, 11)})
    result = majority_vote_market_regime(temps)
    assert result["judgement"] == "RISK-ON"


def test_majority_vote_mixed_when_no_majority():
    temps = {"S1": "上昇", "S2": "調整", "S3": "中立", "S4": "買い集め"}
    result = majority_vote_market_regime(temps)
    assert result["judgement"] == "MIXED"


def test_parse_ishares_holdings_csv_skips_preamble_and_filters_non_equity():
    raw_csv = (
        "iShares Russell 3000 ETF\n"
        "Fund Holdings as of,Sep 12,2026\n"
        "Inception Date,May 22,2000\n"
        "\n"
        "Ticker,Name,Sector,Asset Class,Market Value,Weight (%)\n"
        "AAPL,Apple Inc,Information Technology,Equity,1000,1.0\n"
        "MSFT,Microsoft Corp,Information Technology,Equity,900,0.9\n"
        "BRK.B,Berkshire Hathaway,Financials,Equity,800,0.8\n"
        "USD,US Dollar,Cash,Cash,50,0.05\n"
        "XTSLA,Some Future,Derivatives,Derivative,10,0.01\n"
    )
    tickers = _parse_ishares_holdings_csv(raw_csv)
    assert "AAPL" in tickers
    assert "MSFT" in tickers
    assert "BRK-B" in tickers  # クラス株の "." は "-" に変換
    assert "USD" not in tickers
    assert "XTSLA" not in tickers  # Asset Classが Equity でないため除外


def test_parse_nasdaq_listed_txt_excludes_etf_and_test_issues():
    raw_txt = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "AAPL|Apple Inc|Q|N|N|100|N|N\n"
        "QQQ|Invesco QQQ Trust|Q|N|N|100|Y|N\n"
        "ZZZT|Test Company|Q|Y|N|100|N|N\n"
        "File Creation Time: 0913202608:00|||||||\n"
    )
    tickers = _parse_nasdaq_listed_txt(raw_txt, "Symbol", "ETF", "Test Issue")
    assert tickers == ["AAPL"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
