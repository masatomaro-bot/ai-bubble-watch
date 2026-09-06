"""
ffty_screener.py
=================
FFTY (CapForce IBD 50 ETF, 旧Innovator IBD 50 ETF) の構成銘柄を母集団として、
ミネルヴィニ・トレンドテンプレート8条件でスクリーニングし、予算(円)内に収まる
候補を毎営業日ログに残す「VCP/RSスクリーナー結果トラッカー」。

VCP(ボラティリティ収縮パターン)やカップ・ウィズ・ハンドルなどベースパターン
そのものの視覚判定はこのスクリプトでは行わない(方針: チャート判断は
TradingViewで自分の目で行う)。ここでの役割は「トレンドテンプレートを
通過した監視対象を毎日ログに残す」ところまで。

■ FFTY構成銘柄の取得について (重要な注意)
FFTYは2026年4月にInnovatorからCapForceへ運用移管された。移管後、公式サイト
(capforceetf.com) には保有銘柄の一覧ページはあるが、クリーンなCSV/APIの
公開URLは見当たらなかった(調査時点)。ページはJSで描画されるテーブルのため、
Playwright (ヘッドレスブラウザ) でレンダリングしてスクレイピングする方式を
採用している。サイト側のHTML構造が変わるとセレクタの調整が必要になる、
という前提の実装であることに留意すること。

このサンドボックス環境では外部ドメインへの通信が許可されておらず、
capforceetf.com への実アクセスでの動作確認はできていない。GitHub Actions
(または手元PC) で最初に実行した際、取得できた銘柄数・内容を必ず目視確認する
こと。
"""

from __future__ import annotations

import datetime as dt
import re
import sys

import pandas as pd
import yfinance as yf

FFTY_HOLDINGS_URL = "https://www.capforceetf.com/ffty/details"

# holdings.name もしくは ticker がこれらのパターンに一致する行は
# 現金・短期国債など「株式ではない」構成要素とみなして除外する。
NON_EQUITY_NAME_PATTERNS = [
    r"cash\s*&?\s*other",
    r"treasury obligations fund",
    r"money market",
]
NON_EQUITY_TICKER_PATTERNS = [
    r"^FXFXX$",   # First American Treasury Obligations Fund (2026.09時点で確認)
    r".*&.*",     # "CASH&OTHER" のような表記
]

# 「30万〜100万円」は1株あたり価格の許容レンジではなく、1銘柄あたりに
# 投じる資金(ポジションサイズ)の目安。したがって銘柄フィルタとしては
# 「1株が高すぎて予算内で買いにくい銘柄を除外する」上限チェックのみ行う
# (以前の実装は誤って1株価格をこのレンジ自体でフィルタしており、
#  実際のFFTY銘柄(ほぼ全て1株$20〜$400程度)が軒並みFalseになるバグだった)。
BUDGET_JPY_MIN = 300_000
BUDGET_JPY_MAX = 1_000_000


# ----------------------------------------------------------------------------
# 1. FFTY構成銘柄の取得 (Playwright スクレイピング)
# ----------------------------------------------------------------------------

def fetch_ffty_holdings() -> list[dict]:
    """capforceetf.com の保有銘柄テーブルをレンダリングして取得する。
    戻り値: [{"ticker": ..., "name": ..., "sector": ..., "weight_pct": ...}, ...]
    """
    from playwright.sync_api import sync_playwright

    holdings = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(FFTY_HOLDINGS_URL, wait_until="networkidle", timeout=30000)

        # 「Show All」的なボタンがあればクリックして全件展開する。
        # サイト文言は変わりうるため、複数パターンを試す。
        for label_pattern in [
            re.compile(r"show all", re.I),
            re.compile(r"すべて表示", re.I),
            re.compile(r"view all", re.I),
        ]:
            try:
                btn = page.get_by_text(label_pattern)
                if btn.count() > 0:
                    btn.first.click()
                    page.wait_for_timeout(1500)
                    break
            except Exception:  # noqa: BLE001
                continue

        # テーブル行を汎用的に拾う。tr要素の中に4セル以上あるものを候補とする。
        rows = page.query_selector_all("table tr")
        for row in rows:
            cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
            if len(cells) < 3:
                continue
            # 期待する並び: Name, Ticker, Sector, Weight (要確認・要調整)
            weight_match = None
            for c in cells:
                m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", c)
                if m:
                    weight_match = float(m.group(1))
            ticker_candidates = [c for c in cells if re.fullmatch(r"[A-Z][A-Z0-9.]{0,6}", c)]
            if not ticker_candidates or weight_match is None:
                continue
            holdings.append({
                "ticker": ticker_candidates[0],
                "name": cells[0],
                "sector": cells[2] if len(cells) > 2 else "",
                "weight_pct": weight_match,
            })

        browser.close()

    return holdings


