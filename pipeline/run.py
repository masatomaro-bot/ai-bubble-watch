"""日次パイプラインのエントリポイント。

config/watchlist.yaml を読み込み -> yfinanceで取得 -> 指標計算 -> Google Sheetsへ書き込み。
GitHub Actions からは `python -m pipeline.run` で実行する想定。
"""
from __future__ import annotations

import datetime as dt
import logging
import sys

import pandas as pd

from pipeline import breadth, data, indicators, sheets
from pipeline.config import PipelineConfig, load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _fmt(value, digits: int = 2):
    return round(value, digits) if isinstance(value, float) else value


def _bool_str(value: bool | None) -> str | None:
    """Python の bool を Sheets 上で確実に判別できる文字列にする(空欄と False の混同を防ぐ)。"""
    return None if value is None else ("TRUE" if value else "FALSE")


def build_ticker_metrics(config: PipelineConfig, history: dict) -> tuple[dict, dict, dict, dict]:
    """各ウォッチリスト銘柄の指標を計算する。
    戻り値: (ticker -> 指標dict, ticker -> sector, ticker -> industry, ticker -> 加重リターン)"""
    sector_of: dict[str, str | None] = {}
    industry_of: dict[str, str | None] = {}
    weighted_returns: dict[str, float | None] = {}
    frames: dict[str, object] = {}

    for entry in config.watchlist:
        df = history.get(entry.ticker)
        if df is None:
            logger.warning("skip %s: no history", entry.ticker)
            continue
        df = indicators.add_moving_averages(df)
        frames[entry.ticker] = df
        weighted_returns[entry.ticker] = indicators.weighted_return(df["Close"])

        sector, industry = entry.sector, entry.industry
        if sector is None or industry is None:
            fetched_sector, fetched_industry = data.fetch_sector_industry(entry.ticker)
            sector = sector or fetched_sector
            industry = industry or fetched_industry
        sector_of[entry.ticker] = sector
        industry_of[entry.ticker] = industry

    bench_df = history.get(config.benchmark)
    bench_wr = indicators.weighted_return(bench_df["Close"]) if bench_df is not None else None
    if bench_wr is None:
        logger.warning("benchmark %s has insufficient history; RS will be unrated", config.benchmark)

    excess_returns = {
        ticker: (wr - bench_wr if wr is not None and bench_wr is not None else None)
        for ticker, wr in weighted_returns.items()
    }

    rs_ratings = indicators.percentile_ratings(excess_returns)
    sector_rs = indicators.group_ratings(excess_returns, sector_of)
    industry_rs = indicators.group_ratings(excess_returns, industry_of)

    metrics: dict[str, dict] = {}
    for ticker, df in frames.items():
        rs_rating = rs_ratings.get(ticker)
        metrics[ticker] = {
            "close": float(df["Close"].iloc[-1]),
            "day_change_pct": indicators.day_change_pct(df),
            "rel_volume": indicators.relative_volume(df),
            "sma50": _to_float(df["sma50"].iloc[-1]),
            "sma150": _to_float(df["sma150"].iloc[-1]),
            "sma200": _to_float(df["sma200"].iloc[-1]),
            "pct_from_52w_high": indicators.pct_from_52w_high(df),
            "pct_from_52w_low": indicators.pct_from_52w_low(df),
            "rs_rating": rs_rating,
            "sector_rs_rating": sector_rs.get(ticker),
            "industry_rs_rating": industry_rs.get(ticker),
            "vcp_candidate": indicators.is_vcp_candidate(df),
            "trend_template": indicators.evaluate_trend_template(df, rs_rating),
        }
    return metrics, sector_of, industry_of, weighted_returns


def _to_float(value):
    return None if pd.isna(value) else float(value)


def main() -> int:
    config = load_config()
    as_of = dt.date.today().isoformat()

    all_symbols = list(
        dict.fromkeys(
            [config.benchmark]
            + [entry.ticker for entry in config.watchlist]
            + [idx.symbol for idx in config.market_indices]
        )
    )
    logger.info("fetching history for %d symbols", len(all_symbols))
    history = data.fetch_history_bulk(all_symbols)

    metrics, sector_of, industry_of, weighted_returns = build_ticker_metrics(config, history)
    if not metrics:
        logger.error("no ticker metrics computed; aborting")
        return 1

    watchlist_rows = []
    breadth_rows = []
    for entry in config.watchlist:
        m = metrics.get(entry.ticker)
        if m is None:
            continue
        tt = m["trend_template"]
        watchlist_rows.append(
            [
                as_of,
                entry.ticker,
                _bool_str(entry.holding),
                sector_of.get(entry.ticker) or "",
                industry_of.get(entry.ticker) or "",
                _fmt(m["close"]),
                _fmt(m["day_change_pct"]),
                _fmt(m["rel_volume"]),
                _fmt(m["sma50"]),
                _fmt(m["sma150"]),
                _fmt(m["sma200"]),
                _fmt(m["pct_from_52w_high"]),
                _fmt(m["pct_from_52w_low"]),
                m["rs_rating"],
                m["sector_rs_rating"],
                m["industry_rs_rating"],
                _bool_str(m["vcp_candidate"]),
                tt.pass_count if tt else None,
                _bool_str(tt.passed if tt else None),
            ]
        )
        breadth_rows.append(
            {
                "close": m["close"],
                "sma50": m["sma50"],
                "sma200": m["sma200"],
                "pct_from_52w_high": m["pct_from_52w_high"],
                "pct_from_52w_low": m["pct_from_52w_low"],
                "day_change_pct": m["day_change_pct"],
            }
        )

    sector_rows = [
        [as_of, "Sector", group, rating, count]
        for group, rating, count in indicators.summarize_groups(weighted_returns, sector_of)
    ]
    industry_rows = [
        [as_of, "Industry", group, rating, count]
        for group, rating, count in indicators.summarize_groups(weighted_returns, industry_of)
    ]

    watchlist_breadth = breadth.watchlist_breadth(breadth_rows)
    dist_days = []
    for idx in config.market_indices:
        idx_df = history.get(idx.symbol)
        dist_days.append(breadth.count_distribution_days(idx_df) if idx_df is not None else None)

    logger.info("writing to Google Sheets")
    client = sheets.get_client()
    sh = sheets.open_spreadsheet(client)
    sheets.write_watchlist_latest(sh, watchlist_rows)
    sheets.write_sector_rs(sh, sector_rows + industry_rows)
    sheets.append_breadth_history(
        sh,
        [
            as_of,
            _fmt(watchlist_breadth["pct_above_50dma"]),
            _fmt(watchlist_breadth["pct_above_200dma"]),
            watchlist_breadth["new_highs"],
            watchlist_breadth["new_lows"],
            watchlist_breadth["advancers"],
            watchlist_breadth["decliners"],
            *dist_days,
        ],
        [idx.name for idx in config.market_indices],
    )
    logger.info("done: %d tickers written", len(watchlist_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
