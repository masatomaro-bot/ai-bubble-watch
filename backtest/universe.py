"""バックテスト対象プール(FFTY構成銘柄)の読み込み。

config/ffty_universe.yaml を手動更新する運用。過去時点の構成銘柄変遷が
入手できないため「現行構成銘柄のみ」を使う設計であり、生存バイアスが
生じる点に注意(docs/BACKTEST.md 参照)。
"""
from __future__ import annotations

import csv
import os

import yaml

DEFAULT_UNIVERSE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "ffty_universe.yaml",
)


def load_universe(path: str | None = None) -> tuple[list[str], str]:
    """config/ffty_universe.yaml からティッカーリストを読み込む。
    戻り値: (tickers, as_of)"""
    path = path or os.environ.get("FFTY_UNIVERSE_CONFIG", DEFAULT_UNIVERSE_PATH)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    tickers = [str(t).strip().upper() for t in raw.get("tickers", []) if str(t).strip()]
    as_of = str(raw.get("as_of", "unknown"))

    if not tickers:
        raise ValueError(f"universe is empty in {path}")
    if "PLACEHOLDER" in as_of.upper():
        import logging

        logging.getLogger(__name__).warning(
            "config/ffty_universe.yaml is still the placeholder list; "
            "replace it with the actual current FFTY holdings before running a real backtest"
        )
    return tickers, as_of


def load_from_holdings_csv(path: str) -> list[str]:
    """ETFプロバイダが配布する保有銘柄CSVからティッカー列を抽出する。
    列名に 'ticker' または 'symbol' を含む列(大文字小文字区別なし)を自動検出する。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"no header row found in {path}")
        col = next(
            (c for c in reader.fieldnames if "ticker" in c.lower() or "symbol" in c.lower()),
            None,
        )
        if col is None:
            raise ValueError(f"no ticker/symbol column found in {path}; columns={reader.fieldnames}")
        tickers = [row[col].strip().upper() for row in reader if row.get(col, "").strip()]

    if not tickers:
        raise ValueError(f"no tickers extracted from {path}")
    # 重複除去(順序保持)
    return list(dict.fromkeys(tickers))
