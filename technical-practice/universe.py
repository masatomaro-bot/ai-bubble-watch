"""
universe.py
============
「市場の幅(ブレッドス)」の母集団をS&P500(約500銘柄)より広げるためのユニバース
取得ヘルパー。

オニミネサイトのブレッドス表示は「約4461銘柄」という注記があり、これは
S&P500よりずっと広い米国上場銘柄全体に近い規模。無料でここに近い規模の
ユニバースを毎日再現するには、個別に数千銘柄をスクレイピングするのではなく、
「大手ETFが毎日公開している構成銘柄CSV」を使うのが最も安定していると判断した。

採用したソース: iShares Russell 3000 ETF (IWV) の保有銘柄CSV。
  - Russell 3000は米国株式市場時価総額の約98%をカバーする、公開されている
    ベンチマークの中では最も母集団が広いものの一つ。
  - iSharesは運用会社として毎営業日、保有銘柄の全量CSVをウェブサイト上で
    無料公開している(規制上の開示義務に基づくもの)。

■ 実機検証の結果 (2026-09-13, GitHub Actions)
iShares(IWV/ITOT)のCSV取得は、実際に動かしたところ両方とも
「ヘッダー行が見つからない」で失敗した(ヘッダー行が見つからない = 想定した
CSVの中身が返ってきていない、という意味。iShares側がボット対策のチャレンジ
ページ等を返している可能性がある)。原因を次回の実行ログで特定できるよう、
失敗時にレスポンス本文の先頭部分をログに出すようにしてある。
このため、iSharesが使えない場合の次点としてNASDAQ Trader(NASDAQが公式に
提供する、システム利用者向けのシンボル一覧ファイル。プログラムからの
取得を想定した単純なパイプ区切りテキストで、iSharesのような一般向け
Webページより機械的な取得に向いている)を追加した。
それでも全滅した場合は最終的にS&P500(get_sp500_tickers)にフォールバックする。
取得に失敗しても例外は投げず、必ずどれか(または空リスト)を返す設計。
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request

# iShares Russell 3000 ETF (IWV) の保有銘柄CSV配布URL。
# iSharesの商品ページURLパターンは "https://www.ishares.com/us/products/<製品ID>/<商品名>/<共通パラメータ>.ajax?fileType=csv&fileName=<ファイル名>&dataType=fund"
# という形式で、複数の公開資料・第三者ツールで広く使われている既知の形式だが、
# 数値ID部分がiShares側の内部管理番号のため、変更される可能性がある。
IWV_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239714/"
    "ishares-russell-3000-etf/1467271812596.ajax"
    "?fileType=csv&fileName=IWV_holdings&dataType=fund"
)

# 万一IWVが取得できない場合の次点候補(iShares Core S&P Total US Stock Market ETF)。
ITOT_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239724/"
    "ishares-core-sp-total-us-stock-market-etf/1467271812596.ajax"
    "?fileType=csv&fileName=ITOT_holdings&dataType=fund"
)

# iSharesが両方とも使えない場合の次点候補。NASDAQが自ら「システム利用者
# (プログラム)向け」として公開しているシンボル一覧で、パイプ("|")区切りの
# 単純なテキスト形式。マーケティングサイトのようなボット対策が入りにくい
# 想定だが、これも未検証(GitHub Actions等の実行環境で要確認)。
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

USER_AGENT = "Mozilla/5.0"

# iSharesのCSVは先頭に商品説明・基準日などのメタ情報行が数行入っており、
# その後に本当のヘッダー行(Ticker,Name,Sector,Asset Class,...)が続く形式。
# メタ情報の行数はファイルによって変動しうるため、固定行数スキップではなく
# 「Tickerという語で始まる行」を探してそこをヘッダー行として扱う。
_HEADER_PREFIX = "ticker"

# 現金・先物・その他非株式の構成要素を除外するためのAsset Class値。
_EQUITY_ASSET_CLASS_VALUES = {"equity"}


def _parse_ishares_holdings_csv(raw_text: str) -> list[str]:
    lines = raw_text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(_HEADER_PREFIX):
            header_idx = i
            break
    if header_idx is None:
        # 原因調査用に、実際に何が返ってきたか(HTMLエラーページ、ボット対策
        # チャレンジページ等の可能性がある)を先頭200文字だけログに残す。
        snippet = " ".join(raw_text[:200].split())
        raise ValueError(
            "iSharesホールディングスCSVのヘッダー行が見つからない"
            f"(フォーマット変更の可能性)。レスポンス冒頭: {snippet!r}"
        )

    csv_body = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(csv_body))
    if not reader.fieldnames:
        raise ValueError("iSharesホールディングスCSVの列が読み取れない")

    ticker_col = next((c for c in reader.fieldnames if c.strip().lower() == "ticker"), None)
    asset_class_col = next(
        (c for c in reader.fieldnames if "asset class" in c.strip().lower()), None
    )
    if ticker_col is None:
        raise ValueError(f"Ticker列が見つからない: columns={reader.fieldnames}")

    tickers: list[str] = []
    for row in reader:
        ticker = (row.get(ticker_col) or "").strip().upper()
        if not ticker:
            continue
        if asset_class_col is not None:
            asset_class = (row.get(asset_class_col) or "").strip().lower()
            if asset_class and asset_class not in _EQUITY_ASSET_CLASS_VALUES:
                continue
        # "-" や "CASH" 等のプレースホルダー、ドル記号付き等の非ティッカー値を除外
        if not ticker.replace(".", "").replace("-", "").isalnum():
            continue
        if ticker in {"USD", "CASH", "NET", "N/A"}:
            continue
        # Yahoo Finance形式に合わせてクラス株の "." を "-" に変換 (例: BRK.B -> BRK-B)
        ticker = ticker.replace(".", "-")
        tickers.append(ticker)

    # 重複除去(順序保持)
    return list(dict.fromkeys(tickers))


def sample_tickers(tickers: list[str], max_tickers: int | None) -> list[str]:
    """検証用にmax_tickersで母集団を絞る際、先頭からの切り出しではなく
    固定シードのランダムサンプリングを使う。

    NASDAQ Trader・S&P500(Wikipedia)いずれのティッカー一覧もアルファベット順
    に近い並びのため、単純に先頭N件を取ると「ティッカーがA〜B台の銘柄」に
    偏ってしまい、母集団の代表性が失われる(実機検証2026-09-13で、Market
    LeaderがA始まりの銘柄ばかりになる形で発現した)。本番運用ではmax_tickers
    を指定しない(全件使う)ことを想定しており、これはあくまで検証時の絞り込み
    を代表性のあるサンプルにするための処理。
    """
    if not max_tickers or max_tickers >= len(tickers):
        return tickers
    import random

    return random.Random(42).sample(tickers, max_tickers)


def _fetch_url(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8-sig", errors="replace")


# nasdaqtrader.comのシンボル一覧は "|" 区切り、末尾に
# "File Creation Time: ..." という注記行が付く。ETF・テスト銘柄はブレッドス
# 計算の母集団としてはノイズになるため除外する。
def _parse_nasdaq_listed_txt(raw_text: str, symbol_col: str, is_etf_col: str | None, is_test_col: str | None) -> list[str]:
    lines = [ln for ln in raw_text.splitlines() if ln.strip() and not ln.startswith("File Creation Time")]
    if not lines:
        return []
    reader = csv.DictReader(lines, delimiter="|")
    if not reader.fieldnames or symbol_col not in reader.fieldnames:
        raise ValueError(f"想定した列が見つからない: columns={reader.fieldnames}")

    tickers: list[str] = []
    for row in reader:
        symbol = (row.get(symbol_col) or "").strip().upper()
        if not symbol:
            continue
        if is_etf_col and (row.get(is_etf_col) or "").strip().upper() == "Y":
            continue
        if is_test_col and (row.get(is_test_col) or "").strip().upper() == "Y":
            continue
        if not symbol.replace(".", "").replace("-", "").isalnum():
            continue
        tickers.append(symbol.replace(".", "-"))
    return list(dict.fromkeys(tickers))


def _get_nasdaqtrader_tickers() -> list[str]:
    """NASDAQ Trader公式のシンボル一覧(NASDAQ上場 + その他取引所上場)から、
    ETF・テスト銘柄を除いた普通株ティッカーの一覧を返す。取得失敗時は
    空リストを返す(呼び出し側でさらにフォールバックする)。
    """
    tickers: list[str] = []
    try:
        raw = _fetch_url(NASDAQ_LISTED_URL)
        tickers += _parse_nasdaq_listed_txt(raw, "Symbol", "ETF", "Test Issue")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] NASDAQ Trader一覧取得失敗 (nasdaqlisted): {e}", file=sys.stderr)

    try:
        raw = _fetch_url(OTHER_LISTED_URL)
        tickers += _parse_nasdaq_listed_txt(raw, "ACT Symbol", "ETF", "Test Issue")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] NASDAQ Trader一覧取得失敗 (otherlisted): {e}", file=sys.stderr)

    return list(dict.fromkeys(tickers))


def get_broad_market_tickers(max_tickers: int | None = None) -> tuple[list[str], str]:
    """広い米国株ユニバースを返す。

    優先順位: iShares IWV(Russell3000) -> iShares ITOT -> NASDAQ Trader公式
    シンボル一覧(ETF/テスト銘柄除外)。すべて失敗した場合は空リストと
    "failed" を返す(呼び出し側でS&P500にさらにフォールバックすることを想定)。

    戻り値: (tickers, source_label)
    """
    for url, label in [(IWV_HOLDINGS_URL, "iwv"), (ITOT_HOLDINGS_URL, "itot")]:
        try:
            raw = _fetch_url(url)
            tickers = _parse_ishares_holdings_csv(raw)
            if not tickers:
                continue
            return sample_tickers(tickers, max_tickers), label
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 広域ユニバース取得失敗 ({label}): {e}", file=sys.stderr)
            continue

    tickers = _get_nasdaqtrader_tickers()
    if tickers:
        return sample_tickers(tickers, max_tickers), "nasdaqtrader"

    return [], "failed"
