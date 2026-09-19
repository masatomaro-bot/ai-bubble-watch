"""
market_climate.py
==================
「地合い」計測スクリプト。オニミネサイト (oniminetrade.com) のトップページで
公開されているロジックの説明文をもとに、同じ考え方を自前のデータ (yfinance) で
再現する。オニミネの正確な内部実装や母集団(全銘柄)とは異なるため、完全一致は
しない。どこが「オニミネの公開説明どおり」で、どこが「こちらの解釈・近似」かは
コード内コメントに明記した。

出力する指標:
  1. 売り抜け日数 / 失速日数  (NASDAQ総合 ^IXIC, S&P500 ^GSPC)
     -> オニミネのトップページ注記の定義をそのまま実装。
  2. 主要指数のステージ状態 (50/150/200日線に対する位置)
  3. セクター・ローテーション (11 SPDRセクターETF, RRG方式: RS-Ratio / RS-Momentum)
  4. テーマ・ローテーション (代理ETFによる近似, 「産業セクター月間パフォーマンス」相当)
     -> オニミネの正確な369テーマ分類とは別物。半導体・クリーンエネ・宇宙防衛・
        原子力など、テーマ型ETFで代用できる範囲のみを近似的にカバーする。
  5. 市場の幅 (ブレッドス): 新高値/新安値銘柄数、出来高ブレッド、52週高値/安値
     2%以内の比率
     -> 母集団は universe.get_broad_market_tickers() (iShares IWV/Russell3000
        ベース、数千銘柄規模) を優先し、取得できない場合のみS&P500(約500銘柄)
        に自動でフォールバックする。オニミネの「約4461銘柄」と完全一致する
        母集団ではないため、水準を直接比較しないこと。
  6. Market Leader (個別銘柄RSランキング):
     -> 本物のIBD RSレーティングは再現できないため、ブレッドス母集団内での
        トレーリング1年リターンの百分位を代替指標(proxy)として使う
        (ffty_screener.compute_rs_proxy_percentiles と同じ考え方)。

実行環境: GitHub Actions 等、外部ネットワークに出られる環境を想定。
このリポジトリのサンドボックス内では yfinance 等の外部通信がブロックされて
いたため、ここではロジックのみ実装し、実データでの動作確認は行っていない。
初回実行時は必ず手元 (ローカル or Actions) で出力を目視確認すること。
特に広域ユニバース(universe.py)は数千銘柄をyfinanceで取得するため、実行時間
やレート制限の影響を初回実行で必ず確認すること。
"""

from __future__ import annotations

import datetime as dt
import io
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from universe import get_broad_market_tickers
from yf_retry import download_with_retry

try:
    from ffty_screener import compute_rs_proxy_percentiles, compute_trend_template
except ImportError:  # pragma: no cover - フォールバック(単体実行時など)
    compute_rs_proxy_percentiles = None
    compute_trend_template = None

# ----------------------------------------------------------------------------
# 設定
# ----------------------------------------------------------------------------

NASDAQ_TICKER = "^IXIC"
SP500_TICKER = "^GSPC"
BENCHMARK_FOR_SECTORS = "SPY"

# 市場ストレス指標(Fable 5.1によるダッシュボードレビューで提案): 株価内部の
# ブレッドス指標だけでは「相場の外側」のストレス(恐怖・信用・選好の変化)が
# 見えないという指摘に対応。いずれも無料(yfinance)で取得できるETF/指数の
# 比率・水準で近似する。
#   VIX: 恐怖指数そのもの
#   HYG/IEF: ハイイールド社債(信用リスク選好)÷ 米国債(質への逃避先)
#   RSP/SPY: 均等加重 ÷ 時価総額加重。SPYが高値でもRSPが付いてこなければ
#            「一部の巨大株だけで持っている」痩せた相場を示唆する
#   IWM/SPY: 小型株 ÷ 大型株。リスク選好の強弱の代理
#   SOXX/SPY: 半導体 ÷ 大型株。景気敏感・グロースへのリスク選好の代理
# いずれも「この水準を超えたら危険」という断定的な閾値は置かない(根拠のない
# 閾値を作らないという方針のため)。値と直近10営業日の変化のみを示す。
VIX_TICKER = "^VIX"
STRESS_GAUGE_RATIO_TICKERS = {
    "credit_hyg_ief": ("HYG", "IEF"),
    "breadth_rsp_spy": ("RSP", "SPY"),
    "risk_appetite_iwm_spy": ("IWM", "SPY"),
    "semis_soxx_spy": ("SOXX", "SPY"),
}
STRESS_GAUGE_TICKERS = [VIX_TICKER] + sorted({t for pair in STRESS_GAUGE_RATIO_TICKERS.values() for t in pair})

SECTOR_ETFS = {
    "XLK": "情報技術",
    "XLF": "金融",
    "XLE": "エネルギー",
    "XLV": "ヘルスケア",
    "XLI": "資本財",
    "XLP": "生活必需品",
    "XLY": "一般消費財",
    "XLU": "公益事業",
    "XLB": "素材",
    "XLC": "通信サービス",
    "XLRE": "不動産",
}

# オニミネの「15の大分類テーマ」(産業セクター月間パフォーマンス)を、入手できる
# 範囲のテーマ型ETFで近似する。オニミネ側の正確な構成銘柄・分類基準・テーマ数
# (15)とは異なる代理指標であり、テーマ名・分類自体もこちらの解釈である点に
# 注意。GICS 11セクターETF(SECTOR_ETFS)と重複しないテーマ型/サブセクター型
# ETFのみを選んでいる。
THEME_ETFS = {
    "SOXX": "半導体",
    "XOP": "エネルギー(探鉱・生産)",
    "ICLN": "クリーンエネルギー",
    "IYT": "産業・輸送",
    "FINX": "フィンテック",
    "KRE": "地銀",
    "ITA": "宇宙・防衛",
    "PICK": "素材・鉱業",
    "IBB": "バイオテクノロジー",
    "BOTZ": "AI・ロボティクス",
    "SRVR": "デジタルインフラ(データセンター)",
    "URA": "原子力(ウラン)",
}

DIST_LOOKBACK_DAYS = 25       # オニミネ注記: 直近25営業日
DIST_EXPIRY_RALLY_PCT = 0.05  # オニミネ注記: 終値が当該日比+5%で除外
DIST_DOWN_THRESHOLD = -0.002  # オニミネ注記: 前日比-0.2%以下
STALL_UP_THRESHOLD = 0.002    # オニミネ注記: +0.2%未満の小幅高
# 「安値圏引け」の閾値はオニミネ側で具体的な数値が公開されていないため、
# ここでは「当日レンジの下位25%以内で引けた」を独自定義として採用する(要調整)。
STALL_CLOSE_NEAR_LOW_RATIO = 0.25

BREADTH_NEAR_PCT = 0.02  # 「52週高値/安値の2%以内」


# ----------------------------------------------------------------------------
# 1. 売り抜け日数 / 失速日数
# ----------------------------------------------------------------------------

@dataclass
class DistributionResult:
    distribution_days: int
    stalling_days: int
    distribution_dates: list = field(default_factory=list)
    stalling_dates: list = field(default_factory=list)


