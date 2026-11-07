"""weekly.py(週間ウォッチ)の解析・判定ロジックの単体テスト。ネットワークには出ない。"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import weekly as wk

SAMPLE = """
Key Metrics
• Earnings Scorecard: For Q3 2026 (with 89% of S&P 500 companies reporting actual results), 82% of S&P 500
companies have reported a positive EPS surprise and 70% of S&P 500 companies have reported a positive revenue surprise.
• Earnings Guidance: For Q4 2026, 19 S&P 500 companies have issued negative EPS guidance and 28 S&P 500
companies have issued positive EPS guidance.
• Earnings Growth: For Q4 2026, analysts are projecting earnings growth of 18.1% and revenue growth of 9.0%.
For CY 2026, analysts are projecting earnings growth of 31.0%. For CY 2027, analysts are projecting earnings
growth of 15.4%.
• Valuation: The forward 12-month P/E ratio for the S&P 500 is 17.7. This P/E ratio is below the 5-year average
(19.8) and below the 10-year average (19.1).
"""


def test_parse_factset_text_extracts_key_metrics():
    p = wk.parse_factset_text(SAMPLE)
    assert (p["pe"], p["pe_avg5"], p["pe_avg10"]) == (17.7, 19.8, 19.1)
    assert p["guidance_quarter"] == "Q4 2026"
    assert (p["guidance_negative"], p["guidance_positive"]) == (19, 28)
    assert p["beat_pct"] == 82.0
    assert p["quarters"]["Q4 2026"] == 18.1
    assert p["years"] == {"CY2026": 31.0, "CY2027": 15.4}


def test_parse_factset_text_missing_values_are_none():
    p = wk.parse_factset_text("nothing useful here")
    assert p["pe"] is None and p["guidance_negative"] is None and p["quarters"] == {}


def test_revision_series_and_lamp():
    rows = [
        {"issue_date": "2026-10-30", "guidance_quarter": "Q4 2026", "quarters": {"Q4 2026": 18.5}, "years": {"CY2027": 15.6}},
        {"issue_date": "2026-11-06", "guidance_quarter": "Q4 2026", "quarters": {"Q4 2026": 18.1}, "years": {"CY2027": 15.4}},
    ]
    q, y = wk.revision_series(rows, "quarter"), wk.revision_series(rows, "year")
    assert q["values"] == [18.5, 18.1] and y["labels"] == ["CY2027", "CY2027"]
    assert wk.lamp_eps_revision(q, y)["state"] == "on"
    rows[1]["years"]["CY2027"] = 15.9
    assert wk.lamp_eps_revision(wk.revision_series(rows, "quarter"), wk.revision_series(rows, "year"))["state"] == "watch"


def test_revision_lamp_skips_period_rollover():
    rows = [
        {"issue_date": "2026-12-25", "guidance_quarter": "Q4 2026", "quarters": {"Q4 2026": 18.0}, "years": {"CY2027": 15.0}},
        {"issue_date": "2027-01-01", "guidance_quarter": "Q1 2027", "quarters": {"Q1 2027": 12.0}, "years": {"CY2028": 11.0}},
    ]
    lamp = wk.lamp_eps_revision(wk.revision_series(rows, "quarter"), wk.revision_series(rows, "year"))
    assert lamp["state"] == "unknown"


def test_guidance_lamp():
    assert wk.lamp_guidance([{"guidance_negative": 30, "guidance_positive": 20, "guidance_quarter": "Q4 2026"}])["state"] == "on"
    assert wk.lamp_guidance([{"guidance_negative": 19, "guidance_positive": 28}])["state"] == "off"
    assert wk.lamp_guidance([])["state"] == "unknown"


def test_credit_lamp_and_hy_build():
    idx = pd.date_range("2021-11-01", "2026-11-06", freq="B")
    s = pd.Series(4.0, index=idx)
    s.iloc[-30:] = 3.0
    s.iloc[-3:] = 3.3
    hy = wk.build_hy_oas(fetch=lambda _: s)
    assert hy["avg_5y"] > hy["latest"]
    assert wk.lamp_credit(hy)["state"] == "watch"  # 平均より下だが4週前より拡大
    hy["latest"] = 9.9
    assert wk.lamp_credit(hy)["state"] == "on"
    assert wk.lamp_credit(None)["state"] == "unknown"


def test_manual_rows_fill_only_missing_values():
    cache = {"2026-11-06": {"week": "2026-11-06", "issue_date": "2026-11-06", "pe": 17.7, "guidance_negative": None,
                            "guidance_positive": None, "quarters": {}, "years": {}}}
    manual = [{"week": "2026-11-06", "pe": 99.0, "pe_avg5": None, "pe_avg10": None, "guidance_quarter": "Q4 2026",
               "guidance_negative": 19.0, "guidance_positive": 28.0}]
    out = wk.merge_manual_into_factset(cache, manual)["2026-11-06"]
    assert out["pe"] == 17.7  # Aの値は上書きしない
    assert out["guidance_negative"] == 19 and out["filled_by_manual"] is True


def test_manual_aaii_merge_and_cuts_lamp():
    manual = [{"week": "2026-11-06", "aaii_bull": 34.1, "aaii_neutral": 17.5, "aaii_bear": 48.4, "aaii_date": "2026-11-04",
               "warn3": "未点灯", "warn3_reason": "下方修正はAI関連に限られる", "summary": "x"}]
    aaii = wk.merge_manual_into_aaii([], manual)
    assert aaii[0]["bear"] == 48.4 and aaii[0]["date"] == "2026-11-04"
    assert wk.lamp_breadth_of_cuts(manual)["state"] == "off"
    manual[0]["warn3"] = "点灯"
    assert wk.lamp_breadth_of_cuts(manual)["state"] == "on"


def test_cftc_build_and_last_friday():
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-10-27", "2026-11-03"]),
        "noncomm_positions_long_all": [223724, 220530],
        "noncomm_positions_short_all": [37273, 40982],
        "open_interest_all": [500000, 500000],
    })
    c = wk.build_cftc(fetcher=lambda code: df)
    assert c["gold"]["latest_net"] == 220530 - 40982
    assert c["gold"]["chg_1w"] == (220530 - 40982) - (223724 - 37273)
    assert wk.last_friday(date(2026, 11, 8)) == date(2026, 11, 6)
    assert wk.last_friday(date(2026, 11, 6)) == date(2026, 11, 6)


def test_parse_factset_text_tolerates_pdf_noise():
    """PDFから取り出した文字に異体字のハイフン・空白や段組みの割り込みがあっても読める(2026-11-07修正)。"""
    noisy = (
        "Valuation: The forward 12‑month P/E ratio for the S&P 500 is 18.7. This P/E ratio is below the 5‐year "
        "average (19.8) and below the 10‐year average (19.1).\n"
        "For Q4 2026, analysts are projecting\nTopic of the Week sidebar text\nearnings growth of 28.4% and revenue growth of 13.1%. "
        "For CY 2026, the estimated (year-over-year) earnings growth rate for the S&P 500 is 32.9%. "
        "For CY 2027, analysts are projecting revenue growth of 9.6% and earnings growth of 16.3%."
    )
    p = wk.parse_factset_text(noisy)
    assert (p["pe"], p["pe_avg5"], p["pe_avg10"]) == (18.7, 19.8, 19.1)
    assert p["quarters"] == {"Q4 2026": 28.4}
    assert p["years"] == {"CY2026": 32.9, "CY2027": 16.3}
    assert wk.parse_coverage(p) == ["ガイダンス件数"]


def test_year_series_uses_next_calendar_year_only():
    rows = [{"issue_date": "2026-11-06", "quarters": {}, "years": {"CY2026": 24.0}}]
    y = wk.revision_series(rows, "year")
    assert y["labels"] == ["CY2027"] and y["values"] == [None]  # 今年の値を「来年」として出さない


def test_revision_lamp_ignores_stale_values():
    """最新号で値が読めなかったら、数か月前の値どうしで判定せず「不明」にする。"""
    rows = [
        {"issue_date": "2026-06-19", "quarters": {}, "years": {"CY2027": 23.3}},
        {"issue_date": "2026-06-26", "quarters": {}, "years": {"CY2027": 24.0}},
        {"issue_date": "2026-11-06", "quarters": {}, "years": {}},
    ]
    lamp = wk.lamp_eps_revision(wk.revision_series(rows, "quarter"), wk.revision_series(rows, "year"))
    assert lamp["state"] == "unknown"
