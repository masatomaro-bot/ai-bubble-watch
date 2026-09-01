"""VCPシグナルのコード化(ステップ1〜3)。

pipeline/indicators.py は「最新1行」の判定用だが、こちらはバックテスト用に
全期間を一括でベクトル化して計算する(1銘柄あたり数千行 x 複数銘柄でも高速)。

先読みバイアス対策の方針(docs/BACKTEST.md 5節にも記載):
- 移動平均(SMAn)は当日終値を含む標準的な定義のまま使う(当日引け後に
  確定する値であり、シグナルも当日引け確定後の判定なので先読みではない)。
- ただし「出来高が平均の何倍か」を測る基準側の出来高平均(vol_avg_prior)は
  当日の出来高を含めない(shift(1)してから rolling)。当日自身の出来高
  スパイクが自分自身の基準値を膨らませてしまうと、閾値判定が歪むため。
- ピボット高値も当日を含めない(shift(1)してから rolling max)。当日の
  終値自身がピボットに含まれると「当日がピボットを上抜けたか」の判定が
  循環参照になってしまうため。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class SignalConfig:
    # ステップ1: トレンドテンプレート
    trend_up_lookback: int = 21  # 200DMAの上昇判定に使う遡り日数(約1ヶ月)
    above_low_pct: float = 30.0  # 52週安値からの上昇率(%)の下限
    within_high_pct: float = 25.0  # 52週高値からの下落率(%)の上限

    # ステップ2: ブレイクアウト
    pivot_lookback: int = 50  # ピボット高値を探す遡り日数
    volume_multiplier: float = 1.4  # ブレイクアウト日の出来高倍率の下限
    vol_avg_window: int = 50  # 出来高平均の計算窓

    # ステップ3: 収縮パターン(簡易近似)
    contraction_waves: int = 3  # 波の数(2〜3波を想定)
    contraction_wave_size: int = 13  # 1波あたりの日数(waves * wave_size が遡り幅)
    wave_shrink_ratio: float = 0.90  # 直近波の値幅は1つ前の波の何倍未満であるべきか
    volume_shrink_ratio: float = 0.85  # 直近波の平均出来高は最初の波の何倍未満であるべきか


def add_indicators(df: pd.DataFrame, config: SignalConfig | None = None) -> pd.DataFrame:
    """SMA・出来高平均・52週高安値などバックテストに必要な列を全期間分付与する。"""
    config = config or SignalConfig()
    df = df.copy()
    close = df["Close"]

    df["sma25"] = close.rolling(25).mean()
    df["sma50"] = close.rolling(50).mean()
    df["sma150"] = close.rolling(150).mean()
    df["sma200"] = close.rolling(200).mean()
    df["sma200_prior"] = df["sma200"].shift(config.trend_up_lookback)

    df["high_252"] = close.rolling(252).max()
    df["low_252"] = close.rolling(252).min()

    # 当日出来高は含めない(理由は本モジュールdocstring参照)
    df["vol_avg_prior"] = df["Volume"].shift(1).rolling(config.vol_avg_window).mean()
    # ピボット高値も当日を含めない
    df["pivot_high"] = close.shift(1).rolling(config.pivot_lookback).max()
    return df


def trend_template_signal(df: pd.DataFrame, config: SignalConfig | None = None) -> pd.Series:
    """Minervini トレンドテンプレート(本バックテストでは5条件版)。
    RS Rating条件は除外している(FFTYプール内相対力はプール自体が既に
    IBD 50スクリーニング済みのため意味が薄く、また過去時点の全銘柄横断
    ランクを再現するにはより広い母集団データが要るため、v1では見送り)。"""
    config = config or SignalConfig()
    close = df["Close"]

    cond_price_above_ma = (close > df["sma150"]) & (close > df["sma200"])
    cond_ma_stack = (df["sma50"] > df["sma150"]) & (df["sma50"] > df["sma200"])
    cond_sma200_up = df["sma200"] > df["sma200_prior"]
    cond_above_low = close >= df["low_252"] * (1 + config.above_low_pct / 100)
    cond_within_high = close >= df["high_252"] * (1 - config.within_high_pct / 100)

    return cond_price_above_ma & cond_ma_stack & cond_sma200_up & cond_above_low & cond_within_high


def breakout_signal(df: pd.DataFrame, config: SignalConfig | None = None) -> pd.Series:
    """ピボット高値の上抜け + 出来高急増(ステップ2)。"""
    config = config or SignalConfig()
    price_breakout = df["Close"] > df["pivot_high"]
    volume_surge = df["Volume"] >= df["vol_avg_prior"] * config.volume_multiplier
    return price_breakout & volume_surge


def contraction_signal(df: pd.DataFrame, config: SignalConfig | None = None) -> pd.Series:
    """収縮パターンの簡易検出(ステップ3)。

    ブレイクアウト候補日より前の期間を N波(デフォルト3波)に分割し、
    (1) 各波の値幅(高値安値レンジ/高値)がブレイクアウトに近い波ほど
        縮小しているか、(2) 直近波の平均出来高が最初の波より縮小しているか
    を判定する。実際のパターン形状(きれいなVCPかどうか)は目視判断に
    委ねる前提の近似フィルタ。"""
    config = config or SignalConfig()
    close, volume = df["Close"], df["Volume"]
    waves = config.contraction_waves
    wave_size = config.contraction_wave_size

    range_pct: list[pd.Series] = []
    vol_avg: list[pd.Series] = []
    for w in range(waves):
        shift_start = 1 + w * wave_size  # 当日を含めないよう shift(1) から開始
        wave_close = close.shift(shift_start).rolling(wave_size)
        wave_high, wave_low = wave_close.max(), wave_close.min()
        range_pct.append((wave_high - wave_low) / wave_high)
        vol_avg.append(volume.shift(shift_start).rolling(wave_size).mean())

    shrinking = pd.Series(True, index=df.index)
    for w in range(waves - 1):
        # index 0 = 直近波, index w+1 = 1つ前の波。直近波の値幅が縮小しているか
        shrinking &= range_pct[w] < range_pct[w + 1] * config.wave_shrink_ratio

    volume_contracting = vol_avg[0] < vol_avg[waves - 1] * config.volume_shrink_ratio

    valid = range_pct[-1].notna() & vol_avg[-1].notna()
    return shrinking & volume_contracting & valid


def vcp_entry_signal(df: pd.DataFrame, config: SignalConfig | None = None) -> pd.DataFrame:
    """ステップ1〜3をすべて満たした日を「シグナル発生日(ブレイクアウト確認日)」とする。
    戻り値: 元のdfに indicators + 各段階の真偽値列 + 総合判定'vcp_signal' を追加したもの。"""
    config = config or SignalConfig()
    df = add_indicators(df, config)
    df["trend_template"] = trend_template_signal(df, config)
    df["breakout"] = breakout_signal(df, config)
    df["contraction"] = contraction_signal(df, config)
    df["vcp_signal"] = df["trend_template"] & df["breakout"] & df["contraction"]
    return df