def compute_distribution_and_stalling_days(
    df: pd.DataFrame,
    lookback: int = DIST_LOOKBACK_DAYS,
    expiry_rally_pct: float = DIST_EXPIRY_RALLY_PCT,
) -> DistributionResult:
    """
    df: yfinance の日足データ (列: Open, High, Low, Close, Volume)。
        直近 lookback 営業日+アルファを含んでいること。
    """
    df = df.copy().dropna(subset=["Close", "Volume"])
    if len(df) < lookback + 2:
        raise ValueError("データ不足: lookback+2営業日以上のデータが必要")

    df["pct_change"] = df["Close"].pct_change()
    df["vol_increase"] = df["Volume"] > df["Volume"].shift(1)
    day_range = (df["High"] - df["Low"]).replace(0, np.nan)
    df["close_pos_in_range"] = (df["Close"] - df["Low"]) / day_range
    df["close_pos_in_range"] = df["close_pos_in_range"].fillna(0.5)

    recent = df.iloc[-lookback:]
    latest_close = df["Close"].iloc[-1]

    dist_mask = (recent["pct_change"] <= DIST_DOWN_THRESHOLD) & recent["vol_increase"]
    stall_mask = (
        (recent["pct_change"] >= 0)
        & (recent["pct_change"] < STALL_UP_THRESHOLD)
        & recent["vol_increase"]
        & (recent["close_pos_in_range"] <= STALL_CLOSE_NEAR_LOW_RATIO)
    )

    # +5%ラリーによる除外 (当日終値 -> 直近終値が+5%以上なら無効化)
    def not_expired_by_rally(day_close: float) -> bool:
        return latest_close < day_close * (1 + expiry_rally_pct)

    dist_dates = [
        d for d, ok in zip(recent.index[dist_mask], recent.loc[dist_mask, "Close"].apply(not_expired_by_rally))
        if ok
    ]
    stall_dates = [
        d for d, ok in zip(recent.index[stall_mask], recent.loc[stall_mask, "Close"].apply(not_expired_by_rally))
        if ok
    ]

    return DistributionResult(
        distribution_days=len(dist_dates),
        stalling_days=len(stall_dates),
        distribution_dates=[d.strftime("%Y-%m-%d") for d in dist_dates],
        stalling_dates=[d.strftime("%Y-%m-%d") for d in stall_dates],
    )


# ----------------------------------------------------------------------------
# 1.5. フォロースルー・デイ(FTD)によるO'Neil/IBD式3状態判定
# ----------------------------------------------------------------------------
#
# O'Neilおよび後続のIBD(Investor's Business Daily)が公開している「市場の方向性」
# 判定の考え方をできるだけそのまま実装したもの。オニミネの非公開ロジック(セクター
# 4分類の多数決)とは別の、根拠が公開されている判定手法として位置づける。
#
# 定義(原典/IBDの一般的な説明に準拠):
#   - 「反発の初日(Day 1)」: 下落が続いた後、指数が前日比プラスで引けた日
#   - Day 1から数えてDay 4以降のいずれかの日に、指数が大幅高(+1.25%以上)かつ
#     前日より出来高が多い日が出れば「フォロースルー・デイ(FTD)」となり、
#     そこで新しい上昇トレンドが「確認(confirmed)」される
#   - FTD成立前に、指数が反発開始時の安値を終値で下回ったら、その反発の試みは
#     失敗とみなす
#   - 上昇トレンド確認後も、売り抜け日数(distribution days)が直近25営業日で
#     一定数を超えると「圧力下の上昇トレンド」に格下げされる
#
# 以下は自前の簡略化(オニミネや教科書の完全な再現ではない):
#   - 「安値」の検出は直近ウィンドウ内の終値最小値という単純な定義とし、複数回の
#     反発失敗〜再安値パターンは限られた回数だけ再探索する(MAX_RETRY_ON_UNDERCUT)
#   - FTD成立を待つ期間はDay 4〜Day 10とする(流派によりDay 25まで許容する説もある)
#   - 「反発初日」の検出は安値の後の最初の陽線という単純な定義とする

FTD_GAIN_THRESHOLD = 0.0125       # フォロースルー・デイの上昇率しきい値 (+1.25%)
FTD_WINDOW_MIN_DAY = 4             # FTDが成立しうる最短日(反発Day4から)
FTD_WINDOW_MAX_DAY = 10            # FTDを探す最長日(反発Day10まで)
RALLY_LOW_LOOKBACK_DAYS = 40       # 直近安値を探す遡り日数
RALLY_ATTEMPT_MAX_SEARCH_DAYS = 15 # 安値から反発初日(陽線)を探す最長日数
DISTRIBUTION_PRESSURE_THRESHOLD = 5  # 直近25営業日の売り抜け日数がこれ以上で「圧力下」
MAX_RETRY_ON_UNDERCUT = 2          # 反発失敗(安値割れ)時に安値を探し直す最大回数


@dataclass
class TrendStateResult:
    state: str  # "confirmed_uptrend" | "uptrend_under_pressure" | "correction" | "不明"
    rally_low_date: str | None = None
    rally_day1_date: str | None = None
    ftd_date: str | None = None
    days_since_ftd: int | None = None
    distribution_days_recent: int | None = None
    note: str = ""


def _find_rally_low_and_day1(close: pd.Series, pct: pd.Series, search_start_idx: int, n: int):
    """search_start_idx以降のウィンドウ内で直近安値と、その後最初の陽線
    (反発初日)のインデックスを探す。反発の兆しがまだなければ day1=None。"""
    window_end = min(search_start_idx + RALLY_LOW_LOOKBACK_DAYS, n)
    if search_start_idx >= window_end:
        return None, None
    window = close.iloc[search_start_idx:window_end]
    low_idx = search_start_idx + int(np.asarray(window.values).argmin())

    for j in range(low_idx + 1, min(low_idx + 1 + RALLY_ATTEMPT_MAX_SEARCH_DAYS, n)):
        if pct.iloc[j] > 0:
            return low_idx, j
    return low_idx, None


def compute_trend_state(df: pd.DataFrame) -> TrendStateResult:
    """df: yfinanceの日足データ(列: Close, Volume)。2年分程度を想定。"""
    close = df["Close"].dropna()
    volume = df["Volume"].dropna()
    common_idx = close.index.intersection(volume.index)
    close = close.loc[common_idx]
    volume = volume.loc[common_idx]
    n = len(close)

    min_len = RALLY_LOW_LOOKBACK_DAYS + FTD_WINDOW_MAX_DAY
    if n < min_len:
        return TrendStateResult(state="不明", note=f"データ不足(必要{min_len}営業日、実際{n}営業日)")

    pct = close.pct_change()

    search_start = max(0, n - RALLY_LOW_LOOKBACK_DAYS - FTD_WINDOW_MAX_DAY - RALLY_ATTEMPT_MAX_SEARCH_DAYS)

    low_idx = day1_idx = ftd_idx = None
    for _attempt in range(MAX_RETRY_ON_UNDERCUT + 1):
        low_idx, day1_idx = _find_rally_low_and_day1(close, pct, search_start, n)
        if day1_idx is None:
            break

        rally_low = close.iloc[low_idx]
        undercut_idx = None
        ftd_idx = None
        window_days = range(day1_idx, min(day1_idx + FTD_WINDOW_MAX_DAY, n))
        for day_num, j in enumerate(window_days, start=1):
            if close.iloc[j] < rally_low:
                undercut_idx = j
                break
            if day_num >= FTD_WINDOW_MIN_DAY:
                vol_up = volume.iloc[j] > volume.iloc[j - 1]
                if pct.iloc[j] >= FTD_GAIN_THRESHOLD and vol_up:
                    ftd_idx = j
                    break

        if ftd_idx is not None:
            break
        if undercut_idx is not None:
            search_start = undercut_idx + 1
            continue
        break  # ウィンドウ内でFTDも失敗も確定しなかった(直近すぎて判定保留)

    if ftd_idx is None:
        return TrendStateResult(
            state="correction",
            rally_low_date=close.index[low_idx].strftime("%Y-%m-%d") if low_idx is not None else None,
            rally_day1_date=close.index[day1_idx].strftime("%Y-%m-%d") if day1_idx is not None else None,
            note="直近でフォロースルー・デイが確認できていない",
        )

    dist_result = compute_distribution_and_stalling_days(df.loc[common_idx])
    distribution_days_recent = dist_result.distribution_days
    state = (
        "uptrend_under_pressure"
        if distribution_days_recent >= DISTRIBUTION_PRESSURE_THRESHOLD
        else "confirmed_uptrend"
    )

    return TrendStateResult(
        state=state,
        rally_low_date=close.index[low_idx].strftime("%Y-%m-%d"),
        rally_day1_date=close.index[day1_idx].strftime("%Y-%m-%d"),
        ftd_date=close.index[ftd_idx].strftime("%Y-%m-%d"),
        days_since_ftd=n - 1 - ftd_idx,
        distribution_days_recent=distribution_days_recent,
    )


