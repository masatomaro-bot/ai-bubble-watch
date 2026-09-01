"""config/watchlist.yaml の読み込み。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "watchlist.yaml",
)


@dataclass
class MarketIndex:
    symbol: str
    name: str


@dataclass
class WatchlistEntry:
    ticker: str
    sector: str | None = None
    industry: str | None = None
    holding: bool = False  # True: 実際に保有しているポートフォリオ銘柄 / False: 観察のみ(未保有)


@dataclass
class PipelineConfig:
    benchmark: str
    market_indices: list[MarketIndex]
    watchlist: list[WatchlistEntry] = field(default_factory=list)


def load_config(path: str | None = None) -> PipelineConfig:
    path = path or os.environ.get("WATCHLIST_CONFIG", DEFAULT_CONFIG_PATH)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    market_indices = [
        MarketIndex(symbol=i["symbol"], name=i.get("name", i["symbol"]))
        for i in raw.get("market_indices", [])
    ]
    watchlist = [
        WatchlistEntry(
            ticker=item["ticker"],
            sector=item.get("sector"),
            industry=item.get("industry"),
            holding=bool(item.get("holding", False)),
        )
        for item in raw.get("watchlist", [])
    ]

    if not watchlist:
        raise ValueError(f"watchlist is empty in {path}")

    return PipelineConfig(
        benchmark=raw["benchmark"],
        market_indices=market_indices,
        watchlist=watchlist,
    )
