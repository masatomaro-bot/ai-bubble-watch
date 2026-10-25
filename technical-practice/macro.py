"""
macro.py
========
地合いページ最上部の「外部環境」チャート用データ(2026-10-25追加)。
  - FRBの政策金利(誘導目標レンジ上限/下限、日次)       FRED: DFEDTARU / DFEDTARL
  - FOMC参加者の長期の政策金利見通し(中央値)           FRED: FEDTARMDLR  ← 「中立金利」の目安線
  - インフレ率(前年同月比): CPI総合・コアCPI・コアPCE   FRED: CPIAUCSL / CPILFESL / PCEPILFE
    ← FRBの物価目標2%(コアPCEで見る)を目安線にする
  - 原油(ブレント先物 BZ=F、WTI先物 CL=F)の日足          yfinance
    ← 原油には公式の「適正価格」はないため、目安線は計算で出せる
      200日線と過去5年平均にとどめる(自前の価格予想は置かない)

FREDの fredgraph.csv はAPIキー不要の公開CSV。取得に失敗した系列は None にし、
画面側で「取得できなかった」と表示する(他の地合い計算は止めない)。
"""

from __future__ import annotations

import io
import sys
import urllib.request

import pandas as pd

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
USER_AGENT = "Mozilla/5.0"
YEARS_BACK = 5
CHART_DAYS = 260  # 原油ローソク足の表示日数(約1年)


def fetch_fred(series: str) -> pd.Series | None:
    try:
        req = urllib.request.Request(FRED_CSV.format(series=series), headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(raw))
        date_col = df.columns[0]
        s = pd.to_numeric(df[df.columns[1]], errors="coerce")
        s.index = pd.to_datetime(df[date_col])
        return s.dropna()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] FRED取得失敗 ({series}): {e}", file=sys.stderr)
        return None


def yoy_pct(index_series: pd.Series | None) -> pd.Series | None:
    if index_series is None or len(index_series) < 13:
        return None
    return (100 * (index_series / index_series.shift(12) - 1)).dropna().round(2)


def _points(s: pd.Series | None, since: pd.Timestamp) -> dict | None:
    if s is None or s.empty:
        return None
    s = s[s.index >= since]
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [round(float(v), 2) for v in s]}


def build_policy_rate(fetch=None) -> dict | None:
    fetch = fetch or fetch_fred
    upper, lower = fetch("DFEDTARU"), fetch("DFEDTARL")
    if upper is None or lower is None:
        return None
    since = upper.index.max() - pd.DateOffset(years=YEARS_BACK)
    # 日次の段差データは週次の最終値に間引いて軽くする(政策金利の変更日は段差として残る)
    up_w = upper[upper.index >= since].resample("W-FRI").last().dropna()
    lo_w = lower[lower.index >= since].resample("W-FRI").last().dropna()
    longer = fetch("FEDTARMDLR")
    longer_run = None
    if longer is not None and not longer.empty:
        longer_run = {"value": round(float(longer.iloc[-1]), 2), "as_of": longer.index[-1].strftime("%Y-%m-%d")}
    return {
        "upper": _points(up_w, since),
        "lower": _points(lo_w, since),
        "latest_upper": round(float(upper.iloc[-1]), 2),
        "latest_lower": round(float(lower.iloc[-1]), 2),
        "as_of": upper.index[-1].strftime("%Y-%m-%d"),
        "longer_run_median": longer_run,
        "source": "FRED (DFEDTARU, DFEDTARL, FEDTARMDLR)",
    }


def build_inflation(fetch=None) -> dict | None:
    fetch = fetch or fetch_fred
    out = {}
    for key, series in (("cpi", "CPIAUCSL"), ("core_cpi", "CPILFESL"), ("core_pce", "PCEPILFE")):
        yoy = yoy_pct(fetch(series))
        if yoy is None:
            out[key] = None
            continue
        since = yoy.index.max() - pd.DateOffset(years=YEARS_BACK)
        out[key] = {**_points(yoy, since), "latest": float(yoy.iloc[-1]), "as_of": yoy.index[-1].strftime("%Y-%m")}
    if not any(out.values()):
        return None
    out["target_pct"] = 2.0  # FRBの物価目標(PCEインフレ率で年2%)。公表されている目標値
    out["source"] = "FRED (CPIAUCSL, CPILFESL, PCEPILFE)、前年同月比は自前計算"
    return out


def build_oil(download) -> dict | None:
    """download: tickers -> {ticker: DataFrame} (market_climate.download_history を渡す)。"""
    try:
        hist = download(["BZ=F", "CL=F"], period="5y")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 原油データ取得失敗: {e}", file=sys.stderr)
        return None
    out = {}
    for key, ticker, label in (("brent", "BZ=F", "ブレント原油先物"), ("wti", "CL=F", "WTI原油先物")):
        df = hist.get(ticker)
        if df is None or df.empty:
            out[key] = None
            continue
        df = df.dropna(subset=["Close"])
        close = df["Close"]
        sma50, sma200 = close.rolling(50).mean(), close.rolling(200).mean()
        tail = df.tail(CHART_DAYS)
        r2 = lambda v: round(float(v), 2) if pd.notna(v) else None  # noqa: E731
        out[key] = {
            "label": label,
            "ticker": ticker,
            "price": r2(close.iloc[-1]),
            "as_of": close.index[-1].strftime("%Y-%m-%d"),
            "avg_5y": r2(close.mean()),
            "sma200": r2(sma200.iloc[-1]),
            "chart": {
                "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
                "o": [r2(v) for v in tail["Open"]],
                "h": [r2(v) for v in tail["High"]],
                "l": [r2(v) for v in tail["Low"]],
                "c": [r2(v) for v in tail["Close"]],
                "sma50": [r2(v) for v in sma50.loc[tail.index]],
                "sma200": [r2(v) for v in sma200.loc[tail.index]],
            },
        }
    if not any(out.values()):
        return None
    out["source"] = "Yahoo Finance(yfinance) BZ=F, CL=F。期近の先物で、限月の乗り換えで段差が出ることがある"
    return out


def build_macro(download) -> dict:
    return {
        "policy_rate": build_policy_rate(),
        "inflation": build_inflation(),
        "oil": build_oil(download),
    }