def combine_trend_states(nasdaq_state: str, sp500_state: str) -> str:
    """NASDAQ・S&P500いずれか弱い方に合わせる単純な統合ルール(自前設計)。"""
    states = {nasdaq_state, sp500_state}
    if "correction" in states:
        return "correction"
    if "uptrend_under_pressure" in states:
        return "uptrend_under_pressure"
    if states == {"confirmed_uptrend"}:
        return "confirmed_uptrend"
    return "不明"


# ----------------------------------------------------------------------------
# 2. 指数ステージ状態
# ----------------------------------------------------------------------------

def compute_index_stage(df: pd.DataFrame) -> dict:
    close = df["Close"]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma150 = close.rolling(150).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    price = close.iloc[-1]
    sma200_1m_ago = close.rolling(200).mean().iloc[-22] if len(close) >= 222 else np.nan
    high_52w = close.dropna().tail(252).max()
    pct_below_52w_high = (
        round(float(100 * (high_52w - price) / high_52w), 2) if pd.notna(high_52w) and high_52w else None
    )

    return {
        "price": round(float(price), 2),
        "sma50": round(float(sma50), 2) if pd.notna(sma50) else None,
        "sma150": round(float(sma150), 2) if pd.notna(sma150) else None,
        "sma200": round(float(sma200), 2) if pd.notna(sma200) else None,
        "above_sma50": bool(price > sma50) if pd.notna(sma50) else None,
        "above_sma150": bool(price > sma150) if pd.notna(sma150) else None,
        "above_sma200": bool(price > sma200) if pd.notna(sma200) else None,
        "sma200_rising": bool(sma200 > sma200_1m_ago) if pd.notna(sma200_1m_ago) else None,
        "pct_below_52w_high": pct_below_52w_high,
    }


# ----------------------------------------------------------------------------
# 3. セクター・ローテーション (簡易RRG: RS-Ratio / RS-Momentum)
# ----------------------------------------------------------------------------

def compute_sector_rrg(
    sector_close: pd.Series,
    benchmark_close: pd.Series,
    rs_smooth_window: int = 10,
    mom_window: int = 5,
) -> dict:
    """
    JdK RRG方式の簡易版。
      RS       = sector_close / benchmark_close
      RS-Ratio = RSをrs_smooth_window期間で平滑化し、直近1年のz-scoreを
                 100を中心に正規化したもの
      RS-Mom   = RS-Ratioのmom_window期間変化率を同様に正規化したもの
    厳密な定義(相対力研究所のオリジナル計算式)とは異なる簡易近似である点に注意。
    """
    rs = (sector_close / benchmark_close).dropna()
    rs_smooth = rs.rolling(rs_smooth_window).mean().dropna()

    def normalize_to_100(series: pd.Series) -> pd.Series:
        window = series.tail(252) if len(series) > 252 else series
        mean, std = window.mean(), window.std()
        if std == 0 or pd.isna(std):
            return series * 0 + 100
        return 100 + (series - mean) / std

    rs_ratio = normalize_to_100(rs_smooth)
    rs_mom_raw = rs_ratio.pct_change(mom_window)
    rs_momentum = normalize_to_100(rs_mom_raw.dropna())

    latest_ratio = float(rs_ratio.iloc[-1]) if len(rs_ratio) else None
    latest_mom = float(rs_momentum.iloc[-1]) if len(rs_momentum) else None

    if latest_ratio is None or latest_mom is None:
        quadrant = "不明"
    elif latest_ratio >= 100 and latest_mom >= 100:
        quadrant = "主導"
    elif latest_ratio >= 100 and latest_mom < 100:
        quadrant = "鈍化"
    elif latest_ratio < 100 and latest_mom < 100:
        quadrant = "遅行"
    else:
        quadrant = "改善"

    return {
        "rs_ratio": round(latest_ratio, 2) if latest_ratio is not None else None,
        "rs_momentum": round(latest_mom, 2) if latest_mom is not None else None,
        "quadrant": quadrant,
    }


# ----------------------------------------------------------------------------
# 4. 市場の幅 (ブレッドス)
# ----------------------------------------------------------------------------

def compute_breadth_near_52w(price_frames: dict) -> dict:
    """
    price_frames: {ticker: DataFrame(Close, ...)} の辞書。約1年分のデータを想定。
    52週高値/安値の2%以内にいる銘柄の比率を計算する (母集団はここに渡した銘柄群)。
    """
    near_high = 0
    near_low = 0
    valid = 0
    for _ticker, df in price_frames.items():
        close = df["Close"].dropna()
        if len(close) < 200:
            continue
        high_52w = close.tail(252).max()
        low_52w = close.tail(252).min()
        last = close.iloc[-1]
        valid += 1
        if last >= high_52w * (1 - BREADTH_NEAR_PCT):
            near_high += 1
        if last <= low_52w * (1 + BREADTH_NEAR_PCT):
            near_low += 1

    return {
        "universe_size": valid,
        "near_52w_high": near_high,
        "near_52w_low": near_low,
        "near_high_pct": round(100 * near_high / valid, 1) if valid else None,
        "near_low_pct": round(100 * near_low / valid, 1) if valid else None,
    }


def compute_breadth_extended(price_frames: dict) -> dict:
    """
    厳密な新高値/新安値銘柄数、値上がり/値下がり銘柄数、出来高ブレッド
    (値上がり銘柄の出来高が全体に占める比率)を計算する。
    オニミネの「市場の灯」(新高値/新安値の推移)、「出来高ブレッド」表示に
    相当する自前実装。母集団はここに渡した銘柄群次第で、オニミネ側の
    「約4461銘柄」と完全一致するものではない。
    """
    new_highs = 0
    new_lows = 0
    advancers = 0
    decliners = 0
    unchanged = 0
    up_volume = 0.0
    down_volume = 0.0
    valid = 0

    for _ticker, df in price_frames.items():
        close = df["Close"].dropna()
        volume = df["Volume"].dropna()
        if len(close) < 200 or len(volume) < 2:
            continue

        last = close.iloc[-1]
        prev = close.iloc[-2]
        high_52w = close.tail(252).max()
        low_52w = close.tail(252).min()
        vol_today = volume.iloc[-1]

        valid += 1
        if last >= high_52w:
            new_highs += 1
        if last <= low_52w:
            new_lows += 1

        if last > prev:
            advancers += 1
            up_volume += float(vol_today)
        elif last < prev:
            decliners += 1
            down_volume += float(vol_today)
        else:
            unchanged += 1

    total_volume = up_volume + down_volume
    return {
        "universe_size": valid,
        "new_52w_highs": new_highs,
        "new_52w_lows": new_lows,
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "up_volume": up_volume,
        "down_volume": down_volume,
        "up_volume_pct": round(100 * up_volume / total_volume, 1) if total_volume else None,
    }


# ----------------------------------------------------------------------------
# 4.5. 広域ユニバース全体のテクニカル比率 (200日線上比率・トレンドテンプレート合格率)
# ----------------------------------------------------------------------------
#
# S&P500のような一部指数ではなく、ブレッドス計算に使っている広域ユニバース
# (数千銘柄)全体を対象にした比率。「何%の銘柄が上昇トレンドの型を満たしているか」
# という、O'Neil/ミネルヴィニ流の地合い判断でよく使われる指標。
# トレンドテンプレート合格の8条件目(RSレーティング>=70)は、ffty_screener.py と
# 同様に「このユニバース内でのトレーリング1年リターン百分位」を代替指標として使う
# (本物のIBD RSレーティングとは数値の意味が異なる)。

TREND_TEMPLATE_RS_THRESHOLD = 70  # RS百分位proxyがこの値以上で8条件目を合格扱いにする


