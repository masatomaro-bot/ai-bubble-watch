"""バックテスト結果からの指標算出(勝率・期待値・PF・最大DD・連敗分布)。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import vectorbt as vbt


@dataclass
class BacktestMetrics:
    n_trades: int
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    expectancy: float | None  # ドル建て: 勝率*平均利益 - 敗率*平均損失
    expectancy_pct: float | None  # リターン%建て(サイズ差の影響を除いた比較用)
    profit_factor: float | None
    max_drawdown: float | None
    losing_streak_distribution: dict[int, int]  # {連敗数: 発生回数}
    max_losing_streak: int
    final_value: float
    total_return_pct: float

    def to_dict(self) -> dict:
        return {
            "n_trades": self.n_trades,
            "win_rate": self.win_rate,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "expectancy": self.expectancy,
            "expectancy_pct": self.expectancy_pct,
            "profit_factor": self.profit_factor,
            "max_drawdown": self.max_drawdown,
            "max_losing_streak": self.max_losing_streak,
            "final_value": self.final_value,
            "total_return_pct": self.total_return_pct,
        }


def _losing_streaks(pnl_chronological: pd.Series) -> tuple[dict[int, int], int]:
    """PnLを時系列順に並べたSeriesから連敗の長さ分布を作る。
    戻り値: ({連敗数: 発生回数}, 最大連敗数)"""
    streaks: list[int] = []
    current = 0
    for pnl in pnl_chronological:
        if pnl < 0:
            current += 1
        else:
            if current > 0:
                streaks.append(current)
            current = 0
    if current > 0:
        streaks.append(current)

    distribution = dict(Counter(streaks))
    return distribution, (max(streaks) if streaks else 0)


def compute_metrics(pf: vbt.Portfolio) -> BacktestMetrics:
    trades = pf.trades
    records = trades.records_readable.sort_values("Exit Timestamp")
    n_trades = len(records)

    if n_trades == 0:
        return BacktestMetrics(
            n_trades=0,
            win_rate=None,
            avg_win=None,
            avg_loss=None,
            expectancy=None,
            expectancy_pct=None,
            profit_factor=None,
            max_drawdown=float(pf.max_drawdown()) if hasattr(pf, "max_drawdown") else None,
            losing_streak_distribution={},
            max_losing_streak=0,
            final_value=float(pf.final_value()),
            total_return_pct=float(pf.total_return()) * 100,
        )

    pnl = records["PnL"]
    ret = records["Return"]
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    win_rate = len(wins) / n_trades
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(-losses.mean()) if len(losses) else 0.0
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    ret_wins, ret_losses = ret[pnl > 0], ret[pnl <= 0]
    avg_win_pct = float(ret_wins.mean()) if len(ret_wins) else 0.0
    avg_loss_pct = float(-ret_losses.mean()) if len(ret_losses) else 0.0
    expectancy_pct = win_rate * avg_win_pct - (1 - win_rate) * avg_loss_pct

    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (np.inf if gross_profit > 0 else None)

    distribution, max_streak = _losing_streaks(pnl)

    return BacktestMetrics(
        n_trades=n_trades,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=expectancy,
        expectancy_pct=expectancy_pct,
        profit_factor=profit_factor,
        max_drawdown=float(pf.max_drawdown()),
        losing_streak_distribution=distribution,
        max_losing_streak=max_streak,
        final_value=float(pf.final_value()),
        total_return_pct=float(pf.total_return()) * 100,
    )
