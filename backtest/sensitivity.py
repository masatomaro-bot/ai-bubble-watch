"""パラメータ感度分析(ステップ4): 損切り幅・出来高倍率などを振って指標の変化を見る。"""
from __future__ import annotations

from dataclasses import replace
from itertools import product

import pandas as pd

from backtest.engine import BacktestConfig, run_backtest
from backtest.metrics import compute_metrics

DEFAULT_STOP_LOSS_GRID = (0.06, 0.07, 0.08)
DEFAULT_VOLUME_MULTIPLIER_GRID = (1.3, 1.4, 1.5, 1.6)


def sweep(
    history: dict[str, pd.DataFrame],
    base_config: BacktestConfig | None = None,
    stop_loss_grid: tuple[float, ...] = DEFAULT_STOP_LOSS_GRID,
    volume_multiplier_grid: tuple[float, ...] = DEFAULT_VOLUME_MULTIPLIER_GRID,
) -> pd.DataFrame:
    """stop_loss_pct x volume_multiplier の格子上で総当たりバックテストし、指標を1行1組合せで返す。"""
    base_config = base_config or BacktestConfig()
    rows = []
    for stop_loss_pct, volume_multiplier in product(stop_loss_grid, volume_multiplier_grid):
        signal_config = replace(base_config.signal_config, volume_multiplier=volume_multiplier)
        config = replace(base_config, stop_loss_pct=stop_loss_pct, signal_config=signal_config)
        pf, _ = run_backtest(history, config)
        m = compute_metrics(pf)
        rows.append(
            {
                "stop_loss_pct": stop_loss_pct,
                "volume_multiplier": volume_multiplier,
                **m.to_dict(),
            }
        )
    return pd.DataFrame(rows).sort_values(["profit_factor"], ascending=False, na_position="last").reset_index(drop=True)