def compute_broad_universe_technicals(price_frames: dict, rs_percentiles: dict) -> dict:
    above_50 = above_200 = valid = 0
    template_pass_all8 = template_total = 0
    passing_tickers: list[str] = []

    for ticker, df in price_frames.items():
        close = df["Close"].dropna()
        if len(close) < 200:
            continue
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        if pd.isna(sma50) or pd.isna(sma200):
            continue
        last = close.iloc[-1]

        valid += 1
        if last > sma50:
            above_50 += 1
        if last > sma200:
            above_200 += 1

        if compute_trend_template is None:
            continue
        tmpl = compute_trend_template(df)
        if "error" in tmpl:
            continue
        template_total += 1
        rs_pct = rs_percentiles.get(ticker)
        c8_pass = rs_pct is not None and rs_pct >= TREND_TEMPLATE_RS_THRESHOLD
        if tmpl.get("pass_count_without_rs") == 7 and c8_pass:
            template_pass_all8 += 1
            passing_tickers.append(ticker)

    return {
        "universe_size": valid,
        "pct_above_50dma": round(100 * above_50 / valid, 1) if valid else None,
        "pct_above_200dma": round(100 * above_200 / valid, 1) if valid else None,
        "trend_template_pass_count": template_pass_all8,
        "trend_template_pass_rate_pct": (
            round(100 * template_pass_all8 / template_total, 1) if template_total else None
        ),
        "trend_template_pass_tickers": passing_tickers,
    }


# ----------------------------------------------------------------------------
# 4.6. 市場ストレス指標 (VIX・信用・均等加重・リスク選好)
# ----------------------------------------------------------------------------

STRESS_GAUGE_CHANGE_WINDOW = 10  # 直近何営業日の変化を見るか


def compute_stress_gauges(gauge_hist: dict) -> dict:
    """VIX水準・信用(HYG/IEF)・広さ(RSP/SPY)・小型株選好(IWM/SPY)・
    半導体選好(SOXX/SPY)を計算する。「この水準を超えたら危険」という
    断定的な閾値は置かず、値と直近STRESS_GAUGE_CHANGE_WINDOW営業日の
    変化のみを返す(解釈はダッシュボード側の注記に委ねる)。"""

    def close_of(ticker):
        df = gauge_hist.get(ticker)
        if df is None or df.empty:
            return None
        close = df["Close"].dropna()
        return close if not close.empty else None

    def level_and_change(ticker):
        close = close_of(ticker)
        if close is None:
            return None, None
        level = round(float(close.iloc[-1]), 2)
        change = (
            round(float(close.iloc[-1] - close.iloc[-STRESS_GAUGE_CHANGE_WINDOW]), 2)
            if len(close) > STRESS_GAUGE_CHANGE_WINDOW else None
        )
        return level, change

    def ratio_and_change_pct(numer_ticker, denom_ticker):
        numer, denom = close_of(numer_ticker), close_of(denom_ticker)
        if numer is None or denom is None:
            return None, None
        ratio = (numer / denom).dropna()
        if ratio.empty:
            return None, None
        last = round(float(ratio.iloc[-1]), 4)
        change_pct = (
            round(100 * (ratio.iloc[-1] / ratio.iloc[-STRESS_GAUGE_CHANGE_WINDOW] - 1), 2)
            if len(ratio) > STRESS_GAUGE_CHANGE_WINDOW else None
        )
        return last, change_pct

    vix_level, vix_change = level_and_change(VIX_TICKER)
    result = {
        "vix": {"level": vix_level, "change_10d": vix_change},
    }
    for key, (numer, denom) in STRESS_GAUGE_RATIO_TICKERS.items():
        ratio, change_pct = ratio_and_change_pct(numer, denom)
        result[key] = {"ratio": ratio, "change_10d_pct": change_pct}
    return result


# ----------------------------------------------------------------------------
# 5. セクター温度感の多数決 (RISK-ON/RISK-OFF 判定)
# ----------------------------------------------------------------------------
#
# オニミネは「11セクターを上昇/買い集め/中立/調整の4分類にし、多数決で本日の
# 地合いを判定する」という考え方を公開しているが、各分類の具体的な閾値
# (どこからが「調整」か等)は非公開。以下は完全に自前の解釈・設計であり、
# オニミネの実際の判定と一致する保証はない。
#   - 上昇   : 価格が50日線・200日線の両方より上 かつ 相対力(RS)が直近上昇中
#   - 調整   : 価格が50日線・200日線の両方より下 かつ 相対力(RS)が直近下降中
#   - 買い集め: 価格はまだ弱い(50/200日線の一方または両方より下)が、相対力は
#              直近上昇に転じている ("資金が入り始めている"という解釈)
#   - 中立   : 上記のいずれにも当てはまらない状態
RS_TREND_WINDOW = 20  # 相対力(RS)の直近変化を見る期間(営業日)


def classify_sector_temperature(sector_close: pd.Series, benchmark_close: pd.Series) -> str:
    if len(sector_close) < 200:
        return "不明"

    price = sector_close.iloc[-1]
    sma50 = sector_close.rolling(50).mean().iloc[-1]
    sma200 = sector_close.rolling(200).mean().iloc[-1]
    if pd.isna(sma50) or pd.isna(sma200):
        return "不明"

    rs = (sector_close / benchmark_close).dropna()
    if len(rs) <= RS_TREND_WINDOW:
        return "不明"
    rs_change = rs.pct_change(RS_TREND_WINDOW).iloc[-1]
    if pd.isna(rs_change):
        return "不明"

    above_both = price > sma50 and price > sma200
    below_both = price < sma50 and price < sma200
    rs_rising = rs_change > 0

    if above_both and rs_rising:
        return "上昇"
    if below_both and not rs_rising:
        return "調整"
    if rs_rising and not above_both:
        return "買い集め"
    return "中立"


def majority_vote_market_regime(sector_temperatures: dict) -> dict:
    """セクター温度感の多数決でRISK-ON/RISK-OFF/MIXEDを判定する。
    sector_temperatures: {etf: "上昇"|"買い集め"|"中立"|"調整"|"不明"}
    """
    from collections import Counter

    valid = {k: v for k, v in sector_temperatures.items() if v != "不明"}
    counts = Counter(valid.values())
    total = len(valid)

    if total == 0:
        return {"counts": {}, "total": 0, "judgement": "不明"}

    risk_off_votes = counts.get("調整", 0)
    risk_on_votes = counts.get("上昇", 0) + counts.get("買い集め", 0)

    if risk_off_votes > total / 2:
        judgement = "RISK-OFF"
    elif risk_on_votes > total / 2:
        judgement = "RISK-ON"
    else:
        judgement = "MIXED"

    return {"counts": dict(counts), "total": total, "judgement": judgement}


# ----------------------------------------------------------------------------
# データ取得ヘルパー
# ----------------------------------------------------------------------------

