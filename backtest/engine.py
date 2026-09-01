"""vectorbtによるVCPブレイクアウト戦略のバックテスト。

設計:
- エントリー: シグナル発生日(ブレイクアウト確認日)の翌営業日始値
  (signal_frames の各銘柄について1日shiftしたブール配列をvectorbtに渡し、
  price=Open指定で執行させることで再現する)。
- 損切りは常に有効(実際の裁量トレードでも例外なく使うルールという前提)。
  exit_rule でその上に重ねる利確/トレール条件を切り替える。
    - "stop_only": 損切りのみ
    - "ma25":      損切り + 25日線割れで手仕舞い
    - "partial_tp": 損切り + (ポジションを2分割し) 半分は+X%で利確、
                     残り半分は25日線割れまでトレールで伸ばす
      (vectorbtに組み込みの「同一ポジションの部分利確」機能は無いため、
      同じシグナルに従う2枚(各50%サイズ)の建玉として近似している。
      レポート上のtrade件数は実際の「1トレード2分割決済」の2倍になる点に注意)
- ポジションサイジング:
    - "equal_value":  1トレードあたり固定ドル額(config.equal_trade_value)
    - "percent_risk": 1トレードあたりリスク額(config.risk_pct * 初期資本)を
                       ストップ幅で割った株数。初期資本基準の近似であり、
                       複利(その時点の口座残高)には追随しない単純化。
- 複数銘柄はcash_sharing=True, group_by=Trueで単一口座としてシミュレートし、
  資金配分の競合(同時シグナルが資金枠を上回る場合)も反映する。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import vectorbt as vbt

from backtest.signals import SignalConfig, vcp_entry_signal

EXIT_RULES = ("stop_only", "ma25", "partial_tp")
SIZING_MODES = ("equal_value", "percent_risk")


@dataclass
class BacktestConfig:
    signal_config: SignalConfig = field(default_factory=SignalConfig)
    exit_rule: str = "ma25"
    stop_loss_pct: float = 0.075  # -7.5%
    take_profit_pct: float = 0.20  # partial_tp時の利確ライン(+20%)
    sizing: str = "equal_value"
    initial_capital: float = 100_000.0
    equal_trade_value: float = 5_000.0  # equal_value時の1トレードあたり投資額
    risk_pct: float = 0.01  # percent_risk時の1トレードあたりリスク(資本の%)
    fees: float = 0.0005  # 片道手数料(概算)

    def __post_init__(self) -> None:
        if self.exit_rule not in EXIT_RULES:
            raise ValueError(f"exit_rule must be one of {EXIT_RULES}, got {self.exit_rule!r}")
        if self.sizing not in SIZING_MODES:
            raise ValueError(f"sizing must be one of {SIZING_MODES}, got {self.sizing!r}")


def compute_signal_frames(
    history: dict[str, pd.DataFrame], signal_config: SignalConfig | None = None
) -> dict[str, pd.DataFrame]:
    """各銘柄にステップ1〜3の指標・シグナル列を付与する(ステップ2の目視チェック用にも使う)。"""
    signal_config = signal_config or SignalConfig()
    return {ticker: vcp_entry_signal(df, signal_config) for ticker, df in history.items()}


def _wide(frames: dict[str, pd.DataFrame], column: str) -> pd.DataFrame:
    return pd.concat({ticker: f[column] for ticker, f in frames.items()}, axis=1)


def _entry_size_shares(open_wide: pd.DataFrame, entries: pd.DataFrame, risk_dollar: float, stop_loss_pct: float) -> pd.DataFrame:
    """percent_riskサイジング: 建玉サイズ(株数) = リスク許容額 / (エントリー価格 * 損切り幅)。
    エントリー行以外は np.inf(vectorbtの「全力建玉」既定値、非エントリー行では無視される)。"""
    shares = pd.DataFrame(np.inf, index=open_wide.index, columns=open_wide.columns)
    risk_per_share = open_wide * stop_loss_pct
    computed = risk_dollar / risk_per_share.where(risk_per_share > 0)
    shares = shares.where(~entries, computed)
    return shares


def run_backtest(history: dict[str, pd.DataFrame], config: BacktestConfig | None = None) -> tuple[vbt.Portfolio, dict[str, pd.DataFrame]]:
    """FFTYプール全銘柄をまとめてバックテストする。戻り値: (Portfolio, ticker別signal_frames)。"""
    config = config or BacktestConfig()
    signal_frames = compute_signal_frames(history, config.signal_config)

    open_wide = _wide(signal_frames, "Open")
    close_wide = _wide(signal_frames, "Close")
    sma25_wide = _wide(signal_frames, "sma25")
    raw_signal = _wide(signal_frames, "vcp_signal").fillna(False)

    # ブレイクアウト確認日の"翌"営業日始値でエントリー
    # bool dtypeの shift() は先頭行がNaNになりobject dtypeへ昇格するため、
    # fillna後に明示的にastype(bool)で戻す(そのままだとnumba側で型エラーになる)。
    entries = raw_signal.shift(1).fillna(False).astype(bool)

    ma_exit_raw = (close_wide < sma25_wide).fillna(False)
    ma_exit = ma_exit_raw.shift(1).fillna(False).astype(bool)

    if config.exit_rule == "stop_only":
        exits = pd.DataFrame(False, index=close_wide.index, columns=close_wide.columns)
        sl_stop = config.stop_loss_pct
        tp_stop = None
        size, size_type = _sizing(open_wide, entries, config)
    elif config.exit_rule == "ma25":
        exits = ma_exit
        sl_stop = config.stop_loss_pct
        tp_stop = None
        size, size_type = _sizing(open_wide, entries, config)
    else:  # partial_tp: 2レッグ(利確レッグ/トレールレッグ)に分割
        tp_cols = {f"{t}__tp": t for t in history}
        trail_cols = {f"{t}__trail": t for t in history}
        cols = list(tp_cols) + list(trail_cols)

        def dup(wide: pd.DataFrame) -> pd.DataFrame:
            return pd.concat({c: wide[src] for c, src in {**tp_cols, **trail_cols}.items()}, axis=1)[cols]

        open_wide2, close_wide2 = dup(open_wide), dup(close_wide)
        entries2 = dup(entries)
        exits2 = pd.DataFrame(False, index=entries2.index, columns=cols)
        for c, src in trail_cols.items():
            exits2[c] = ma_exit[src]

        sl_stop = pd.DataFrame(config.stop_loss_pct, index=entries2.index, columns=cols)
        tp_stop = pd.DataFrame(np.nan, index=entries2.index, columns=cols)
        for c in tp_cols:
            tp_stop[c] = config.take_profit_pct

        # equal_value/percent_riskとも「1トレード分」の半分ずつを各レッグに割り当てる
        half_config = BacktestConfig(**{**config.__dict__, "equal_trade_value": config.equal_trade_value / 2, "risk_pct": config.risk_pct / 2})
        size2, size_type = _sizing(open_wide2, entries2, half_config)

        pf = vbt.Portfolio.from_signals(
            close=close_wide2,
            open=open_wide2,
            entries=entries2,
            exits=exits2,
            sl_stop=sl_stop,
            tp_stop=tp_stop,
            size=size2,
            size_type=size_type,
            price=open_wide2,
            init_cash=config.initial_capital,
            fees=config.fees,
            cash_sharing=True,
            group_by=True,
            freq="1D",
        )
        return pf, signal_frames

    pf = vbt.Portfolio.from_signals(
        close=close_wide,
        open=open_wide,
        entries=entries,
        exits=exits,
        sl_stop=sl_stop,
        tp_stop=tp_stop,
        size=size,
        size_type=size_type,
        price=open_wide,
        init_cash=config.initial_capital,
        fees=config.fees,
        cash_sharing=True,
        group_by=True,
        freq="1D",
    )
    return pf, signal_frames


def _sizing(open_wide: pd.DataFrame, entries: pd.DataFrame, config: BacktestConfig) -> tuple[pd.DataFrame | float, str]:
    if config.sizing == "equal_value":
        return config.equal_trade_value, "value"
    risk_dollar = config.risk_pct * config.initial_capital
    return _entry_size_shares(open_wide, entries, risk_dollar, config.stop_loss_pct), "amount"
