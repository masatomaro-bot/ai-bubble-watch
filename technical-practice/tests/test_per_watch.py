"""per_watch.py(ポートフォリオウォッチの日次更新)の単体テスト。ネットワークには出ない。"""

import copy
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import per_watch as pw

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _holding():
    """確定年度のPERが10〜29倍に均等に並ぶ、小さな銘柄データ。"""
    series = [[f"2025-{m:02d}-01", 10.0 + i, None, None] for i, m in enumerate(range(1, 13))]
    series += [[f"2025-{m:02d}-15", 22.0 + i, None, None] for i, m in enumerate(range(1, 9))]
    weekly = []
    d = date(2025, 3, 3)
    for i in range(45):
        c = 100.0 + i
        weekly.append([d.isoformat(), c - 1, c + 2, c - 3, c, None, None])
        d = date.fromordinal(d.toordinal() + 7)
    weekly = pw.merge_weekly([], [(date.fromisoformat(r[0]), r[1], r[2], r[3], r[4]) for r in weekly])
    return {
        "ticker": "TEST", "currency": "USD",
        "eps_now": {"lo": 8.0, "hi": 10.0, "from": "2026-01-05"},
        "series": series, "weekly": weekly,
        "frame": {"eps_lo": 12.0, "eps_hi": 13.0, "bands": []},
    }


def test_monday_of_aligns_holiday_weeks():
    assert pw.monday_of(date(2026, 11, 13)) == date(2026, 11, 9)
    assert pw.monday_of(date(2021, 2, 16)) == date(2021, 2, 15)  # 祝日で火曜始まりの週
    assert pw.monday_of(date(2026, 11, 9)) == date(2026, 11, 9)


def test_merge_weekly_upserts_and_computes_moving_averages():
    h = _holding()
    last = h["weekly"][-1]
    assert last[5] == pytest.approx(sum(100.0 + i for i in range(35, 45)) / 10)
    assert last[6] == pytest.approx(sum(100.0 + i for i in range(5, 45)) / 40)
    # 同じ週を上書き(水曜の日付で渡しても月曜の足に入る)
    wed = date.fromordinal(date.fromisoformat(last[0]).toordinal() + 2)
    out = pw.merge_weekly(h["weekly"], [(wed, 1.0, 2.0, 0.5, 200.0)])
    assert len(out) == len(h["weekly"])
    assert out[-1][0] == last[0] and out[-1][4] == 200.0
    assert out[-1][5] == pytest.approx((sum(100.0 + i for i in range(35, 44)) + 200.0) / 10)
    # 触っていない足の移動平均はそのまま
    assert out[-2][5:] == h["weekly"][-2][5:]


def test_merge_weekly_skips_nan_and_keeps_104():
    h = _holding()
    out = pw.merge_weekly(h["weekly"], [(date(2030, 1, 7), float("nan"), 1.0, 1.0, 1.0)])
    assert out == h["weekly"]
    many = [(date.fromordinal(date(2020, 1, 6).toordinal() + 7 * i), 1.0, 1.0, 1.0, 1.0) for i in range(150)]
    assert len(pw.merge_weekly([], many)) == pw.WEEKLY_KEEP


def test_recompute_per_range_percentile_and_bands():
    h = _holding()
    h["weekly"] = pw.merge_weekly(h["weekly"], [(date(2026, 1, 5), 150.0, 170.0, 140.0, 160.0)])
    pw.recompute(h)
    assert h["price"] == 160.0
    assert h["per_now"] == "16.0〜20.0"      # 160÷10 〜 160÷8
    assert h["per_now_mid"] == 18.0
    # 確定PERは10..21と22..29の20個。18より小さいのは10..17の8個 → 40%
    assert h["percentile_now"] == 40
    assert h["per_max"] == 29.0
    # 進行中の年度の行は週足から作り直され、確定行は残る
    assert h["series"][-1] == ["2026-01-05", None, 16.0, 20.0]
    assert sum(1 for r in h["series"] if r[1] is not None) == 20
    # 来年度の枠
    assert (h["frame"]["per_now_lo"], h["frame"]["per_now_hi"]) == (12.3, 13.3)
    names = [b["name"] for b in h["frame"]["bands"]]
    assert names == pw.BAND_NAMES
    top = h["frame"]["bands"][-1]
    assert (top["mult"], top["lo"], top["hi"]) == (29.0, 348.0, 377.0)
    # 株価換算は今期EPSの幅 × 過去の倍率
    assert h["price_cap"] == pw.fmt_range(h["p90"] * 8.0, h["p90"] * 10.0)