def get_sp500_tickers() -> list:
    """Wikipediaの一覧ページから S&P500 構成銘柄ティッカーを取得する。
    (ブレッドス計算の母集団として使用。取得失敗時は空リストを返す)

    User-Agentを付けずにリクエストすると403 Forbiddenで弾かれることがある
    ため、ブラウザ相当のUser-Agentを明示して取得する。
    """
    import urllib.request

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read()
        tables = pd.read_html(io.BytesIO(html))
        tickers = tables[0]["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
        return tickers
    except Exception as e:  # noqa: BLE001
        print(f"[warn] S&P500銘柄リスト取得失敗: {e}", file=sys.stderr)
        return []


DOWNLOAD_HISTORY_MAX_RETRIES = 3
DOWNLOAD_HISTORY_RETRY_SLEEP_SEC = 3.0


def _extract_ticker_frames(raw, tickers: list) -> dict:
    result = {}
    if not isinstance(raw.columns, pd.MultiIndex):
        result[tickers[0]] = raw
        return result
    for t in tickers:
        try:
            result[t] = raw[t].dropna(how="all")
        except (KeyError, Exception):  # noqa: BLE001
            continue
    return result


def download_history(tickers: list, period: str = "2y", missing_tolerance: float = 0.0) -> dict:
    """複数ティッカーをまとめて取得し、{ticker: DataFrame} の辞書で返す。
    yfinanceの"database is locked"エラー対策でリトライ付き(yf_retry.py参照)。
    group_by="ticker"を指定しても、ティッカーが1件だけの場合に列がMultiIndexに
    なるかどうかはyfinanceのバージョンによって挙動が異なる(実際に1.7.0系で
    MultiIndexになることを確認済み)。ティッカー数で分岐せず、返ってきた列が
    実際にMultiIndexかどうかで判定する。

    2026-09-15の実機実行で判明: 複数ティッカーを一括取得する際、一部の
    ティッカーだけ"database is locked"で失敗することがあるが、yfinanceは
    これを例外として送出せず、"N Failed download"という警告を出すだけで
    該当ティッカーのデータが欠損したまま処理を続けてしまう。そのため
    yf_retry.download_with_retry(例外ベースのリトライ)だけでは検知できない。
    ここでは取得後に各ティッカーのCloseが実際に存在するかを確認し、
    不足していれば取得全体をリトライする。

    missing_tolerance: 欠損許容率(0.0〜1.0)。指数(2銘柄)のように1件欠損が
    致命的な呼び出しでは既定の0.0(1件でも欠損したら再取得)のままでよいが、
    広域ユニバースを数百件ずつチャンク取得する場合、数百件中の数件が上場廃止・
    薄商いで恒常的に欠損するのは正常であり、その都度チャンク全体を再取得すると
    Yahoo側への負荷が増えて逆にレート制限を誘発しかねない(母集団サイズが
    5433→4280→4095と日によって大きく変動した一因と考えられる)。呼び出し側で
    チャンク単位の許容率を指定できるようにする。"""
    if not tickers:
        return {}
    result: dict = {}
    for attempt in range(DOWNLOAD_HISTORY_MAX_RETRIES):
        raw = download_with_retry(tickers, period=period, interval="1d", group_by="ticker",
                                   auto_adjust=False, progress=False, threads=True)
        result = _extract_ticker_frames(raw, tickers)
        missing = [
            t for t in tickers
            if t not in result or result[t].empty or result[t]["Close"].dropna().empty
        ]
        if len(missing) <= missing_tolerance * len(tickers):
            return result
        if attempt < DOWNLOAD_HISTORY_MAX_RETRIES - 1:
            sleep_sec = DOWNLOAD_HISTORY_RETRY_SLEEP_SEC * (attempt + 1)
            missing_preview = missing[:10] if len(missing) > 10 else missing
            print(
                f"[warn] download_history: {len(missing)}/{len(tickers)}件のデータ取得に失敗 "
                f"({missing_preview}{'...' if len(missing) > 10 else ''})、"
                f"{sleep_sec:.0f}秒後に取得全体をリトライ ({attempt + 1}/{DOWNLOAD_HISTORY_MAX_RETRIES})",
                file=sys.stderr,
            )
            time.sleep(sleep_sec)
    return result


# 広域ユニバース(数千銘柄)を一度にyf.downloadへ渡すと、タイムアウトや
# 部分的な取得失敗が起きやすいため、chunk_size件ずつに分けて取得する。
# 各チャンクの間に小休止を入れ、Yahoo Finance側への負荷を抑える
# (実際にどの程度の待機が必要かはこのサンドボックスでは検証できておらず、
#  初回実行時にレート制限(429など)が出ないか確認すること)。
BREADTH_DOWNLOAD_CHUNK_SIZE = 250
BREADTH_DOWNLOAD_SLEEP_SEC = 1.0


CHUNK_MISSING_TOLERANCE = 0.05


def download_history_chunked(
    tickers: list,
    period: str = "1y",
    chunk_size: int = BREADTH_DOWNLOAD_CHUNK_SIZE,
    sleep_sec: float = BREADTH_DOWNLOAD_SLEEP_SEC,
) -> dict:
    result: dict = {}
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        try:
            result.update(download_history(chunk, period=period, missing_tolerance=CHUNK_MISSING_TOLERANCE))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] チャンク取得失敗 ({i}〜{i + len(chunk)}件目): {e}", file=sys.stderr)
        if i + chunk_size < len(tickers) and sleep_sec:
            time.sleep(sleep_sec)
    print(f"[info] download_history_chunked: 要求{len(tickers)}件中{len(result)}件取得成功", file=sys.stderr)
    return result


def get_breadth_universe(universe: str, max_tickers: int | None = None) -> tuple[list, str]:
    """ブレッドス計算用のティッカーユニバースを返す。

    universe="broad": iShares IWV(Russell3000)ベースの広域ユニバースを試み、
      取得できなければ自動的にS&P500にフォールバックする。
    universe="sp500": 最初からS&P500のみを使う(軽量・お試し用)。
    """
    if universe == "broad":
        tickers, source = get_broad_market_tickers(max_tickers=max_tickers)
        if tickers:
            return tickers, source
        print("[warn] 広域ユニバース取得失敗のためS&P500にフォールバック", file=sys.stderr)

    from universe import sample_tickers

    tickers = get_sp500_tickers()
    return sample_tickers(tickers, max_tickers), "sp500"


# ----------------------------------------------------------------------------
# メイン処理
# ----------------------------------------------------------------------------

MARKET_LEADER_TOP_N = 20  # Market Leader (RSランキング上位) の出力件数
TREND_TEMPLATE_LEADER_TOP_N = 20  # トレンドテンプレート合格銘柄のRS上位表の出力件数

# Market Leadersの「明らかにデータ異常・実用性の低い銘柄」を除外するための
# 品質フィルタ。2026-09-15/09-16の実機実行で、NFE(前日比+3906%)・GTBP
# (1ヶ月+2815%)のような、株式分割の未調整(auto_adjust=False)や超低位株
# 特有の異常値と思われる銘柄が上位に混入することを確認したための対応。
MARKET_LEADER_MIN_PRICE = 5.0  # 未満はいわゆるペニー株として除外
MARKET_LEADER_MIN_AVG_DOLLAR_VOLUME = 1_000_000.0  # 直近20営業日平均の概算売買代金(ドル)下限
MARKET_LEADER_MAX_ABS_DAY_CHANGE_PCT = 50.0  # これを超える前日比は分割未調整等のデータ異常とみなす


def select_market_leaders(price_frames: dict, percentiles: dict, top_n: int = MARKET_LEADER_TOP_N) -> list[dict]:
    """RS百分位の高い順に、品質フィルタ(最低株価・最低売買代金・前日比の
    異常値除外)を通過した銘柄をtop_n件選ぶ。フィルタで弾かれた分は
    後続の候補で埋め合わせる(単純に上位top_n件を切ってからフィルタすると
    件数が不足するため)。"""
    leaders: list[dict] = []
    ranked = sorted(percentiles.items(), key=lambda kv: kv[1], reverse=True)
    for ticker, pct in ranked:
        if len(leaders) >= top_n:
            break
        df = price_frames[ticker]
        close = df["Close"].dropna()
        if len(close) < 2:
            continue
        if close.iloc[-1] < MARKET_LEADER_MIN_PRICE:
            continue
        recent = df.tail(20)
        avg_dollar_volume = (recent["Close"] * recent["Volume"]).mean()
        if pd.isna(avg_dollar_volume) or avg_dollar_volume < MARKET_LEADER_MIN_AVG_DOLLAR_VOLUME:
            continue
        day_change = round(100 * (close.iloc[-1] / close.iloc[-2] - 1), 2)
        if abs(day_change) > MARKET_LEADER_MAX_ABS_DAY_CHANGE_PCT:
            continue
        one_month = round(100 * (close.iloc[-1] / close.iloc[-22] - 1), 2) if len(close) > 22 else None
        three_month = round(100 * (close.iloc[-1] / close.iloc[-63] - 1), 2) if len(close) > 63 else None
        sma50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None
        above_sma50 = bool(close.iloc[-1] > sma50) if sma50 is not None and pd.notna(sma50) else None
        leaders.append({
            "ticker": ticker,
            "rs_percentile": pct,
            "day_change_pct": day_change,
            "one_month_pct": one_month,
            "three_month_pct": three_month,
            "above_sma50": above_sma50,
        })
    return leaders


