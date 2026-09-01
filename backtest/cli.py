"""VCPバックテストのコマンドラインエントリポイント。

実行例(進め方の推奨順序 docs/BACKTEST.md 参照):
  python -m backtest.cli fetch
  python -m backtest.cli signals --out signals.csv
  python -m backtest.cli backtest --exit-rule ma25 --sizing equal_value
  python -m backtest.cli sensitivity --out sensitivity.csv
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from backtest import data, universe
from backtest.engine import BacktestConfig, run_backtest
from backtest.metrics import compute_metrics
from backtest.sensitivity import sweep
from backtest.signals import SignalConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _load_history(args: argparse.Namespace) -> dict[str, pd.DataFrame]:
    tickers, as_of = universe.load_universe(args.universe)
    logger.info("universe: %d tickers (as_of=%s)", len(tickers), as_of)
    if "PLACEHOLDER" in as_of.upper():
        logger.warning(
            "config/ffty_universe.yaml is still a placeholder list; "
            "results below are not representative of real FFTY constituents"
        )
    return data.load_history_cached(tickers, period=args.period, cache_dir=args.cache_dir, refresh=args.refresh)


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--universe", default=None, help="path to ffty_universe.yaml (default: config/ffty_universe.yaml)")
    p.add_argument("--period", default=data.DEFAULT_PERIOD, help="yfinance period, e.g. 5y (default: 5y)")
    p.add_argument("--cache-dir", default=data.DEFAULT_CACHE_DIR, help="local parquet cache directory")
    p.add_argument("--refresh", action="store_true", help="ignore cache and refetch from yfinance")


def cmd_fetch(args: argparse.Namespace) -> int:
    history = _load_history(args)
    logger.info("fetched history for %d/%d tickers", len(history), len(universe.load_universe(args.universe)[0]))
    for ticker, df in history.items():
        logger.info("  %s: %s rows, %s -> %s", ticker, len(df), df.index.min().date(), df.index.max().date())
    return 0


def cmd_signals(args: argparse.Namespace) -> int:
    from backtest.engine import compute_signal_frames

    history = _load_history(args)
    signal_config = SignalConfig(volume_multiplier=args.volume_multiplier)
    frames = compute_signal_frames(history, signal_config)

    rows = []
    for ticker, df in frames.items():
        hits = df[df["vcp_signal"] == True]  # noqa: E712 (pandasブールインデックスのため明示比較)
        for date, row in hits.iterrows():
            rows.append(
                {
                    "ticker": ticker,
                    "date": date.date(),
                    "close": round(float(row["Close"]), 2),
                    "pivot_high": round(float(row["pivot_high"]), 2),
                    "volume": int(row["Volume"]),
                    "vol_avg_prior": round(float(row["vol_avg_prior"]), 0),
                    "volume_ratio": round(float(row["Volume"] / row["vol_avg_prior"]), 2),
                    "pct_from_52w_high": round(float(row["Close"] / row["high_252"] - 1) * 100, 1),
                }
            )
    out = pd.DataFrame(rows).sort_values(["date", "ticker"])
    logger.info("found %d signal days across %d tickers", len(out), out["ticker"].nunique() if len(out) else 0)
    if args.out:
        out.to_csv(args.out, index=False)
        logger.info("wrote %s", args.out)
    else:
        print(out.to_string(index=False))
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    history = _load_history(args)
    config = BacktestConfig(
        signal_config=SignalConfig(volume_multiplier=args.volume_multiplier),
        exit_rule=args.exit_rule,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        sizing=args.sizing,
        initial_capital=args.initial_capital,
        equal_trade_value=args.equal_trade_value,
        risk_pct=args.risk_pct,
    )
    pf, _ = run_backtest(history, config)
    metrics = compute_metrics(pf)

    print(f"exit_rule={config.exit_rule} sizing={config.sizing} stop_loss_pct={config.stop_loss_pct}")
    for key, value in metrics.to_dict().items():
        print(f"  {key}: {value}")
    print("  losing_streak_distribution:", dict(sorted(metrics.losing_streak_distribution.items())))
    return 0


def cmd_sensitivity(args: argparse.Namespace) -> int:
    history = _load_history(args)
    config = BacktestConfig(exit_rule=args.exit_rule, sizing=args.sizing, initial_capital=args.initial_capital)
    result = sweep(history, base_config=config)
    if args.out:
        result.to_csv(args.out, index=False)
        logger.info("wrote %s", args.out)
    print(result.to_string(index=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VCP backtest engine (FFTY universe)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="fetch & cache 5y daily history for the universe")
    _add_common_args(p_fetch)
    p_fetch.set_defaults(func=cmd_fetch)

    p_signals = sub.add_parser("signals", help="list VCP signal days for manual visual review (step2)")
    _add_common_args(p_signals)
    p_signals.add_argument("--volume-multiplier", type=float, default=SignalConfig().volume_multiplier)
    p_signals.add_argument("--out", default=None, help="write CSV to this path instead of stdout")
    p_signals.set_defaults(func=cmd_signals)

    p_bt = sub.add_parser("backtest", help="run the full backtest and print metrics (step3)")
    _add_common_args(p_bt)
    p_bt.add_argument("--exit-rule", choices=("stop_only", "ma25", "partial_tp"), default="ma25")
    p_bt.add_argument("--stop-loss-pct", type=float, default=0.075)
    p_bt.add_argument("--take-profit-pct", type=float, default=0.20)
    p_bt.add_argument("--sizing", choices=("equal_value", "percent_risk"), default="equal_value")
    p_bt.add_argument("--initial-capital", type=float, default=100_000.0)
    p_bt.add_argument("--equal-trade-value", type=float, default=5_000.0)
    p_bt.add_argument("--risk-pct", type=float, default=0.01)
    p_bt.add_argument("--volume-multiplier", type=float, default=SignalConfig().volume_multiplier)
    p_bt.set_defaults(func=cmd_backtest)

    p_sens = sub.add_parser("sensitivity", help="sweep stop-loss / volume-multiplier grid (step4)")
    _add_common_args(p_sens)
    p_sens.add_argument("--exit-rule", choices=("stop_only", "ma25", "partial_tp"), default="ma25")
    p_sens.add_argument("--sizing", choices=("equal_value", "percent_risk"), default="equal_value")
    p_sens.add_argument("--initial-capital", type=float, default=100_000.0)
    p_sens.add_argument("--out", default=None, help="write CSV to this path")
    p_sens.set_defaults(func=cmd_sensitivity)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
