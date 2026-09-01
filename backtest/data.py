"""yfinanceからの過去5年分日足取得(バックテスト用)。

pipeline/data.py と同じ一括取得手法を流用しつつ、バックテストは同じ期間の
データを何度も読み直す(シグナル確認 → バックテスト → 感度分析)ため、
ローカルparquetキャッシュを追加している。
"""
from __future__ import annotations

import logging
import os

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

DEFAULT_PERIOD = "5y"
DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "cache",
)


def fetch_history_bulk(tickers: list[str], period: str = DEFAULT_PERIOD) -> dict[str, pd.DataFrame]:
    """複数銘柄のOHLCVを一括取得する(pipeline/data.pyと同じ方式)。"""
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
        df = df.dropna(subset=["Close", "Volume"])
        if df.empty:
            logger.warning("empty history for %s", ticker)
            continue
        result[ticker] = df
    return result


def _cache_path(cache_dir: str, ticker: str) -> str:
    safe = ticker.replace("/", "_").replace("^", "_")
    return os.path.join(cache_dir, f"{safe}.parquet")


def load_history_cached(
    tickers: list[str],
    period: str = DEFAULT_PERIOD,
    cache_dir: str = DEFAULT_CACHE_DIR,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """キャッシュ(parquet)があればそれを使い、無ければyfinanceから取得して保存する。
    refresh=True で強制的に再取得する。"""
    os.makedirs(cache_dir, exist_ok=True)

    to_fetch = []
    result: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        path = _cache_path(cache_dir, ticker)
        if not refresh and os.path.exists(path):
            try:
                result[ticker] = pd.read_parquet(path)
                continue
            except Exception as exc:  # 壊れたキャッシュは再取得にフォールバック
                logger.warning("failed to read cache for %s (%s); refetching", ticker, exc)
        to_fetch.append(ticker)

    if to_fetch:
        logger.info("fetching %d/%d tickers from yfinance", len(to_fetch), len(tickers))
        fetched = fetch_history_bulk(to_fetch, period=period)
        for ticker, df in fetched.items():
            df.to_parquet(_cache_path(cache_dir, ticker))
            result[ticker] = df

    missing = set(tickers) - set(result)
    if missing:
        logger.warning("no history available for: %s", sorted(missing))
    return result
