"""Market Breadth と Distribution Day。

全市場スクリーニングは対象外のため、Breadthはウォッチリスト内の集計値とする
(全市場のAD Lineではなく「監視銘柄群のうち何%が50DMA/200DMA上か」等)。
Distribution Dayは主要指数(S&P500, Nasdaq等)そのものの値動きから判定する。
"""
from __future__ import annotations

import pandas as pd

DISTRIBUTION_WINDOW = 25  # 直近25営業日でカウント(O'Neil方式)
DISTRIBUTION_DECLINE_THRESHOLD = 0.002  # 前日比-0.2%以上の下落


def count_distribution_days(
    df: pd.DataFrame,
    window: int = DISTRIBUTION_WINDOW,
    threshold: float = DISTRIBUTION_DECLINE_THRESHOLD,
) -> int | None:
    """出来高増加を伴う下落日(Distribution Day)を直近window営業日でカウントする。"""
    if len(df) < 2:
        return None
    ret = df["Close"].pct_change()
    vol_increased = df["Volume"] > df["Volume"].shift(1)
    is_distribution = (ret <= -threshold) & vol_increased
    return int(is_distribution.tail(window).sum())


def watchlist_breadth(rows: list[dict]) -> dict:
    """rowsは各銘柄の {close, sma50, sma200, pct_from_52w_high, pct_from_52w_low,
    day_change_pct} を持つdictのリスト(indicators.py の計算結果)。"""
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "pct_above_50dma": None,
            "pct_above_200dma": None,
            "new_highs": None,
            "new_lows": None,
            "advancers": None,
            "decliners": None,
        }

    def has(row: dict, *keys: str) -> bool:
        return all(row.get(k) is not None for k in keys)

    above_50 = [r for r in rows if has(r, "close", "sma50") and r["close"] > r["sma50"]]
    above_200 = [r for r in rows if has(r, "close", "sma200") and r["close"] > r["sma200"]]
    new_highs = [r for r in rows if has(r, "pct_from_52w_high") and r["pct_from_52w_high"] >= -0.5]
    new_lows = [r for r in rows if has(r, "pct_from_52w_low") and r["pct_from_52w_low"] <= 0.5]
    advancers = [r for r in rows if has(r, "day_change_pct") and r["day_change_pct"] > 0]
    decliners = [r for r in rows if has(r, "day_change_pct") and r["day_change_pct"] < 0]

    dma50_n = sum(1 for r in rows if has(r, "close", "sma50"))
    dma200_n = sum(1 for r in rows if has(r, "close", "sma200"))

    return {
        "n": n,
        "pct_above_50dma": (len(above_50) / dma50_n * 100) if dma50_n else None,
        "pct_above_200dma": (len(above_200) / dma200_n * 100) if dma200_n else None,
        "new_highs": len(new_highs),
        "new_lows": len(new_lows),
        "advancers": len(advancers),
        "decliners": len(decliners),
    }
