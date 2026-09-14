"""
yf_retry.py
============
yfinanceの内部キャッシュ(cookie/crumb情報を保持するsqlite DB)への同時アクセスで
"database is locked" エラーが断続的に発生することが、実機のGitHub Actions定期
実行(2026-09-10, 2026-09-14のcron)で確認された。workflow_dispatchの手動実行
では今のところ再現しておらず、原因はスレッド間のロック競合など偶発的なものと
考えられる。一時的なエラーであることが多いため、短い間隔を空けてリトライする。

market_climate.py と ffty_screener.py の双方が yfinance を呼ぶため、循環import
を避けるためにこの共通モジュールに切り出している。
"""

from __future__ import annotations

import sys
import time

import yfinance as yf

MAX_RETRIES = 3
RETRY_BASE_SLEEP_SEC = 2.0


def download_with_retry(*args, **kwargs):
    """yf.download と同じ引数を受け取り、"database is locked" エラーのみ
    リトライする(それ以外の例外はそのまま送出する)。"""
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return yf.download(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            last_error = e
            if "database is locked" not in str(e).lower():
                raise
            sleep_sec = RETRY_BASE_SLEEP_SEC * (2 ** attempt)
            print(
                f"[warn] yfinance取得失敗(database is locked)、{sleep_sec:.0f}秒後にリトライ "
                f"({attempt + 1}/{MAX_RETRIES}): {e}",
                file=sys.stderr,
            )
            time.sleep(sleep_sec)
    raise last_error
