"""テクニカル指標の計算。

Note:
- RS(相対力)は全市場ではなく「ウォッチリスト内でのパーセンタイル順位」で
  1〜99にスケールする(IBD RS Ratingと同じレンジ表記だが、母集団は全市場ではない)。
  設計上、全市場スクリーニングは対象外のため、この近似で妥協している。
- VCP候補判定はボラティリティ/出来高の収縮を機械的に検出する簡易版であり、
  実際のパターン形状(ピボット、ベース回数など)の最終判断はTradingViewでの
  目視に委ねる。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

# IBD RS Rating方式に倣い、直近1四半期(3ヶ月)を40%、以降3四半期を各20%で加重
RS_WEIGHTED_PERIODS: dict[int, float] = {63: 0.4, 126: 0.2, 189: 0.2, 252: 0.2}


def add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["sma50"] = df["Close"].rolling(50).mean()
    df["sma150"] = df["Close"].rolling(150).mean()
    df["sma200"] = df["Close"].rolling(200).mean()
    df["vol_avg10"] = df["Volume"].rolling(10).mean()
    df["vol_avg50"] = df["Volume"].rolling(50).mean()
    return df


def weighted_return(close: pd.Series) -> float | None:
    if len(close) < max(RS_WEIGHTED_PERIODS) + 1:
        return None
    latest = close.iloc[-1]
    if pd.isna(latest):
        return None
    score = 0.0
    for period, weight in RS_WEIGHTED_PERIODS.items():
        past = close.iloc[-1 - period]
        if pd.isna(past) or past <= 0:
            return None
        score += weight * (latest / past - 1)
    return score


def percentile_ratings(scores: dict[str, float | None]) -> dict[str, int | None]:
    """加重リターンを母集団内パーセンタイルで1〜99にスケールする。"""
    valid = {k: v for k, v in scores.items() if v is not None and pd.notna(v)}
    result: dict[str, int | None] = {k: None for k in scores}
    if not valid:
        return result
    ranked = pd.Series(valid).rank(pct=True, method="average")
    rating = (ranked * 98 + 1).round().astype(int)
    result.update(rating.to_dict())
    return result


def summarize_groups(
    weighted_returns: dict[str, float | None], group_of: dict[str, str | None]
) -> list[tuple[str, int | None, int]]:
    """グループ(セクター/業種)ごとの平均加重リターンをグループ間パーセンタイルでRS化する。
    戻り値は (グループ名, RSレーティング, 銘柄数) のリスト(レーティング降順)。"""
    group_scores: dict[str, list[float]] = {}
    group_counts: dict[str, int] = {}
    for ticker, ret in weighted_returns.items():
        group = group_of.get(ticker)
        if group is None:
            continue
        group_counts[group] = group_counts.get(group, 0) + 1
        if ret is not None:
            group_scores.setdefault(group, []).append(ret)

    group_avg = {g: float(np.mean(vals)) for g, vals in group_scores.items()}
    group_rating = percentile_ratings(group_avg)

    rows = [(group, group_rating.get(group), count) for group, count in group_counts.items()]
    rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0)))
    return rows


def group_ratings(
    weighted_returns: dict[str, float | None], group_of: dict[str, str | None]
) -> dict[str, int | None]:
    """各銘柄にそのセクター/業種のRSレーティングを割り当てる。"""
    rating_by_group = {group: rating for group, rating, _ in summarize_groups(weighted_returns, group_of)}
    return {ticker: rating_by_group.get(group_of.get(ticker)) for ticker in weighted_returns}


def pct_from_52w_high(df: pd.DataFrame) -> float | None:
    window = df["Close"].tail(252)
    if window.empty:
        return None
    return float(df["Close"].iloc[-1] / window.max() - 1) * 100


def pct_from_52w_low(df: pd.DataFrame) -> float | None:
    window = df["Close"].tail(252)
    if window.empty:
        return None
    return float(df["Close"].iloc[-1] / window.min() - 1) * 100


def relative_volume(df: pd.DataFrame) -> float | None:
    avg = df["vol_avg50"].iloc[-1]
    if pd.isna(avg) or avg == 0:
        return None
    return float(df["Volume"].iloc[-1] / avg)


def day_change_pct(df: pd.DataFrame) -> float | None:
    if len(df) < 2:
        return None
    prev, latest = df["Close"].iloc[-2], df["Close"].iloc[-1]
    if prev == 0:
        return None
    return float(latest / prev - 1) * 100


def sma200_trending_up(df: pd.DataFrame, lookback: int = 21) -> bool | None:
    """200DMAが約1ヶ月(21営業日)前より上向きか。"""
    sma200 = df["sma200"]
    if len(sma200) <= lookback:
        return None
    prev, latest = sma200.iloc[-1 - lookback], sma200.iloc[-1]
    if pd.isna(prev) or pd.isna(latest):
        return None
    return bool(latest > prev)


@dataclass
class TrendTemplate:
    price_above_150_200: bool
    sma150_above_sma200: bool
    sma200_trending_up: bool
    sma50_above_150_200: bool
    price_above_sma50: bool
    above_52w_low_30pct: bool
    within_52w_high_25pct: bool
    rs_rating_70plus: bool

    @property
    def pass_count(self) -> int:
        return sum(1 for v in asdict(self).values() if v is True)

    @property
    def passed(self) -> bool:
        return self.pass_count == 8


def evaluate_trend_template(df: pd.DataFrame, rs_rating: int | None) -> TrendTemplate | None:
    """Mark Minervini の Trend Template(8条件)判定。200日分のデータが無ければNone。"""
    latest = df.iloc[-1]
    sma50, sma150, sma200 = latest.get("sma50"), latest.get("sma150"), latest.get("sma200")
    if pd.isna(sma50) or pd.isna(sma150) or pd.isna(sma200):
        return None

    trending_up = sma200_trending_up(df)
    if trending_up is None:
        return None

    close = float(latest["Close"])
    dist_high = pct_from_52w_high(df)
    dist_low = pct_from_52w_low(df)

    return TrendTemplate(
        price_above_150_200=bool(close > sma150 and close > sma200),
        sma150_above_sma200=bool(sma150 > sma200),
        sma200_trending_up=trending_up,
        sma50_above_150_200=bool(sma50 > sma150 and sma50 > sma200),
        price_above_sma50=bool(close > sma50),
        above_52w_low_30pct=bool(dist_low is not None and dist_low >= 30),
        within_52w_high_25pct=bool(dist_high is not None and dist_high >= -25),
        rs_rating_70plus=bool(rs_rating is not None and rs_rating >= 70),
    )


def is_vcp_candidate(df: pd.DataFrame) -> bool | None:
    """VCP候補の簡易判定: 52週高値圏 + 50DMA上 + ボラティリティ収縮 + 出来高収縮。"""
    if len(df) < 60:
        return None
    latest = df.iloc[-1]
    sma50 = latest.get("sma50")
    if pd.isna(sma50):
        return None

    dist_high = pct_from_52w_high(df)
    if dist_high is None:
        return None
    near_high = dist_high >= -25
    above_sma50 = bool(latest["Close"] > sma50)

    returns = df["Close"].pct_change()
    vol10, vol50 = returns.tail(10).std(), returns.tail(50).std()
    if pd.isna(vol10) or pd.isna(vol50) or vol50 == 0:
        return None
    volatility_contracting = vol10 < vol50 * 0.7

    vol_avg10, vol_avg50 = latest.get("vol_avg10"), latest.get("vol_avg50")
    if pd.isna(vol_avg10) or pd.isna(vol_avg50) or vol_avg50 == 0:
        return None
    volume_contracting = vol_avg10 < vol_avg50 * 0.85

    return bool(near_high and above_sma50 and volatility_contracting and volume_contracting)