def build_opportunity_universe(price_frames: dict, percentiles: dict, date: str, source: str) -> dict:
    """Reuse downloaded bars; retain every quality-passing row, not only top 20.

    Drop symbols whose most recent usable close is not the snapshot trading date.
    This is a research universe, not a fundamental or liquidity suitability rating.
    """
    rows = select_market_leaders(price_frames, percentiles, top_n=len(percentiles))
    current = []
    for row in rows:
        close = price_frames[row["ticker"]]["Close"].dropna()
        observed = close.index[-1].date().isoformat()
        if observed == date:
            current.append({**row, "observed_date": observed})
    return {
        "method": "broad-close-return-252-percentile-v1",
        "source": source,
        "ranked_count": len(percentiles),
        "eligible_count": len(current),
        "excluded_stale_count": len(rows) - len(current),
        "filters": {
            "min_price_usd": MARKET_LEADER_MIN_PRICE,
            "min_avg_dollar_volume_20d": MARKET_LEADER_MIN_AVG_DOLLAR_VOLUME,
            "max_abs_day_change_pct": MARKET_LEADER_MAX_ABS_DAY_CHANGE_PCT,
        },
        "rows": current,
    }


# ----------------------------------------------------------------------------
# 警戒チェックリスト(既知の「崩れの前兆」パターンの機械判定)
# ----------------------------------------------------------------------------
#
# Fable 5.1によるダッシュボードレビューで、「下落を予測することはできないが、
# 指数がまだ高値圏なのに内部(ブレッドス・リーダー株)が先に痩せていく」という
# 乖離パターンは崩れの前によく見られる、との指摘があった。ここではその種の
# 既知パターンを機械的に判定するが、あくまで「参考情報」であり、点灯した
# からといって必ず下落するわけではない。閾値はすべて自前設計で、有効性は
# backtest_trend_state.py同様、別途検証が必要(未検証)。

WARNING_NEAR_HIGH_PCT = 3.0  # 52週高値からこの%以内を「高値圏」とみなす
WARNING_LOW_BREADTH_PCT_ABOVE_50DMA = 50.0  # これ未満を「参加率が低い」とみなす
WARNING_DISTRIBUTION_DAYS_THRESHOLD = 5  # 直近25営業日の売り抜け日数がこれ以上で点灯
WARNING_LEADER_BREAKDOWN_RATIO = 0.5  # Market Leadersのこの比率以上が50日線割れで点灯
DEFENSIVE_SECTOR_ETFS = ["XLP", "XLV", "XLU"]  # 生活必需品・ヘルスケア・公益
GROWTH_SECTOR_ETFS = ["XLK", "XLY"]  # 情報技術・一般消費財
IMPROVING_QUADRANTS = {"主導", "改善"}
WEAKENING_QUADRANTS = {"鈍化", "遅行"}


def compute_warning_flags(
    nasdaq_stage: dict,
    sp500_stage: dict,
    nasdaq_distribution_days: int,
    sp500_distribution_days: int,
    breadth_extended: dict,
    broad_universe_technicals: dict,
    leaders: list,
    sectors: dict,
) -> list[dict]:
    flags = []

    # 1. 指数が52週高値圏なのに参加率(50日線上比率)が低い
    near_high = any(
        (stage or {}).get("pct_below_52w_high") is not None
        and (stage or {})["pct_below_52w_high"] <= WARNING_NEAR_HIGH_PCT
        for stage in (nasdaq_stage, sp500_stage)
    )
    pct_above_50dma = (broad_universe_technicals or {}).get("pct_above_50dma")
    breadth_thrust_active = bool(
        near_high and pct_above_50dma is not None and pct_above_50dma < WARNING_LOW_BREADTH_PCT_ABOVE_50DMA
    )
    flags.append({
        "id": "breadth_thrust_divergence",
        "label": "指数は高値圏なのに参加銘柄が少ない",
        "active": breadth_thrust_active,
        "detail": f"50日線上比率 {pct_above_50dma}%" if pct_above_50dma is not None else "データ不足",
    })

    # 2. 新安値が新高値を上回っている
    ext = breadth_extended or {}
    new_highs, new_lows = ext.get("new_52w_highs"), ext.get("new_52w_lows")
    new_lows_exceed = bool(new_highs is not None and new_lows is not None and new_lows > new_highs)
    flags.append({
        "id": "new_lows_exceed_highs",
        "label": "新安値銘柄数が新高値銘柄数を上回っている",
        "active": new_lows_exceed,
        "detail": f"新高値{new_highs} / 新安値{new_lows}" if new_highs is not None else "データ不足",
    })

    # 3. 売り抜け日数が多い(直近25営業日、指数いずれか)
    max_dist_days = max(nasdaq_distribution_days or 0, sp500_distribution_days or 0)
    flags.append({
        "id": "elevated_distribution",
        "label": "売り抜け日数が多い(直近25営業日)",
        "active": max_dist_days >= WARNING_DISTRIBUTION_DAYS_THRESHOLD,
        "detail": f"NASDAQ {nasdaq_distribution_days} / S&P500 {sp500_distribution_days}",
    })

    # 4. リーダー株の崩れ(Market Leadersの過半数が50日線割れ)
    valid_leaders = [l for l in (leaders or []) if l.get("above_sma50") is not None]
    if valid_leaders:
        below_ratio = sum(1 for l in valid_leaders if not l["above_sma50"]) / len(valid_leaders)
        leader_active = below_ratio >= WARNING_LEADER_BREAKDOWN_RATIO
        detail = f"{round(below_ratio * 100)}%が50日線割れ({len(valid_leaders)}銘柄中)"
    else:
        leader_active, detail = False, "データ不足"
    flags.append({
        "id": "leader_breakdown",
        "label": "Market Leadersの過半数が50日線を割っている",
        "active": leader_active,
        "detail": detail,
    })

    # 5. ディフェンシブ優位・グロース劣位のローテーション
    sectors = sectors or {}
    defensive_quads = [(sectors.get(etf) or {}).get("quadrant") for etf in DEFENSIVE_SECTOR_ETFS]
    growth_quads = [(sectors.get(etf) or {}).get("quadrant") for etf in GROWTH_SECTOR_ETFS]
    defensive_improving = sum(1 for q in defensive_quads if q in IMPROVING_QUADRANTS)
    growth_weakening = sum(1 for q in growth_quads if q in WEAKENING_QUADRANTS)
    rotation_active = bool(
        defensive_improving >= len(defensive_quads) / 2 and growth_weakening >= len(growth_quads) / 2
    )
    flags.append({
        "id": "defensive_rotation",
        "label": "ディフェンシブ優位・グロース劣位のローテーション",
        "active": rotation_active,
        "detail": f"生活必需品/ヘルスケア/公益: {defensive_quads} / 情報技術/一般消費財: {growth_quads}",
    })

    return flags


