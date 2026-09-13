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

■ 重要な注意 (このサンドボックスでは未検証)
このリポジトリの開発環境は外部ネットワークに出られないため、下記URLが
実際に生きているか、CSVのフォーマット(先頭の説明行の行数や列名)が
想定通りかは、GitHub Actions等の実行環境で初回実行して必ず確認すること。
iShares側がURLやCSV仕様を変更した場合はここの修正が必要になる。
取得に失敗した場合は例外を投げず、警告を出してS&P500(get_sp500_tickers)に
自動的にフォールバックする設計にしている。
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
        raise ValueError("iSharesホールディングスCSVのヘッダー行が見つからない(フォーマット変更の可能性)")

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


def _fetch_url(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8-sig", errors="replace")


def get_broad_market_tickers(max_tickers: int | None = None) -> tuple[list[str], str]:
    """Russell 3000(IWV)構成銘柄をベースにした広い米国株ユニバースを返す。

    戻り値: (tickers, source_label)
    取得に失敗した場合は空リストと "failed" を返す(呼び出し側でS&P500に
    フォールバックすることを想定)。
    """
    for url, label in [(IWV_HOLDINGS_URL, "iwv"), (ITOT_HOLDINGS_URL, "itot")]:
        try:
            raw = _fetch_url(url)
            tickers = _parse_ishares_holdings_csv(raw)
            if not tickers:
                continue
            if max_tickers:
                tickers = tickers[:max_tickers]
            return tickers, label
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 広域ユニバース取得失敗 ({label}): {e}", file=sys.stderr)
            continue

    return [], "failed"
