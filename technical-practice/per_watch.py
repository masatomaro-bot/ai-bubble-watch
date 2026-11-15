"""
per_watch.py
============
ポートフォリオウォッチ(docs/data/per_watch.json)の「株価に連動する部分」を毎営業日更新する。

背景(2026-11-15): per_watch.json は Claude が手で作り直す固定データだったため、
「データ時点 2026-10-31」のまま株価が止まっていた。株価・今のPER・過去5年の中での
位置・週足ローソクは yfinance だけで再計算できるので、日次ワークフローに載せる。

このスクリプトが更新するもの(株価だけで決まるもの):
  - weekly      : 週足ローソク(直近104週)＋10週線・40週線
  - series      : 進行中の会計年度の行 [日付, null, PER下限, PER上限]
  - price / price_date / per_now / per_now_mid / percentile_now
  - price_floor / price_mid / price_cap (今期EPS × 過去の倍率)
  - frame.per_now_lo / per_now_hi / bands (来年度の予想EPS × 過去の倍率)
  - 先頭の asof (株価の日付)

このスクリプトが触らないもの(人が確認して決めるもの):
  - eps_now(今期のEPSの幅)・frame の予想EPS・過去の確定年度のPER(series の確定行)
  - eps_asof(EPSの前提を最後に確認した日)
  これらは決算やコンセンサスの変化に合わせて Claude が更新する。EPSは必ずコア基準
  (評価益・一時益を除く)で入れる。ルールは docs/PORTFOLIO.md を参照。

使い方:
  python per_watch.py            # yfinance から取得して docs/data/per_watch.json を更新
  python per_watch.py --dry-run  # 書き込まずに差分だけ表示
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(os.path.dirname(HERE), "docs", "data", "per_watch.json")

WEEKLY_KEEP = 104      # 週足ローソクとして保持する本数(約2年)
BAND_NAMES = ["最低", "下位10%", "中央", "上位10%", "最高"]


# ---------------------------------------------------------------- 純粋な計算

def monday_of(d: date) -> date:
    """その日を含む週の月曜日。週足の日付は月曜に揃える(祝日で火曜始まりの週も同じ週として扱う)。"""
    return d - timedelta(days=d.weekday())


def _percentile(sorted_vals: list[float], q: float) -> float:
    """線形補間のパーセンタイル(numpy.percentile の既定と同じ)。"""
    if not sorted_vals:
        raise ValueError("empty")
    k = (len(sorted_vals) - 1) * q / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def distribution(series: list[list]) -> dict:
    """確定年度の行(PERが入っている行)だけで分布を出す。"""
    vals = sorted(r[1] for r in series if r[1] is not None)
    return {
        "n": len(vals),
        "min": round(vals[0], 1),
        "p10": round(_percentile(vals, 10), 1),
        "p50": round(_percentile(vals, 50), 1),
        "p90": round(_percentile(vals, 90), 1),
        "max": round(vals[-1], 1),
        "values": vals,
    }


def percentile_rank(sorted_vals: list[float], x: float) -> int:
    """x が分布の下から何%にあるか(x より小さい値の割合)。"""
    below = sum(1 for v in sorted_vals if v < x)
    return round(below / len(sorted_vals) * 100)


def fmt_price(v: float) -> str:
    return str(round(v)) if v >= 100 else f"{v:.1f}"


def fmt_range(lo: float, hi: float, f=fmt_price) -> str:
    a, b = f(lo), f(hi)
    return a if a == b else f"{a}〜{b}"


def merge_weekly(weekly: list[list], bars: list[tuple]) -> list[list]:
    """既存の週足に新しい足を上書き・追加し、10週線・40週線を付け直す。

    weekly: [[日付, 始値, 高値, 安値, 終値, 10週線, 40週線], ...]
    bars  : [(日付(date), 始値, 高値, 安値, 終値), ...]  日付は月曜に揃えて扱う。
    既存の足の移動平均は、より古い(保持していない)終値を使って計算済みなので、
    上書き・追加した足だけ計算し直す。
    """
    by_date = {r[0]: list(r) for r in weekly}
    touched = set()
    for d, o, h, l, c in bars:
        if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in (o, h, l, c)):
            continue
        key = monday_of(d).isoformat()
        by_date[key] = [key, round(o, 3), round(h, 3), round(l, 3), round(c, 3), None, None]
        touched.add(key)
    out = [by_date[k] for k in sorted(by_date)]
    closes = [r[4] for r in out]
    for i, r in enumerate(out):
        if r[0] in touched or r[5] is None:
            r[5] = round(sum(closes[i - 9:i + 1]) / 10, 3) if i >= 9 else None
            r[6] = round(sum(closes[i - 39:i + 1]) / 40, 3) if i >= 39 else None
    return out[-WEEKLY_KEEP:]


def recompute(h: dict) -> dict:
    """1銘柄ぶんの、株価に連動する項目をすべて計算し直す(h を書き換えて返す)。"""
    eps = h["eps_now"]
    eps_lo, eps_hi = float(eps["lo"]), float(eps["hi"])
    if not (0 < eps_lo <= eps_hi):
        raise ValueError(f"{h['ticker']}: eps_now が不正 (lo={eps_lo}, hi={eps_hi})")
    weekly = h["weekly"]
    last = weekly[-1]
    price = last[4]

    # 進行中の年度の行を週足の終値から作り直す。確定年度の行には触らない。
    start = eps["from"]
    confirmed = [r for r in h["series"] if r[0] < start]
    band = [[r[0], None, round(r[4] / eps_hi, 2), round(r[4] / eps_lo, 2)] for r in weekly if r[0] >= start]
    h["series"] = confirmed + band

    dist = distribution(h["series"])
    per_lo, per_hi = price / eps_hi, price / eps_lo
    mid = (per_lo + per_hi) / 2
    h["price"] = price
    h["price_date"] = h.get("price_date") or last[0]
    h["per_now"] = fmt_range(per_lo, per_hi, lambda v: f"{v:.1f}")
    h["per_now_mid"] = round(mid, 1)
    h["percentile_now"] = percentile_rank(dist["values"], mid)
    h["p10"], h["p50"], h["p90"], h["per_max"] = dist["p10"], dist["p50"], dist["p90"], dist["max"]
    h["price_floor"] = fmt_range(dist["p10"] * eps_lo, dist["p10"] * eps_hi)
    h["price_mid"] = fmt_range(dist["p50"] * eps_lo, dist["p50"] * eps_hi)
    h["price_cap"] = fmt_range(dist["p90"] * eps_lo, dist["p90"] * eps_hi)

    f = h.get("frame")
    if f:
        f_lo, f_hi = float(f["eps_lo"]), float(f["eps_hi"])
        f["per_now_lo"] = round(price / f_hi, 1)
        f["per_now_hi"] = round(price / f_lo, 1)
        mults = [dist["min"], dist["p10"], dist["p50"], dist["p90"], dist["max"]]
        f["bands"] = [
            {"name": n, "mult": m, "lo": round(m * f_lo, 2), "hi": round(m * f_hi, 2)}
            for n, m in zip(BAND_NAMES, mults)
        ]
    return h


def apply_bars(data: dict, bars_by_ticker: dict[str, list[tuple]], price_dates: dict[str, str] | None = None) -> dict:
    """取得した週足を全銘柄に反映する。取得できなかった銘柄は前回の値のまま残す。"""
    price_dates = price_dates or {}
    for h in data["holdings"]:
        bars = bars_by_ticker.get(h["ticker"])
        if bars:
            h["weekly"] = merge_weekly(h["weekly"], bars)
            h["price_date"] = price_dates.get(h["ticker"]) or max(b[0] for b in bars).isoformat()
        recompute(h)
    dates = [h["price_date"] for h in data["holdings"] if h.get("price_date")]
    if dates:
        data["asof"] = max(dates)
    return data


# ---------------------------------------------------------------- 取得と入出力

def fetch_bars(holdings: list[dict]) -> tuple[dict[str, list[tuple]], dict[str, str]]:
    """yfinance から週足(直近3か月)と最終取引日を取得する。失敗した銘柄は結果に含めない。"""
    from yf_retry import download_with_retry  # ネットワークに出るのはここだけ

    bars: dict[str, list[tuple]] = {}
    last_day: dict[str, str] = {}
    for h in holdings:
        sym = h.get("yf")
        if not sym:
            continue
        try:
            wk = download_with_retry(sym, period="3mo", interval="1wk", auto_adjust=False, progress=False)
            dy = download_with_retry(sym, period="10d", interval="1d", auto_adjust=False, progress=False)
        except Exception as e:  # noqa: BLE001  yfinance は多様な例外を投げる
            print(f"[warn] {h['ticker']} ({sym}) の取得に失敗、前回の値を残す: {e}", file=sys.stderr)
            continue
        if wk is None or wk.empty:
            print(f"[warn] {h['ticker']} ({sym}) のデータが空、前回の値を残す", file=sys.stderr)
            continue
        if hasattr(wk.columns, "nlevels") and wk.columns.nlevels > 1:
            wk = wk.droplevel(1, axis=1)
        wk = wk.dropna(subset=["Close"])
        rows = [(ts.date(), float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])) for ts, r in wk.iterrows()]
        # 取得期間の最初の足は週の途中から始まることがあり、完全な週足を不完全な足で
        # 上書きしてしまうので捨てる(その週はすでに保存済み)。
        rows = rows[1:]
        if not rows:
            continue
        bars[h["ticker"]] = rows
        if dy is not None and not dy.empty:
            last_day[h["ticker"]] = dy.index[-1].date().isoformat()
    return bars, last_day


def summary(data: dict) -> str:
    return " / ".join(f"{h['ticker']} {h['price']} PER {h['per_now']} ({h['percentile_now']}%)" for h in data["holdings"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ポートフォリオウォッチの株価連動部分を更新する")
    ap.add_argument("--path", default=DEFAULT_PATH)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    with open(args.path, encoding="utf-8") as fp:
        data = json.load(fp)
    before = json.dumps(data, ensure_ascii=False, sort_keys=True)

    bars, last_day = fetch_bars(data["holdings"])
    if not bars:
        print("[warn] 1銘柄も取得できなかったため、per_watch.json は更新しない", file=sys.stderr)
        return 0
    apply_bars(data, bars, last_day)
    data["updated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")

    after = json.dumps({k: v for k, v in data.items() if k != "updated_at"}, ensure_ascii=False, sort_keys=True)
    before_cmp = json.dumps({k: v for k, v in json.loads(before).items() if k != "updated_at"}, ensure_ascii=False, sort_keys=True)
    print(f"[info] {data['asof']} 時点: {summary(data)}")
    if after == before_cmp:
        print("[info] 変更なし")
        return 0
    if args.dry_run:
        print("[info] --dry-run のため書き込まない")
        return 0
    with open(args.path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)
    print(f"[info] {args.path} を更新した")
    return 0


if __name__ == "__main__":
    sys.exit(main())
