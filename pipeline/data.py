"""yfinance からの日次OHLCVおよび銘柄属性(sector/industry)取得。"""
from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

HISTORY_PERIOD = "2y"  # 200DMAのトレンド判定(約1ヶ月分の遡り)に必要な余裕を持たせる


def fetch_history_bulk(tickers: list[str], period: str = HISTORY_PERIOD) -> dict[str, pd.DataFrame]:
    """複数銘柄のOHLCVを一括取得する(個別リクエストより速く、レート制限にも強い)。"""
    data = yf.download(
        tickers=tickers,
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        threads=True,
        progress=False,
    )
    is_multi = isinstance(data.columns, pd.MultiIndex)

    result: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            df = data[ticker] if is_multi else data
        except KeyError:
            logger.warning("no data returned for %s", ticker)
            continue
        # Close/Volumeが欠損した行が混じっていると、rolling/オフセット参照計算がずれるため除去する
        df = df.dropna(subset=["Close", "Volume"])
        if df.empty:
            logger.warning("empty history for %s", ticker)
            continue
        result[ticker] = df
    return result


def fetch_sector_industry(ticker: str) -> tuple[str | None, str | None]:
    try:
        info = yf.Ticker(ticker).get_info()
    except Exception as exc:  # yfinance は多様な例外を投げるため広めに捕捉
        logger.warning("failed to fetch sector/industry for %s: %s", ticker, exc)
        return None, None
    return info.get("sector"), info.get("industry")