def filter_equity_rows(holdings: list[dict]) -> list[dict]:
    def is_equity(row: dict) -> bool:
        name = row.get("name", "")
        ticker = row.get("ticker", "")
        for pat in NON_EQUITY_NAME_PATTERNS:
            if re.search(pat, name, re.I):
                return False
        for pat in NON_EQUITY_TICKER_PATTERNS:
            if re.fullmatch(pat, ticker, re.I):
                return False
        if row.get("weight_pct", 0) <= 0:
            return False
        return True

    return [h for h in holdings if is_equity(h)]


# ----------------------------------------------------------------------------
# 2. ミネルヴィニ・トレンドテンプレート (8条件)
# ----------------------------------------------------------------------------

def compute_trend_template(df: pd.DataFrame) -> dict:
    """
    df: 1銘柄の日足データ (Open, High, Low, Close, Volume)。約1年+分。
    8条件の定義は一般に公開されているMinervini Trend Templateに準拠。
    条件6の「52週安値からの上昇率」は資料により25%/30%とばらつきがあるため
    ここでは25%を採用(オニミネのように厳密な公開基準ではなく一般的な目安)。
    """
    close = df["Close"].dropna()
    if len(close) < 210:
        return {"error": "insufficient_history"}

    price = close.iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma150 = close.rolling(150).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    sma200_series = close.rolling(200).mean()
    sma200_1m_ago = sma200_series.iloc[-22] if len(sma200_series) >= 222 else None

    low_52w = close.tail(252).min()
    high_52w = close.tail(252).max()

    conditions = {
        "c1_price_above_150_200": bool(price > sma150 and price > sma200),
        "c2_150_above_200": bool(sma150 > sma200),
        "c3_200_trending_up": bool(sma200_1m_ago is not None and sma200 > sma200_1m_ago),
        "c4_50_above_150_200": bool(sma50 > sma150 and sma50 > sma200),
        "c5_price_above_50": bool(price > sma50),
        "c6_price_25pct_above_52w_low": bool(price >= low_52w * 1.25),
        "c7_price_within_25pct_of_52w_high": bool(price >= high_52w * 0.75),
        # c8 (RSレーティング>=70) は fetch_rs_proxy_percentiles() で
        # FFTY銘柄群内の相対比較として別途付与する。
    }
    pass_count_without_rs = sum(1 for v in conditions.values() if v)

    return {
        **conditions,
        "price": round(float(price), 2),
        "sma50": round(float(sma50), 2),
        "sma150": round(float(sma150), 2),
        "sma200": round(float(sma200), 2),
        "low_52w": round(float(low_52w), 2),
        "high_52w": round(float(high_52w), 2),
        "pct_off_52w_high": round(float(100 * (price / high_52w - 1)), 1),
        "pass_count_without_rs": pass_count_without_rs,
    }


def compute_rs_proxy_percentiles(price_frames: dict, lookback_days: int = 252) -> dict:
    """
    本物のIBD RSレーティング(全米国株母集団に対する相対力の百分位)は自前では
    再現できないため、ここではFFTY構成銘柄"内"でのトレーリング1年リターンの
    百分位を代替指標(proxy)として使う。RSレーティング70以上に相当する
    「上位30%」を目安のしきい値とする。
    絶対値としての意味はIBD公式のRSレーティングとは異なる点に注意。
    """
    returns = {}
    for ticker, df in price_frames.items():
        close = df["Close"].dropna()
        if len(close) < lookback_days:
            continue
        returns[ticker] = close.iloc[-1] / close.iloc[-lookback_days] - 1

    if not returns:
        return {}

    series = pd.Series(returns)
    percentiles = series.rank(pct=True) * 100
    return percentiles.round(1).to_dict()