def test_recompute_rejects_bad_eps():
    h = _holding()
    h["eps_now"]["lo"] = 0
    with pytest.raises(ValueError):
        pw.recompute(h)


def test_apply_bars_keeps_holding_when_fetch_missing():
    a, b = _holding(), _holding()
    b["ticker"] = "MISS"
    for h in (a, b):
        h["weekly"] = pw.merge_weekly(h["weekly"], [(date(2026, 1, 5), 150.0, 170.0, 140.0, 160.0)])
        h["price_date"] = "2026-01-09"
    data = {"asof": "2026-01-09", "holdings": [a, b]}
    pw.apply_bars(data, {"TEST": [(date(2026, 1, 12), 160.0, 185.0, 158.0, 180.0)]}, {"TEST": "2026-01-14"})
    assert a["price"] == 180.0 and a["price_date"] == "2026-01-14"
    assert b["price"] == 160.0 and b["price_date"] == "2026-01-09"   # 取得できなかった銘柄は前回のまま
    assert data["asof"] == "2026-01-14"


def test_fmt_helpers():
    assert pw.fmt_price(492.2) == "492" and pw.fmt_price(45.44) == "45.4"
    assert pw.fmt_range(196.4, 211.2) == "196〜211" and pw.fmt_range(26.41, 26.41) == "26.4"


# ---- 実データ(docs/data/per_watch.json)が更新スクリプトの前提を満たしているか

def _real():
    with open(os.path.join(REPO, "docs", "data", "per_watch.json"), encoding="utf-8") as fp:
        return json.load(fp)


def test_real_data_has_fields_the_updater_needs():
    d = _real()
    assert d.get("eps_rule") and d.get("eps_asof")
    for h in d["holdings"]:
        assert h.get("yf"), h["ticker"]
        e = h["eps_now"]
        assert 0 < e["lo"] <= e["hi"] and e["from"], h["ticker"]
        assert isinstance(h.get("core_checked"), bool), h["ticker"]
        assert len(h["weekly"]) >= 40 and h["weekly"][-1][6] is not None, h["ticker"]
        assert h["weekly"][0][0] <= e["from"], f"{h['ticker']}: 進行中の年度の最初の週が週足に無い"


def test_real_data_is_a_fixed_point_of_recompute():
    """保存されている値が、保存されている週足とEPSの前提から計算した値と一致する。"""
    d = _real()
    again = pw.apply_bars(copy.deepcopy(d), {})
    assert json.dumps(again, ensure_ascii=False, sort_keys=True) == json.dumps(d, ensure_ascii=False, sort_keys=True)


def test_fetch_bars_parses_yfinance_frames(monkeypatch):
    """yfinance の戻り値(列が2段のDataFrame)を週足に直す。最初の足(週の途中から)は捨てる。"""
    import pandas as pd

    import yf_retry

    def fake(sym, period, interval, **kw):
        if sym == "BAD":
            raise RuntimeError("boom")
        if interval == "1wk":
            idx = pd.to_datetime(["2026-10-26", "2026-11-02", "2026-11-09"])
            cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], [sym]])
            return pd.DataFrame([[1, 2, 0.5, 1.5, 9], [10, 12, 9, 11, 9], [11, 13, 10, float("nan"), 9]], index=idx, columns=cols)
        idx = pd.to_datetime(["2026-11-05", "2026-11-06"])
        return pd.DataFrame({"Close": [10.5, 11.0]}, index=idx)

    monkeypatch.setattr(yf_retry, "download_with_retry", fake)
    bars, last_day = pw.fetch_bars([{"ticker": "A", "yf": "A"}, {"ticker": "B", "yf": "BAD"}, {"ticker": "C"}])
    assert bars == {"A": [(date(2026, 11, 2), 10.0, 12.0, 9.0, 11.0)]}   # 終値が欠けた週と最初の足は入らない
    assert last_day == {"A": "2026-11-06"}
