"""
weekly.py
=========
「週間ウォッチ」用の週次データ(2026-11-07追加)。

地合いウォッチ(毎日)とは別に、更新が週1回の指標をまとめて docs/data/weekly.json に書き出す。
画面(docs/weekly-watch.js)は重要度の高い順に表示する:

  1. 分母(利益予想)  FactSet Earnings Insight … 予想増益率の修正・ガイダンス件数・予想PER
  2. 信用             FRED BAMLH0A0HYM2       … ハイイールド社債の上乗せ金利(OAS)
  3. 心理             AAII Sentiment Survey   … 個人投資家の強気・弱気 / VIX(yfinance)
  4. 景気             FRED GDPNOW             … アトランタ連銀GDPNowの推計
  5. 建玉             CFTC 建玉明細(先物のみ・Legacy) … 金・原油の大口投機筋の買い越し

データの取り方(A+Bの分担):
  A) このスクリプト(GitHub Actions、土曜朝と日曜夜)が公開データを機械的に取得する。
  B) 日曜夕方のClaudeの予定タスクが、Aで取れなかった値(サイトがActionsを拒否した場合など)と
     「今週の一文」「警戒③(AI以外のセクターへの下方修正の広がり)」の判定を、
     Googleスプレッドシートの「週間ウォッチ_手入力」タブに1行追加する。
     このスクリプトはそのタブを読み、Aで取れなかった項目だけを埋める(Aの値は上書きしない)。

数字を作らない方針:
  取得できなかった値は None のままにし、画面で「取得できなかった」と表示する。
  目安線は公表値(FactSetの5年・10年平均)か計算値(HY OASの5年平均)だけを使う。
  警戒ランプのしきい値は「データ」ではなく判定ルールで、画面に定義を明記する。
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
OUT_PATH = os.path.join(_REPO_ROOT, "docs", "data", "weekly.json")
FACTSET_CACHE = os.path.join(_REPO_ROOT, "docs", "data", "weekly_factset.json")

USER_AGENT = "Mozilla/5.0 (ai-bubble-watch weekly)"
FETCH_ERRORS: dict = {}

MANUAL_TAB = "週間ウォッチ_手入力"
MANUAL_HEADER = [
    "週(金曜日付 YYYY-MM-DD)", "今週の一文", "警戒3(AI以外へ下方修正の広がり) 点灯/未点灯", "警戒3の根拠",
    "AAII強気%", "AAII中立%", "AAII弱気%", "AAII調査週(YYYY-MM-DD)",
    "FactSet予想PER", "FactSet5年平均", "FactSet10年平均", "ガイダンス対象四半期", "ガイダンス下方社数", "ガイダンス上方社数",
    "出典メモ", "記入者",
]
AUTO_TAB = "週間ウォッチ"
AUTO_HEADER = [
    "週(金曜日付)", "FactSet号", "予想PER", "5年平均", "10年平均", "次四半期", "次四半期の予想増益率%",
    "暦年", "暦年の予想増益率%", "ガイダンス下方", "ガイダンス上方", "予想超過%",
    "HY OAS%", "HY OAS 5年平均%", "AAII強気-弱気pt", "VIX", "GDPNow%", "金 投機筋ネット", "原油 投機筋ネット",
    "警戒1", "警戒2", "警戒3", "警戒4",
]


def _err(key: str, e: Exception | str) -> None:
    msg = e if isinstance(e, str) else f"{type(e).__name__}: {e}"
    k = os.environ.get("FRED_API_KEY", "").strip()
    if k:
        msg = msg.replace(k, "***")
    FETCH_ERRORS[key] = msg[:200]
    print(f"[warn] {key}: {msg}", file=sys.stderr)


def _get_bytes(url: str, timeout: int = 30, tries: int = 2) -> bytes:
    import urllib.request
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last = e
            # 404は「その日付の号がない」なので再試行しない
            if getattr(e, "code", None) == 404:
                break
            if i < tries - 1:
                time.sleep(2 * (i + 1))
    raise last


def last_friday(today: date | None = None) -> date:
    today = today or datetime.now(timezone.utc).date()
    return today - timedelta(days=(today.weekday() - 4) % 7)


def _series_points(s: pd.Series | None, digits: int = 2) -> dict | None:
    if s is None or s.empty:
        return None
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [round(float(v), digits) for v in s]}


# ---------------------------------------------------------------------------
# 1. FactSet Earnings Insight(週次PDF、無料)
# ---------------------------------------------------------------------------
FACTSET_URL = (
    "https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/"
    "Earnings%20Insight/EarningsInsight_{mmddyy}{suffix}.pdf"
)

_NUM = r"(-?\d+(?:\.\d+)?)"


def _clean(text: str) -> str:
    """PDFの改行・ハイフネーション・連続空白をならして正規表現を当てやすくする。"""
    t = text.replace("’", "'").replace("“", '"').replace("”", '"')
    # PDFから取り出した文字には、見た目は同じでも別の文字(ハイフンや空白の異体字)が混ざる。
    # これがあると「12-month」「Q4 2026」に正規表現が当たらず、項目が丸ごと取れない週が出ていた(2026-11-07修正)。
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212", "\u00ad"):
        t = t.replace(ch, "-")
    for ch in ("\xa0", "\u2002", "\u2003", "\u2009", "\u200a", "\u202f", "\u3000"):
        t = t.replace(ch, " ")
    t = t.replace("\u200b", "").replace("\ufb01", "fi").replace("\ufb02", "fl")
    t = re.sub(r"-\s*\n\s*", "-", t)
    t = re.sub(r"\s+", " ", t)
    return t


def parse_factset_text(text: str) -> dict:
    """Earnings Insight の Key Metrics の文から数値を抜き出す。見つからない項目は None。

    抜き出す文の形(2025〜2026年の号で確認した書き方):
      "The forward 12-month P/E ratio for the S&P 500 is 18.7. This P/E ratio is below the 5-year average (19.8)
       and below the 10-year average (19.1)."
      "For Q4 2026, 19 S&P 500 companies have issued negative EPS guidance and 28 S&P 500 companies have issued
       positive EPS guidance."
      "... 82% of S&P 500 companies have reported a positive EPS surprise ..."
      "For Q4 2026, analysts are projecting earnings growth of 18.1% ..."  (次四半期の予想増益率)
      "For CY 2027, analysts are projecting earnings growth of 15.4% ..."  (暦年の予想増益率)
    """
    t = _clean(text)
    out: dict = {
        "pe": None, "pe_avg5": None, "pe_avg10": None,
        "guidance_quarter": None, "guidance_negative": None, "guidance_positive": None,
        "beat_pct": None,
        "quarters": {}, "years": {},
    }
    m = re.search(
        r"forward 12-month P/E ratio(?: for the S&P 500)? is " + _NUM + r"\.?.{0,160}?5-year average \(" + _NUM
        + r"\).{0,80}?10-year average \(" + _NUM + r"\)",
        t, re.I,
    )
    if m:
        out["pe"], out["pe_avg5"], out["pe_avg10"] = float(m.group(1)), float(m.group(2)), float(m.group(3))
    else:
        m = re.search(r"forward 12-month P/E ratio(?: for the S&P 500)? is " + _NUM, t, re.I)
        if m:
            out["pe"] = float(m.group(1))

    m = re.search(
        r"For (Q[1-4] \d{4}),? (\d+) S&P 500 companies have issued negative EPS guidance and (\d+) S&P 500 "
        r"companies have issued positive EPS guidance",
        t, re.I,
    )
    if m:
        out["guidance_quarter"] = m.group(1)
        out["guidance_negative"], out["guidance_positive"] = int(m.group(2)), int(m.group(3))

    m = re.search(r"(\d+(?:\.\d+)?)% of (?:the )?S&P 500 companies (?:have )?reported (?:a )?positive EPS surprise", t, re.I)
    if m:
        out["beat_pct"] = float(m.group(1))

    # 予想増益率。号によって書き方が2通りある：
    #   "For Q4 2026, analysts are projecting earnings growth of 28.4% ..."
    #   "For Q4 2026, the estimated (year-over-year) earnings growth rate for the S&P 500 is 28.4%"
    # PDFの段組みで文の途中に別の文字列が挟まることがあるため、「For 期」から増益率までの間は
    # 次の「For 」が出てこない範囲(200字まで)を許す。売上(revenue)の伸び率を拾わないよう earnings を必須にする。
    gap = r"(?:(?!For ).){0,200}?"
    for per, g in re.findall(
        r"For (Q[1-4] \d{4}|CY ?\d{4}),?" + gap + r"earnings growth (?:rate )?(?:of|for the S&P 500 is|is) " + _NUM + "%",
        t, re.I,
    ):
        if per.upper().startswith("CY"):
            out["years"].setdefault("CY" + per[-4:], float(g))
        else:
            out["quarters"].setdefault(per.upper(), float(g))
    return out


def parse_coverage(p: dict) -> list[str]:
    """号から読み取れなかった項目の名前(画面とエラー欄に出す)。"""
    miss = []
    if p.get("pe") is None:
        miss.append("予想PER")
    if p.get("guidance_negative") is None:
        miss.append("ガイダンス件数")
    if not p.get("quarters"):
        miss.append("四半期の予想増益率")
    if not p.get("years"):
        miss.append("暦年の予想増益率")
    return miss


PARSER_VERSION = 2  # 解析方法を変えたら上げる。古い版で読んだ週はキャッシュにあっても取り直す


def _pdf_text(raw: bytes, max_pages: int = 40) -> str:
    """全ページ(40ページまで)の文字を取り出す。以前は先頭6ページだけで、増益率の文が後ろのページに
    ある号を取りこぼしていた。段組みの読み順が崩れる号に備え、レイアウト維持の取り出しも後ろに足す。"""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    pages = reader.pages[:max_pages]
    plain = "\n".join((p.extract_text() or "") for p in pages)
    try:
        layout = "\n".join((p.extract_text(extraction_mode="layout") or "") for p in pages)
    except Exception:  # noqa: BLE001  古いpypdfにはlayoutモードがない
        layout = ""
    return plain + "\n\n" + layout


def _merge_parsed(a: dict, b: dict) -> dict:
    """2通りの取り出し方の結果を合わせる(先に取れた値を優先)。"""
    out = dict(a)
    for k, v in b.items():
        if k in ("quarters", "years"):
            out[k] = {**v, **(a.get(k) or {})}
        elif out.get(k) is None:
            out[k] = v
    return out


def fetch_factset_issue(friday: date) -> dict | None:
    """その週の号を探す。通常は金曜号。祝日週は木曜などにずれ、「A」付きの臨時号もあるため順に試す。"""
    candidates = [friday, friday - timedelta(days=1), friday - timedelta(days=2), friday + timedelta(days=1)]
    for d in candidates:
        for suffix in ("", "A"):
            url = FACTSET_URL.format(mmddyy=d.strftime("%m%d%y"), suffix=suffix)
            try:
                raw = _get_bytes(url, timeout=40, tries=1)
            except Exception as e:  # noqa: BLE001
                if getattr(e, "code", None) == 404:
                    continue
                _err(f"FactSet:{d.isoformat()}{suffix}", e)
                continue
            if not raw.startswith(b"%PDF"):
                continue
            try:
                text = _pdf_text(raw)
                plain, _, layout = text.partition("\n\n")
                parsed = _merge_parsed(parse_factset_text(plain), parse_factset_text(layout)) if layout else parse_factset_text(text)
            except Exception as e:  # noqa: BLE001
                _err(f"FactSet解析:{d.isoformat()}{suffix}", e)
                return None
            parsed.update({"week": friday.isoformat(), "issue_date": d.isoformat(), "url": url,
                           "parser": PARSER_VERSION, "missing": parse_coverage(parsed)})
            return parsed
    return None


def load_factset_cache(path: str = FACTSET_CACHE) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def update_factset(weeks_back: int, cache: dict, today: date | None = None) -> dict:
    """直近 weeks_back 週のうち、キャッシュにない週だけ取りに行く(初回は過去データの埋め戻し)。
    直近2週は数字の訂正がありうるので毎回取り直す。"""
    fri = last_friday(today)
    misses = 0
    for i in range(weeks_back):
        wk = fri - timedelta(weeks=i)
        key = wk.isoformat()
        if key in cache and i >= 2 and cache[key].get("parser") == PARSER_VERSION and not cache[key].get("missing"):
            continue
        issue = fetch_factset_issue(wk)
        if issue:
            cache[key] = issue
            misses = 0
            if i == 0 and issue.get("missing"):
                _err("FactSet:最新号の解析", f"{issue['issue_date']}号から読み取れなかった項目：{'・'.join(issue['missing'])}")
        else:
            misses += 1
            if i == 0:
                _err("FactSet:最新号", f"{key}の週の号が見つからない(未公開か、URLの形が変わった可能性)")
        time.sleep(0.5)
        if misses >= 8 and i > 8:  # 連続で見つからなければ打ち切り(URLの形が古い号で違う等)
            break
    return cache


def factset_rows(cache: dict) -> list[dict]:
    rows = [v for _, v in sorted(cache.items())]
    return rows


def revision_series(rows: list[dict], kind: str) -> dict:
    """次四半期(kind='quarter')または来年(kind='year')の予想増益率を、週ごとに「その号で一番近い将来」の
    期について並べる。期が切り替わった週は線が途切れるよう、期ラベルも返す。"""
    dates, values, labels = [], [], []
    for r in rows:
        d = r.get("issue_date") or r.get("week")
        if kind == "quarter":
            src = r.get("quarters") or {}
            # ガイダンスの対象四半期＝号が「次の四半期」として扱っている期
            label = r.get("guidance_quarter") if r.get("guidance_quarter") in src else (sorted(src)[-1] if src else None)
        else:
            src = r.get("years") or {}
            # 「来年」＝号の発行年の翌年。号に載っている一番先の年を取る方式だと、来年の値が読めなかった週に
            # 今年(CY2026)の値が「来年」として表示されてしまっていた(2026-11-07修正)。
            label = f"CY{int(str(d)[:4]) + 1}" if d else None
        dates.append(d)
        labels.append(label)
        values.append(src.get(label) if label else None)
    return {"dates": dates, "values": values, "labels": labels}


# ---------------------------------------------------------------------------
# 2. 信用・景気(FRED)
# ---------------------------------------------------------------------------
def build_hy_oas(fetch=None) -> dict | None:
    if fetch is None:
        from macro import fetch_fred as fetch
    s = fetch("BAMLH0A0HYM2")
    if s is None or s.empty:
        _err("FRED:BAMLH0A0HYM2", "取得できず")
        return None
    since = s.index.max() - pd.DateOffset(years=5)
    s5 = s[s.index >= since]
    wk = s5.resample("W-FRI").last().dropna()
    avg5 = round(float(s5.mean()), 2)
    latest = round(float(s.iloc[-1]), 2)

    def chg(weeks):
        if len(wk) <= weeks:
            return None
        return round(float(wk.iloc[-1] - wk.iloc[-1 - weeks]), 2)

    return {
        **_series_points(wk),
        "latest": latest,
        "as_of": s.index[-1].strftime("%Y-%m-%d"),
        "avg_5y": avg5,
        "min_52w": round(float(s[s.index >= s.index.max() - pd.DateOffset(weeks=52)].min()), 2),
        "chg_1w": chg(1),
        "chg_4w": chg(4),
        "source": "FRED BAMLH0A0HYM2(ICE BofA US High Yield Index Option-Adjusted Spread)",
    }


def build_gdpnow(fetch=None) -> dict | None:
    if fetch is None:
        from macro import fetch_fred as fetch
    s = fetch("GDPNOW")
    if s is None or s.empty:
        _err("FRED:GDPNOW", "取得できず")
        return None
    s = s[s.index >= s.index.max() - pd.DateOffset(years=5)]
    return {
        **_series_points(s, 1),
        "latest": round(float(s.iloc[-1]), 1),
        "quarter_start": s.index[-1].strftime("%Y-%m-%d"),
        "source": "FRED GDPNOW(アトランタ連銀GDPNow、四半期ごとの推計。実質GDP成長率・年率)",
    }


# ---------------------------------------------------------------------------
# 3. 心理(AAII、VIX)
# ---------------------------------------------------------------------------
AAII_XLS = "https://www.aaii.com/files/surveys/sentiment.xls"


def fetch_aaii() -> list[dict]:
    """AAIIの公開Excel。Actionsからは拒否されることがあるため、失敗したら空を返し手入力タブで補う。"""
    try:
        raw = _get_bytes(AAII_XLS, timeout=30, tries=1)
        df = pd.read_excel(io.BytesIO(raw), header=None)
    except Exception as e:  # noqa: BLE001
        _err("AAII", e)
        return []
    rows = []
    for _, r in df.iterrows():
        d = pd.to_datetime(r.iloc[0], errors="coerce")
        try:
            bull, neu, bear = (float(r.iloc[1]), float(r.iloc[2]), float(r.iloc[3]))
        except (TypeError, ValueError):
            continue
        if pd.isna(d) or any(pd.isna(x) for x in (bull, neu, bear)):
            continue
        scale = 100 if bull <= 1.0 and bear <= 1.0 else 1  # 0.341形式なら%へ
        rows.append({"date": d.strftime("%Y-%m-%d"), "bull": round(bull * scale, 1),
                     "neutral": round(neu * scale, 1), "bear": round(bear * scale, 1), "source": "AAII(公開Excel)"})
    rows.sort(key=lambda x: x["date"])
    return rows[-260:]


def build_vix(download=None) -> dict | None:
    try:
        if download is None:
            import yfinance as yf
            df = yf.download("^VIX", period="2y", interval="1d", progress=False, auto_adjust=False)
        else:
            df = download("^VIX")
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        wk = close.dropna().resample("W-FRI").last().dropna()
        wk = wk[wk.index >= wk.index.max() - pd.DateOffset(weeks=104)]
        return {**_series_points(wk), "latest": round(float(close.dropna().iloc[-1]), 2),
                "as_of": close.dropna().index[-1].strftime("%Y-%m-%d"), "source": "Yahoo Finance(^VIX)"}
    except Exception as e:  # noqa: BLE001
        _err("VIX", e)
        return None


# ---------------------------------------------------------------------------
# 4. 建玉(CFTC 公開API・キー不要)
# ---------------------------------------------------------------------------
CFTC_API = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"  # Legacy・先物のみ
CFTC_CODES = {"gold": ("088691", "金(COMEX)"), "crude": ("067651", "原油WTI(NYMEX)")}


def fetch_cftc(code: str, weeks: int = 260) -> pd.DataFrame | None:
    q = urllib.parse.urlencode({
        "cftc_contract_market_code": code,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(weeks),
        "$select": "report_date_as_yyyy_mm_dd,noncomm_positions_long_all,noncomm_positions_short_all,open_interest_all",
    })
    try:
        rows = json.loads(_get_bytes(f"{CFTC_API}?{q}", timeout=40).decode("utf-8"))
        df = pd.DataFrame(rows)
        if df.empty:
            raise ValueError("データなし")
        df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])
        for c in ("noncomm_positions_long_all", "noncomm_positions_short_all", "open_interest_all"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.sort_values("date")
    except Exception as e:  # noqa: BLE001
        _err(f"CFTC:{code}", e)
        return None


def build_cftc(fetcher=fetch_cftc) -> dict:
    out = {}
    for key, (code, label) in CFTC_CODES.items():
        df = fetcher(code)
        if df is None or df.empty:
            out[key] = None
            continue
        net = df["noncomm_positions_long_all"] - df["noncomm_positions_short_all"]
        pct_oi = 100 * net / df["open_interest_all"]
        out[key] = {
            "label": label,
            "dates": [d.strftime("%Y-%m-%d") for d in df["date"]],
            "net": [int(v) for v in net],
            "pct_oi": [round(float(v), 1) for v in pct_oi],
            "latest_net": int(net.iloc[-1]),
            "chg_1w": int(net.iloc[-1] - net.iloc[-2]) if len(net) > 1 else None,
            "latest_long": int(df["noncomm_positions_long_all"].iloc[-1]),
            "latest_short": int(df["noncomm_positions_short_all"].iloc[-1]),
            "as_of": df["date"].iloc[-1].strftime("%Y-%m-%d"),
            "max_5y": int(net.max()), "min_5y": int(net.min()),
            "source": f"CFTC 建玉明細(Legacy・先物のみ、コード{code})",
        }
    return out


# ---------------------------------------------------------------------------
# 5. 手入力タブ(Claudeの日曜タスクが書く)
# ---------------------------------------------------------------------------
def _num(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(str(v).replace("%", "").replace(",", "").strip())
    except ValueError:
        return None


def read_manual_rows() -> list[dict]:
    sid = os.environ.get("SPREADSHEET_ID", "").strip()
    if not sid or not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        return []
    try:
        import sheets_writer as sw
        sw.ensure_worksheet(sid, MANUAL_TAB, MANUAL_HEADER)
        ws = sw._get_client().open_by_key(sid).worksheet(MANUAL_TAB)
        values = ws.get_all_values()
    except Exception as e:  # noqa: BLE001
        _err("Sheets:手入力タブ", e)
        return []
    rows = []
    for v in values[1:]:
        v = (v + [""] * len(MANUAL_HEADER))[: len(MANUAL_HEADER)]
        if not v[0].strip():
            continue
        rows.append({
            "week": v[0].strip(), "summary": v[1].strip(), "warn3": v[2].strip(), "warn3_reason": v[3].strip(),
            "aaii_bull": _num(v[4]), "aaii_neutral": _num(v[5]), "aaii_bear": _num(v[6]), "aaii_date": v[7].strip(),
            "pe": _num(v[8]), "pe_avg5": _num(v[9]), "pe_avg10": _num(v[10]),
            "guidance_quarter": v[11].strip() or None, "guidance_negative": _num(v[12]), "guidance_positive": _num(v[13]),
            "note": v[14].strip(), "by": v[15].strip(),
        })
    rows.sort(key=lambda r: r["week"])
    return rows


def merge_manual_into_factset(cache: dict, manual: list[dict]) -> dict:
    """Aで取れなかった週・項目だけ、手入力の値で埋める(Aの値は上書きしない)。"""
    for m in manual:
        wk = m["week"]
        if m.get("pe") is None and m.get("guidance_negative") is None:
            continue
        row = cache.setdefault(wk, {"week": wk, "issue_date": wk, "url": None, "quarters": {}, "years": {}})
        filled = False
        for k in ("pe", "pe_avg5", "pe_avg10", "guidance_quarter", "guidance_negative", "guidance_positive"):
            if row.get(k) is None and m.get(k) is not None:
                row[k] = int(m[k]) if k.startswith("guidance_") and k != "guidance_quarter" else m[k]
                filled = True
        if filled:
            row["filled_by_manual"] = True
    return cache


def merge_manual_into_aaii(aaii: list[dict], manual: list[dict]) -> list[dict]:
    have = {r["date"] for r in aaii}
    for m in manual:
        if m.get("aaii_bull") is None or m.get("aaii_bear") is None:
            continue
        d = m.get("aaii_date") or m["week"]
        if d in have:
            continue
        aaii.append({"date": d, "bull": m["aaii_bull"], "neutral": m.get("aaii_neutral"), "bear": m["aaii_bear"],
                     "source": "手入力(日曜の予定タスクがAAIIサイトから転記)"})
        have.add(d)
    aaii.sort(key=lambda r: r["date"])
    return aaii


# ---------------------------------------------------------------------------
# 6. 警戒ランプ(判定ルール。しきい値は画面に明記する)
# ---------------------------------------------------------------------------
def lamp_eps_revision(q: dict, y: dict) -> dict:
    """警戒①：予想増益率(次四半期・来年)が前週より下がったか。
    比べるのは「最新号」と「その1つ前の号」だけ。どちらかで値が読めなかった週や、期が切り替わった週は比べない。
    (以前は値のある最後の2点を比べていたため、数か月前の値どうしの差で判定してしまうことがあった。2026-11-07修正)"""
    def last_move(s):
        n = len(s["values"])
        if n < 2:
            return None
        (v0, l0), (v1, l1) = (s["values"][-2], s["labels"][-2]), (s["values"][-1], s["labels"][-1])
        if v0 is None or v1 is None or l0 != l1:
            return None
        return round(v1 - v0, 2)

    mq, my = last_move(q), last_move(y)
    if mq is None and my is None:
        return {"state": "unknown", "detail": "最新号と前週号で比べられる値がない(読み取れなかった週、または期の切り替わり週)"}
    downs = sum(1 for m in (mq, my) if m is not None and m < 0)
    known = sum(1 for m in (mq, my) if m is not None)
    state = "on" if downs == known and downs > 0 else "watch" if downs > 0 else "off"
    ql, yl = (q["labels"] or [None])[-1], (y["labels"] or [None])[-1]
    return {"state": state, "detail": f"次四半期{f'({ql})' if ql else ''} {_fmt_move(mq)} ／ "
                                      f"来年{f'({yl})' if yl else ''} {_fmt_move(my)}(前週比、%pt)"}


def _fmt_move(v):
    return "比較不可" if v is None else f"{'+' if v > 0 else ''}{v}"


def lamp_guidance(rows: list[dict]) -> dict:
    r = next((x for x in reversed(rows) if x.get("guidance_negative") is not None), None)
    if not r:
        return {"state": "unknown", "detail": "ガイダンス件数を取得できなかった"}
    neg, pos = r["guidance_negative"], r["guidance_positive"]
    return {"state": "on" if neg > pos else "off",
            "detail": f"{r.get('guidance_quarter') or ''} 下方 {neg}社 ／ 上方 {pos}社({r.get('issue_date')}号)"}


def lamp_breadth_of_cuts(manual: list[dict]) -> dict:
    m = next((x for x in reversed(manual) if x.get("warn3")), None)
    if not m:
        return {"state": "unknown", "detail": "日曜の予定タスクの判定待ち"}
    s = "on" if "点灯" in m["warn3"] and "未" not in m["warn3"] else "off"
    return {"state": s, "detail": (m.get("warn3_reason") or "")[:140], "week": m["week"]}


def lamp_credit(hy: dict | None) -> dict:
    """警戒④：HY OASが5年平均を上回れば点灯、4週前より拡大していれば注意。"""
    if not hy:
        return {"state": "unknown", "detail": "HY OASを取得できなかった"}
    if hy["latest"] > hy["avg_5y"]:
        st = "on"
    elif hy.get("chg_4w") is not None and hy["chg_4w"] > 0:
        st = "watch"
    else:
        st = "off"
    return {"state": st, "detail": f"{hy['latest']}%({hy['as_of']}) ／ 5年平均 {hy['avg_5y']}% ／ 4週前比 {_fmt_move(hy.get('chg_4w'))}pt"}


# ---------------------------------------------------------------------------
def build(today: date | None = None, weeks_back: int | None = None) -> dict:
    weeks_back = weeks_back or int(os.environ.get("FACTSET_WEEKS_BACK", "60") or 60)
    cache = update_factset(weeks_back, load_factset_cache(), today)
    manual = read_manual_rows()
    cache = merge_manual_into_factset(cache, manual)
    rows = factset_rows(cache)
    q, y = revision_series(rows, "quarter"), revision_series(rows, "year")

    hy = build_hy_oas()
    aaii = merge_manual_into_aaii(fetch_aaii(), manual)
    vix = build_vix()
    gdp = build_gdpnow()
    cftc = build_cftc()

    lamps = {
        "eps_revision": lamp_eps_revision(q, y),
        "guidance": lamp_guidance(rows),
        "cuts_breadth": lamp_breadth_of_cuts(manual),
        "credit": lamp_credit(hy),
    }
    summary = next((m for m in reversed(manual) if m.get("summary")), None)
    return {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "week": last_friday(today).isoformat(),
        "summary": {"text": summary["summary"], "week": summary["week"]} if summary else None,
        "lamps": lamps,
        "factset": {"rows": rows[-80:], "eps_quarter": q, "eps_year": y},
        "hy_oas": hy,
        "aaii": aaii[-156:],
        "vix": vix,
        "gdpnow": gdp,
        "cftc": cftc,
        "fetch_errors": FETCH_ERRORS,
        "_cache": cache,
    }


def write_outputs(result: dict) -> None:
    from history_store import _sanitize_for_json
    cache = result.pop("_cache")
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(FACTSET_CACHE, "w", encoding="utf-8") as f:
        json.dump(_sanitize_for_json(cache), f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(_sanitize_for_json(result), f, ensure_ascii=False, indent=1)


def sheet_row(result: dict) -> list:
    fr = (result["factset"]["rows"] or [{}])[-1]
    q, y = result["factset"]["eps_quarter"], result["factset"]["eps_year"]
    a = (result["aaii"] or [{}])[-1]
    hy, vix, gdp, c = result["hy_oas"] or {}, result["vix"] or {}, result["gdpnow"] or {}, result["cftc"] or {}
    L = result["lamps"]
    jp = {"on": "点灯", "watch": "注意", "off": "未点灯", "unknown": "不明"}
    return [
        result["week"], fr.get("issue_date"), fr.get("pe"), fr.get("pe_avg5"), fr.get("pe_avg10"),
        (q["labels"] or [None])[-1], (q["values"] or [None])[-1], (y["labels"] or [None])[-1], (y["values"] or [None])[-1],
        fr.get("guidance_negative"), fr.get("guidance_positive"), fr.get("beat_pct"),
        hy.get("latest"), hy.get("avg_5y"),
        round(a["bull"] - a["bear"], 1) if a.get("bull") is not None and a.get("bear") is not None else None,
        vix.get("latest"), gdp.get("latest"),
        (c.get("gold") or {}).get("latest_net"), (c.get("crude") or {}).get("latest_net"),
        jp[L["eps_revision"]["state"]], jp[L["guidance"]["state"]], jp[L["cuts_breadth"]["state"]], jp[L["credit"]["state"]],
    ]


def main() -> int:
    result = build()
    row = sheet_row(result)
    write_outputs(result)
    print(f"[info] weekly.json を書き出し: {OUT_PATH}", file=sys.stderr)
    sid = os.environ.get("SPREADSHEET_ID", "").strip()
    if sid and os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        try:
            import sheets_writer as sw
            sw.ensure_worksheet(sid, AUTO_TAB, AUTO_HEADER)
            sw.upsert_row(sid, AUTO_TAB, ["" if v is None else v for v in row], key_col_index=0)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Sheets書き込み失敗: {e}", file=sys.stderr)
    if FETCH_ERRORS:
        print(f"[info] 取得できなかった項目: {list(FETCH_ERRORS)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
