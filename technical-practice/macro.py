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


FETCH_ERRORS: dict = {}  # 系列ごとの最後の取得エラー(画面とJSONに残して原因を追えるようにする)


def _get(url: str, timeout: int = 60, tries: int = 3) -> str:
    import time
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,application/json,*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(3 * (i + 1))
    raise last


FRED_API = "https://api.stlouisfed.org/fred/series/observations?series_id={series}&api_key={key}&file_type=json"
_FRED_CSV_DEAD = False  # 公開CSVが一度タイムアウトしたら、その実行では以後試さない


def fetch_fred(series: str) -> pd.Series | None:
    """FREDの値を取る。
    2026-10-25の実行で、公開CSV(fred.stlouisfed.org)はGitHub Actionsからだと
    全系列が読み取りタイムアウトになった(ブロックされている可能性が高い)。
    1回あたり最大60秒×3回待つため、地合いジョブ全体が約25分延びた。
      1) 環境変数 FRED_API_KEY があれば公式API(api.stlouisfed.org)を使う(無料キー)
      2) なければ公開CSVを短いタイムアウトで1回だけ試し、タイムアウトしたら以後の系列は飛ばす
    """
    import json
    import os
    global _FRED_CSV_DEAD
    key = os.environ.get("FRED_API_KEY", "").strip()
    try:
        if key:
            obs = json.loads(_get(FRED_API.format(series=series, key=key), timeout=30, tries=2))["observations"]
            s = pd.Series(
                pd.to_numeric([o["value"] for o in obs], errors="coerce"),
                index=pd.to_datetime([o["date"] for o in obs]),
            )
            return s.dropna()
        if _FRED_CSV_DEAD:
            raise TimeoutError("公開CSVはこの実行で既にタイムアウトしたため省略(FRED_API_KEY未設定)")
        try:
            raw = _get(FRED_CSV.format(series=series), timeout=15, tries=1)
        except TimeoutError:
            _FRED_CSV_DEAD = True
            raise
        if not raw.lstrip().lower().startswith(("observation_date", "date")):
            raise ValueError(f"CSVではない応答: {raw[:80]!r}")
        df = pd.read_csv(io.StringIO(raw))
        s = pd.to_numeric(df[df.columns[1]], errors="coerce")
        s.index = pd.to_datetime(df[df.columns[0]])
        return s.dropna()
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        k = __import__("os").environ.get("FRED_API_KEY", "").strip()
        if k:
            msg = msg.replace(k, "***")  # キーを記録・画面に出さない
        FETCH_ERRORS[f"FRED:{series}"] = msg[:200]
        print(f"[warn] FRED取得失敗 ({series}): {e}", file=sys.stderr)
        return None


# ---- FREDが使えないときの代替(いずれも公的機関の公開API、キー不要) ----
NYFED_EFFR = "https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate={start}&endDate={end}"
BLS_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/{series}"


def fetch_nyfed_target_range() -> tuple[pd.Series, pd.Series] | None:
    """NY連銀のEFFR公表データに含まれる誘導目標レンジ(下限/上限)。"""
    import json
    try:
        end = pd.Timestamp.today().normalize()
        start = end - pd.DateOffset(years=YEARS_BACK)
        raw = _get(NYFED_EFFR.format(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d")))
        rows = json.loads(raw).get("refRates", [])
        if not rows:
            raise ValueError("refRatesが空")
        idx = pd.to_datetime([r["effectiveDate"] for r in rows])
        lo = pd.Series([float(r["targetRateFrom"]) for r in rows], index=idx).sort_index()
        up = pd.Series([float(r["targetRateTo"]) for r in rows], index=idx).sort_index()
        return lo, up
    except Exception as e:  # noqa: BLE001
        FETCH_ERRORS["NYFED:EFFR"] = f"{type(e).__name__}: {e}"[:200]
        print(f"[warn] NY連銀EFFR取得失敗: {e}", file=sys.stderr)
        return None


def fetch_bls(series: str) -> pd.Series | None:
    """BLSの公開API(v1、キー不要・直近数年分)。CPI総合 CUUR0000SA0、コア CUUR0000SA0L1E。"""
    import json
    try:
        data = json.loads(_get(BLS_V1.format(series=series), timeout=20, tries=1))
        items = data["Results"]["series"][0]["data"]
        pts = {}
        for it in items:
            if not str(it.get("period", "")).startswith("M") or it["period"] == "M13":
                continue
            pts[pd.Timestamp(f"{it['year']}-{it['period'][1:]}-01")] = float(it["value"])
        if not pts:
            raise ValueError("データなし")
        return pd.Series(pts).sort_index()
    except Exception as e:  # noqa: BLE001
        FETCH_ERRORS[f"BLS:{series}"] = f"{type(e).__name__}: {e}"[:200]
        print(f"[warn] BLS取得失敗 ({series}): {e}", file=sys.stderr)
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
    source = "FRED (DFEDTARU, DFEDTARL, FEDTARMDLR)"
    if (upper is None or lower is None) and fetch is fetch_fred:
        alt = fetch_nyfed_target_range()
        if alt is not None:
            lower, upper = alt
            source = "NY連銀(EFFR公表の誘導目標レンジ)、長期見通しはFRED"
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
        "source": source,
    }


def build_inflation(fetch=None) -> dict | None:
    fetch = fetch or fetch_fred
    out = {}
    bls = {"cpi": "CUUR0000SA0", "core_cpi": "CUUR0000SA0L1E"}
    for key, series in (("cpi", "CPIAUCSL"), ("core_cpi", "CPILFESL"), ("core_pce", "PCEPILFE")):
        level = fetch(series)
        if level is None and fetch is fetch_fred and key in bls:
            level = fetch_bls(bls[key])  # 季節調整なしの指数だが前年同月比なら比較できる
        yoy = yoy_pct(level)
        if yoy is None:
            out[key] = None
            continue
        since = yoy.index.max() - pd.DateOffset(years=YEARS_BACK)
        out[key] = {**_points(yoy, since), "latest": float(yoy.iloc[-1]), "as_of": yoy.index[-1].strftime("%Y-%m")}
    if not any(out.values()):
        return None
    out["target_pct"] = 2.0  # FRBの物価目標(PCEインフレ率で年2%)。公表されている目標値
    out["source"] = "FRED (CPIAUCSL, CPILFESL, PCEPILFE)、取得できない場合はBLS。前年同月比は自前計算"
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
    global _FRED_CSV_DEAD
    FETCH_ERRORS.clear()
    _FRED_CSV_DEAD = False
    out = {
        "policy_rate": build_policy_rate(),
        "inflation": build_inflation(),
        "oil": build_oil(download),
    }
    out["fetch_errors"] = dict(FETCH_ERRORS)
    return out