def run(
    breadth_universe: str = "broad",
    max_breadth_tickers: int | None = None,
) -> dict:
    """
    breadth_universe: "broad"(既定) = iShares IWV(Russell3000)ベースの広域
      ユニバースを試み、失敗時はS&P500に自動フォールバック。
      "sp500" = 最初からS&P500のみ(軽量・お試し用、CIの初回動作確認などに)。
    max_breadth_tickers: 検証用に母集団を絞りたい場合の上限(Noneで無制限)。
      "broad"を数千銘柄そのまま毎日実行するとyfinanceの負荷・実行時間が
      読めないため、初回はこれを例えば500などに絞って実行時間を確認してから
      段階的に広げることを推奨する。
    """
    # 売り抜け日数・ステージ状態・FTD判定はいずれも同じ指数データ(1年分)で
    # 計算できるため、ダウンロードは1回にまとめる。市場ストレス指標
    # (VIX・HYG/IEF等)も同じ「軽量な少数ティッカー」の性質なのでまとめて取得する。
    idx_hist = download_history([NASDAQ_TICKER, SP500_TICKER] + STRESS_GAUGE_TICKERS, period="1y")
    nasdaq_df, sp500_df = idx_hist.get(NASDAQ_TICKER), idx_hist.get(SP500_TICKER)
    stress_gauges = compute_stress_gauges(idx_hist)

    # dt.date.today()(GitHub Actions実行日、UTC)は実際の株価データの最終
    # 取引日とずれることがある(例: 深夜0時台の実行で前日分の取引しかまだ
    # 確定していない場合)。「今日見ている数字がいつのものか」が紛らわしく
    # なるため、指数データの最終行の日付を対象取引日として使う。
    if nasdaq_df is not None and not nasdaq_df.empty:
        today = nasdaq_df.index[-1].date().isoformat()
    elif sp500_df is not None and not sp500_df.empty:
        today = sp500_df.index[-1].date().isoformat()
    else:
        today = dt.date.today().isoformat()

    nasdaq_dist = compute_distribution_and_stalling_days(nasdaq_df)
    sp500_dist = compute_distribution_and_stalling_days(sp500_df)

    nasdaq_stage = compute_index_stage(nasdaq_df)
    sp500_stage = compute_index_stage(sp500_df)

    nasdaq_trend = compute_trend_state(nasdaq_df)
    sp500_trend = compute_trend_state(sp500_df)
    overall_trend_state = combine_trend_states(nasdaq_trend.state, sp500_trend.state)

    sector_tickers = list(SECTOR_ETFS.keys()) + [BENCHMARK_FOR_SECTORS]
    sector_hist = download_history(sector_tickers, period="1y")
    # 2026-09-15の実行で判明: yfinanceが当日分の未確定バー(Closeが欠損)を
    # 含めて返すことがあり、dropna()せずにiloc[-1]を使うとNaNが混入する。
    # NaNはPythonのjson.dumpsではNaNリテラルとしてシリアライズされてしまい、
    # ブラウザ側のJSON.parse()が失敗してダッシュボードが「データなし」表示に
    # なる不具合につながっていた。
    benchmark_close = sector_hist[BENCHMARK_FOR_SECTORS]["Close"].dropna()

    sector_results = {}
    sector_temperatures = {}
    for etf, jp_name in SECTOR_ETFS.items():
        if etf not in sector_hist or sector_hist[etf].empty:
            continue
        etf_close = sector_hist[etf]["Close"].dropna()
        rrg = compute_sector_rrg(etf_close, benchmark_close)
        temperature = classify_sector_temperature(etf_close, benchmark_close)
        day_change_pct = (
            round(100 * (etf_close.iloc[-1] / etf_close.iloc[-2] - 1), 2) if len(etf_close) > 1 else None
        )
        sector_results[etf] = {
            "name_jp": jp_name,
            "temperature": temperature,
            "day_change_pct": day_change_pct,
            **rrg,
        }
        sector_temperatures[etf] = temperature

    market_regime = majority_vote_market_regime(sector_temperatures)

    # テーマ・ローテーション (代理ETF, GICS 11セクターと重複しない範囲)
    theme_tickers = list(THEME_ETFS.keys())
    theme_hist = download_history(theme_tickers, period="1y")
    theme_results = {}
    for etf, jp_name in THEME_ETFS.items():
        if etf not in theme_hist or theme_hist[etf].empty:
            continue
        close = theme_hist[etf]["Close"].dropna()
        rrg = compute_sector_rrg(close, benchmark_close)
        monthly_return = (
            round(100 * (close.iloc[-1] / close.iloc[-22] - 1), 2) if len(close) > 22 else None
        )
        day_change_pct = round(100 * (close.iloc[-1] / close.iloc[-2] - 1), 2) if len(close) > 1 else None
        theme_results[etf] = {
            "name_jp": jp_name,
            "monthly_return_pct": monthly_return,
            "day_change_pct": day_change_pct,
            **rrg,
        }

    # ブレッドス(市場の幅) + Market Leader(個別RSランキング)
    breadth_tickers, breadth_source = get_breadth_universe(breadth_universe, max_breadth_tickers)
    breadth_near_52w = {}
    breadth_extended = {}
    broad_universe_technicals = {}
    leaders = []
    trend_template_leaders = []
    opportunity_universe = None
    percentiles: dict = {}
    if breadth_tickers:
        # 52週(約252営業日)ブレッドス計算とMarket LeaderのRS百分位
        # (compute_rs_proxy_percentilesは既定でlookback_days=252営業日分の
        # データを要求する)の両方に足りるよう、"1y"ではなく"2y"で取得する。
        # "1y"だと実際の営業日数が252を僅かに下回ることがあり、その場合
        # percentilesが全銘柄で計算されず market_leaders が空になる不具合が
        # 実機検証(2026-09-13)で確認されたための修正。
        price_frames = download_history_chunked(breadth_tickers, period="2y")
        breadth_near_52w = compute_breadth_near_52w(price_frames)
        breadth_extended = compute_breadth_extended(price_frames)

        if compute_rs_proxy_percentiles is not None and price_frames:
            percentiles = compute_rs_proxy_percentiles(price_frames)

        broad_universe_technicals = compute_broad_universe_technicals(price_frames, percentiles)

        if percentiles:
            opportunity_universe = build_opportunity_universe(price_frames, percentiles, today, breadth_source)
            leaders = select_market_leaders(price_frames, percentiles, MARKET_LEADER_TOP_N)

            # トレンドテンプレート8条件(RS含む)に合格した銘柄だけのRS上位表。
            # Market Leadersは母集団全体のRS順位なので低品質な急騰銘柄が混ざり
            # やすいが、こちらはO'Neil/Minerviniのトレンドテンプレートで
            # 事前にふるいにかけた銘柄群なので、より「攻めに使える」候補になる
            # (Fable 5.1によるダッシュボードレビューでの指摘)。
            pass_tickers = broad_universe_technicals.pop("trend_template_pass_tickers", [])
            template_percentiles = {t: percentiles[t] for t in pass_tickers if t in percentiles}
            trend_template_leaders = select_market_leaders(
                price_frames, template_percentiles, TREND_TEMPLATE_LEADER_TOP_N
            )

    warning_flags = compute_warning_flags(
        nasdaq_stage, sp500_stage,
        nasdaq_dist.distribution_days, sp500_dist.distribution_days,
        breadth_extended, broad_universe_technicals, leaders, sector_results,
    )

    result = {
        "date": today,
        "nasdaq": {
            "distribution_days": nasdaq_dist.distribution_days,
            "stalling_days": nasdaq_dist.stalling_days,
            "distribution_dates": nasdaq_dist.distribution_dates,
            "stalling_dates": nasdaq_dist.stalling_dates,
            "trend_state": nasdaq_trend.__dict__,
            **nasdaq_stage,
        },
        "sp500": {
            "distribution_days": sp500_dist.distribution_days,
            "stalling_days": sp500_dist.stalling_days,
            "distribution_dates": sp500_dist.distribution_dates,
            "stalling_dates": sp500_dist.stalling_dates,
            "trend_state": sp500_trend.__dict__,
            **sp500_stage,
        },
        "overall_trend_state": overall_trend_state,
        "sectors": sector_results,
        "market_regime": market_regime,
        "themes": theme_results,
        "breadth_universe_source": breadth_source,
        "breadth_near_52w": breadth_near_52w,
        "breadth_extended": breadth_extended,
        "broad_universe_technicals": broad_universe_technicals,
        "opportunity_universe": opportunity_universe,
        "market_leaders": leaders,
        "trend_template_leaders": trend_template_leaders,
        "stress_gauges": stress_gauges,
        "warning_flags": warning_flags,
    }
    return result