# ----------------------------------------------------------------------------
# 3. 為替レート・予算フィルタ
# ----------------------------------------------------------------------------

def fetch_usdjpy_rate() -> float:
    df = yf.download("JPY=X", period="5d", interval="1d", progress=False)
    close = df["Close"].dropna()
    last = close.iloc[-1]
    # yfinanceのバージョンによりMultiIndex列になり、iloc[-1]がSeries(要素数1)に
    # なることがあるため、item()で素のスカラーを取り出す。
    return float(last.item()) if hasattr(last, "item") else float(last)


# ----------------------------------------------------------------------------
# メイン処理
# ----------------------------------------------------------------------------

SHEET_HEADER = [
    "date", "ticker", "name", "sector", "price_usd", "price_jpy",
    "pass_count_of_8", "pass_all_8", "rs_proxy_percentile",
    "pct_off_52w_high", "within_budget_max", "shares_at_budget_min", "shares_at_budget_max",
    "c1", "c2", "c3", "c4", "c5", "c6", "c7",
]


def run() -> list[list]:
    today = dt.date.today().isoformat()

    raw_holdings = fetch_ffty_holdings()
    holdings = filter_equity_rows(raw_holdings)
    if not holdings:
        print("[warn] FFTY構成銘柄が0件。ページ構造が変わっている可能性あり。", file=sys.stderr)
        return []

    tickers = [h["ticker"] for h in holdings]
    price_frames = {}
    raw = yf.download(tickers, period="2y", interval="1d", group_by="ticker",
                       auto_adjust=False, progress=False, threads=True)
    for t in tickers:
        try:
            price_frames[t] = raw[t].dropna(how="all")
        except Exception:  # noqa: BLE001
            continue

    rs_percentiles = compute_rs_proxy_percentiles(price_frames)
    usdjpy = fetch_usdjpy_rate()

    rows = []
    for h in holdings:
        t = h["ticker"]
        df = price_frames.get(t)
        if df is None or df.empty:
            continue
        tmpl = compute_trend_template(df)
        if "error" in tmpl:
            continue

        rs_pct = rs_percentiles.get(t)
        c8_pass = bool(rs_pct is not None and rs_pct >= 70)
        pass_count_of_8 = tmpl["pass_count_without_rs"] + (1 if c8_pass else 0)
        price_jpy = tmpl["price"] * usdjpy
        # 1株が高すぎて予算上限(100万円)でも買えない銘柄だけを除外する
        # (下限30万円は「1株価格」ではなく「1銘柄への投資額の目安」なので
        #  1株価格のフィルタには使わない。参考情報として株数だけ併記する)
        within_budget = bool(price_jpy <= BUDGET_JPY_MAX)
        shares_at_min = int(BUDGET_JPY_MIN // price_jpy) if price_jpy > 0 else None
        shares_at_max = int(BUDGET_JPY_MAX // price_jpy) if price_jpy > 0 else None

        rows.append([
            today, t, h["name"], h["sector"],
            tmpl["price"], round(price_jpy),
            pass_count_of_8, bool(pass_count_of_8 == 8),
            rs_pct, tmpl["pct_off_52w_high"], within_budget,
            shares_at_min, shares_at_max,
            tmpl["c1_price_above_150_200"], tmpl["c2_150_above_200"],
            tmpl["c3_200_trending_up"], tmpl["c4_50_above_150_200"],
            tmpl["c5_price_above_50"], tmpl["c6_price_25pct_above_52w_low"],
            tmpl["c7_price_within_25pct_of_52w_high"],
        ])

    # 合格数が多い順に並べる (トレンドテンプレート適合度が高い順)
    rows.sort(key=lambda r: r[6], reverse=True)
    return rows


if __name__ == "__main__":
    import os

    result_rows = run()
    for r in result_rows:
        print(r)

    try:
        from sheets_writer import append_rows, ensure_worksheet

        sheet_id = os.environ.get("SPREADSHEET_ID")
        if sheet_id and result_rows:
            ensure_worksheet(sheet_id, "FFTY_VCP候補トラッカー", SHEET_HEADER)
            append_rows(sheet_id, "FFTY_VCP候補トラッカー", result_rows)
            print("[info] Google Sheetsへの書き込み完了", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Sheets書き込みスキップ: {e}", file=sys.stderr)
