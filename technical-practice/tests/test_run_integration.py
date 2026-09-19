"""
market_climate.run() の結合テスト。個々の計算関数は test_calculations.py で
単体テスト済みだが、run()自体は「どの関数の戻り値をどのキーでresultに詰めるか」
という配線が多く、そこでのタイプミスやキー名の不一致は単体テストだけでは
見つからない。ここではyfinance呼び出しをすべて合成データにモックした上で
run()を実際に一度最後まで実行し、SHEET_HEADERとの整合性・JSONシリアライズ
可能性までを確認する。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

import market_climate as mc


def _fake_download_history(tickers, period="2y", missing_tolerance=0.0):
    """どんなティッカーが来ても、それらしいOHLCVを合成して返す簡易フェイク。
    ティッカー名から決定的なシードを作るので、テスト実行のたびに結果が
    変わらない。"""
    result = {}
    n = 520  # 約2年分の営業日。200日線・252日ルックバックいずれにも足りる長さ。
    idx = pd.bdate_range("2024-01-01", periods=n)
    for t in tickers:
        rng = np.random.default_rng(abs(hash(t)) % (2**32))
        returns = rng.normal(0.0006, 0.012, n)  # ゆるやかな右肩上がりのランダムウォーク
        close = 100 * np.cumprod(1 + returns)
        volume = rng.integers(500_000, 2_000_000, n).astype(float)
        result[t] = pd.DataFrame(
            {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": volume},
            index=idx,
        )
    return result


def _fake_get_breadth_universe(universe, max_tickers=None):
    tickers = [f"TST{i:02d}" for i in range(20)]
    return tickers, "test"


@pytest.fixture
def mocked_network(monkeypatch):
    monkeypatch.setattr(mc, "download_history", _fake_download_history)
    monkeypatch.setattr(mc, "get_breadth_universe", _fake_get_breadth_universe)


def test_run_end_to_end_with_mocked_network(mocked_network):
    result = mc.run(breadth_universe="broad", max_breadth_tickers=None)

    expected_top_level_keys = {
        "date", "nasdaq", "sp500", "overall_trend_state", "sectors", "market_regime",
        "themes", "breadth_universe_source", "breadth_near_52w", "breadth_extended",
        "broad_universe_technicals", "market_leaders", "trend_template_leaders",
        "stress_gauges", "warning_flags",
    }
    assert expected_top_level_keys <= set(result.keys())
    assert set(result["stress_gauges"].keys()) == {
        "vix", "credit_hyg_ief", "breadth_rsp_spy", "risk_appetite_iwm_spy", "semis_soxx_spy",
    }
    assert len(result["warning_flags"]) == 5
    assert all("id" in f and "active" in f and "label" in f for f in result["warning_flags"])
    assert isinstance(result["trend_template_leaders"], list)
    assert len(result["trend_template_leaders"]) <= mc.TREND_TEMPLATE_LEADER_TOP_N
    # trend_template_pass_tickersは内部利用後にresultから取り除かれ、
    # JSON履歴の肥大化を避ける(トレンドテンプレート合格銘柄の生リストは
    # 数百件になりうるため、毎日の履歴に残さない)
    assert "trend_template_pass_tickers" not in result["broad_universe_technicals"]

    assert result["nasdaq"]["trend_state"]["state"] in {
        "confirmed_uptrend", "uptrend_under_pressure", "correction", "不明",
    }
    assert result["sp500"]["trend_state"]["state"] in {
        "confirmed_uptrend", "uptrend_under_pressure", "correction", "不明",
    }
    assert result["overall_trend_state"] in {
        "confirmed_uptrend", "uptrend_under_pressure", "correction", "不明",
    }
    assert result["breadth_universe_source"] == "test"
    assert result["breadth_extended"]["universe_size"] == 20
    assert len(result["sectors"]) == len(mc.SECTOR_ETFS)
    assert len(result["themes"]) == len(mc.THEME_ETFS)
    assert result["opportunity_universe"]["method"] == "broad-close-return-252-percentile-v1"
    assert result["opportunity_universe"]["ranked_count"] == 20
    assert all(r["observed_date"] == result["date"] for r in result["opportunity_universe"]["rows"])
    assert isinstance(result["market_leaders"], list)
    assert len(result["market_leaders"]) <= mc.MARKET_LEADER_TOP_N


def test_run_date_uses_actual_last_trading_day_not_execution_date(mocked_network):
    # dt.date.today()(GitHub Actions実行日、UTC)は実際の株価データの最終
    # 取引日とずれることがある。result["date"]は指数データの最終行の日付
    # (=対象取引日)であるべきで、テスト実行日そのものであってはならない。
    result = mc.run(breadth_universe="broad", max_breadth_tickers=None)

    expected_last_trading_day = pd.bdate_range("2024-01-01", periods=520)[-1].date().isoformat()
    assert result["date"] == expected_last_trading_day
    assert result["date"] != dt.date.today().isoformat()


def test_flatten_for_sheet_matches_header_length(mocked_network):
    result = mc.run(breadth_universe="broad", max_breadth_tickers=None)
    result["cumulative_ad_line"] = 123  # 通常は__main__側で注入される値
    row = mc.flatten_for_sheet(result)
    assert len(row) == len(mc.SHEET_HEADER)


def test_run_result_is_json_serializable(mocked_network):
    result = mc.run(breadth_universe="broad", max_breadth_tickers=None)
    result["cumulative_ad_line"] = 42
    # default=str で例外なく変換できること(history_store.save_snapshotと同条件)
    json.dumps(result, ensure_ascii=False, default=str)


def _fake_download_history_with_trailing_nan(tickers, period="2y"):
    """2026-09-15の実データ実行で実際に発生したケースの回帰テスト用フェイク:
    yfinanceが当日分の未確定バー(Closeが欠損)を含めて返すことがある。
    最終行のCloseだけNaNにした合成データを返す。"""
    result = _fake_download_history(tickers, period=period)
    for df in result.values():
        df.loc[df.index[-1], "Close"] = np.nan
    return result


def test_run_sectors_and_themes_survive_trailing_nan_close(monkeypatch):
    # Close列の最終行がNaN(市場未確定バー)でも、day_change_pctがNaNのまま
    # resultに残らないこと(=json.dumpsでNaNリテラルが出力されず、ブラウザの
    # JSON.parse()を壊さないこと)を確認する回帰テスト。
    monkeypatch.setattr(mc, "download_history", _fake_download_history_with_trailing_nan)
    monkeypatch.setattr(mc, "get_breadth_universe", _fake_get_breadth_universe)

    result = mc.run(breadth_universe="broad", max_breadth_tickers=None)

    for etf, s in result["sectors"].items():
        dcp = s["day_change_pct"]
        assert dcp is None or (isinstance(dcp, float) and not np.isnan(dcp)), f"{etf}: {dcp}"
    for etf, s in result["themes"].items():
        dcp = s["day_change_pct"]
        assert dcp is None or (isinstance(dcp, float) and not np.isnan(dcp)), f"{etf}: {dcp}"


def test_run_saves_to_history_store(mocked_network, tmp_path, monkeypatch):
    import history_store

    monkeypatch.setattr(history_store, "HISTORY_DIR", str(tmp_path))
    result = mc.run(breadth_universe="broad", max_breadth_tickers=None)
    result["cumulative_ad_line"] = 7

    saved_path = history_store.save_snapshot(result, history_dir=str(tmp_path))
    assert os.path.exists(saved_path)
    loaded = history_store.load_snapshot(result["date"], history_dir=str(tmp_path))
    assert loaded["overall_trend_state"] == result["overall_trend_state"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