def flatten_for_sheet(result: dict) -> list:
    """Google Sheets への1行分のデータを作る(upsert_rowで日付キー上書き)。
    result["cumulative_ad_line"] は __main__ 側で history_store の履歴から
    計算して注入される想定(run()自体はファイルI/Oを行わない)。"""
    leading_sectors = [k for k, v in result["sectors"].items() if v["quadrant"] == "主導"]
    lagging_sectors = [k for k, v in result["sectors"].items() if v["quadrant"] == "遅行"]
    leading_themes = [k for k, v in result["themes"].items() if v["quadrant"] == "主導"]
    lagging_themes = [k for k, v in result["themes"].items() if v["quadrant"] == "遅行"]
    top_leaders = ",".join(l["ticker"] for l in result["market_leaders"][:10])

    regime = result["market_regime"]
    ext = result["breadth_extended"]
    near = result["breadth_near_52w"]
    but = result["broad_universe_technicals"]
    nasdaq_trend = result["nasdaq"]["trend_state"]
    sp500_trend = result["sp500"]["trend_state"]
    stress = result.get("stress_gauges", {})
    active_warning_flags = [f["id"] for f in result.get("warning_flags", []) if f["active"]]

    return [
        result["date"],
        result["nasdaq"]["distribution_days"],
        result["nasdaq"]["stalling_days"],
        result["sp500"]["distribution_days"],
        result["sp500"]["stalling_days"],
        result["nasdaq"]["above_sma50"],
        result["nasdaq"]["above_sma200"],
        result["overall_trend_state"],
        nasdaq_trend.get("state"),
        nasdaq_trend.get("ftd_date"),
        nasdaq_trend.get("days_since_ftd"),
        sp500_trend.get("state"),
        regime.get("judgement"),
        regime.get("counts", {}).get("上昇", 0),
        regime.get("counts", {}).get("買い集め", 0),
        regime.get("counts", {}).get("中立", 0),
        regime.get("counts", {}).get("調整", 0),
        result["breadth_universe_source"],
        ext.get("universe_size"),
        ext.get("new_52w_highs"),
        ext.get("new_52w_lows"),
        ext.get("advancers"),
        ext.get("decliners"),
        ext.get("up_volume_pct"),
        result.get("cumulative_ad_line"),
        near.get("near_high_pct"),
        near.get("near_low_pct"),
        but.get("pct_above_50dma"),
        but.get("pct_above_200dma"),
        but.get("trend_template_pass_rate_pct"),
        but.get("trend_template_pass_count"),
        ",".join(leading_sectors),
        ",".join(lagging_sectors),
        ",".join(leading_themes),
        ",".join(lagging_themes),
        top_leaders,
        (stress.get("vix") or {}).get("level"),
        (stress.get("credit_hyg_ief") or {}).get("ratio"),
        (stress.get("breadth_rsp_spy") or {}).get("ratio"),
        (stress.get("risk_appetite_iwm_spy") or {}).get("ratio"),
        (stress.get("semis_soxx_spy") or {}).get("ratio"),
        len(active_warning_flags),
        ",".join(active_warning_flags),
    ]


SHEET_HEADER = [
    "date", "nasdaq_dist_days", "nasdaq_stall_days", "sp500_dist_days", "sp500_stall_days",
    "nasdaq_above_sma50", "nasdaq_above_sma200",
    "overall_trend_state", "nasdaq_trend_state", "nasdaq_ftd_date", "nasdaq_days_since_ftd",
    "sp500_trend_state",
    "market_regime", "sector_count_up", "sector_count_accum", "sector_count_neutral", "sector_count_down",
    "breadth_universe_source", "breadth_universe_size",
    "breadth_new_52w_highs", "breadth_new_52w_lows",
    "breadth_advancers", "breadth_decliners", "breadth_up_volume_pct",
    "cumulative_ad_line",
    "breadth_near_high_pct", "breadth_near_low_pct",
    "broad_pct_above_50dma", "broad_pct_above_200dma",
    "broad_trend_template_pass_rate_pct", "broad_trend_template_pass_count",
    "leading_sectors", "lagging_sectors",
    "leading_themes", "lagging_themes",
    "top_market_leaders",
    "vix_level", "credit_hyg_ief_ratio", "breadth_rsp_spy_ratio",
    "risk_appetite_iwm_spy_ratio", "semis_soxx_spy_ratio",
    "active_warning_flag_count", "active_warning_flags",
]


LEADER_SHEET_HEADER = ["date", "ticker", "rs_percentile", "day_change_pct", "one_month_pct", "three_month_pct"]


def flatten_leaders_for_sheet(result: dict) -> list[list]:
    return [
        [result["date"], l["ticker"], l["rs_percentile"], l["day_change_pct"], l["one_month_pct"], l["three_month_pct"]]
        for l in result["market_leaders"]
    ]


if __name__ == "__main__":
    import json
    import os

    # 運用中に母集団を調整できるよう環境変数で上書き可能にしておく。
    # BREADTH_UNIVERSE: "broad"(既定) または "sp500"
    # MAX_BREADTH_TICKERS: 検証用に母集団件数を絞りたい場合の上限(未設定なら無制限)
    breadth_universe_env = os.environ.get("BREADTH_UNIVERSE", "broad")
    max_tickers_env = os.environ.get("MAX_BREADTH_TICKERS")
    max_tickers = int(max_tickers_env) if max_tickers_env else None

    res = run(breadth_universe=breadth_universe_env, max_breadth_tickers=max_tickers)

    # 累積A/Dライン: 「gitをDBにする」履歴JSON(history_store)を正として、
    # 前回保存分(今日以外で最新の日付)の累積値に今日の値上がり・値下がり
    # 銘柄数の差を積み上げる。同じ日に何度も再実行しても、そのたびに
    # history_store側の当日ファイルが上書きされるだけなので二重加算しない。
    try:
        from history_store import list_history_dates, load_snapshot

        prev_dates = [d for d in list_history_dates() if d != res["date"]]
        prev_cumulative = 0.0
        if prev_dates:
            prev_snapshot = load_snapshot(prev_dates[-1])
            if prev_snapshot and prev_snapshot.get("cumulative_ad_line") is not None:
                prev_cumulative = float(prev_snapshot["cumulative_ad_line"])
        ext = res.get("breadth_extended", {})
        net_ad_today = (ext.get("advancers") or 0) - (ext.get("decliners") or 0)
        res["cumulative_ad_line"] = prev_cumulative + net_ad_today
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 累積A/Dライン計算失敗、Noneのまま保存: {e}", file=sys.stderr)
        res["cumulative_ad_line"] = None

    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))

    # 「gitをDBにする」方式: 日次結果をリポジトリ内にJSONで保存する。
    # git add/commit/push自体はGitHub Actionsワークフロー側のステップが行う。
    try:
        from history_store import save_snapshot

        saved_path = save_snapshot(res)
        print(f"[info] 履歴JSON保存完了: {saved_path}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 履歴JSON保存スキップ: {e}", file=sys.stderr)

    # Google Sheets へ書き込む場合 (環境変数が設定されていれば)
    try:
        from sheets_writer import append_rows, ensure_worksheet, upsert_row

        sheet_id = os.environ.get("SPREADSHEET_ID")
        if sheet_id:
            ensure_worksheet(sheet_id, "地合いトラッカー", SHEET_HEADER)
            upsert_row(sheet_id, "地合いトラッカー", flatten_for_sheet(res))

            leader_rows = flatten_leaders_for_sheet(res)
            if leader_rows:
                ensure_worksheet(sheet_id, "Market Leaders", LEADER_SHEET_HEADER)
                # Market Leadersは日次のスナップショット一覧として全件追記のまま
                # (upsertすると当日分だけ複数回書き込み時に重複行のクリーンアップが
                # 別途必要になるため、履歴JSON側を正として割り切る)。
                append_rows(sheet_id, "Market Leaders", leader_rows)

            print("[info] Google Sheetsへの書き込み完了", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Sheets書き込みスキップ: {e}", file=sys.stderr)
