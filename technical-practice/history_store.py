"""
history_store.py
=================
地合い判定の日次結果をJSONスナップショットとしてリポジトリ内に保存する
(「gitをデータベースにする」方式)。

Googleスプレッドシートは表として見るための副次的な出力とし、GitHub Pages
ダッシュボード(docs/index.html)が読む「正」のデータはこのJSON履歴とする。

保存先: docs/data/history/YYYY-MM-DD.json (1日1ファイル)
       docs/data/history/latest.json      (最新日へのコピー)
(docs/ に置くのは、GitHub Pagesを「mainブランチの/docsフォルダ」から配信する
設定にした場合、docs/index.html の静的ダッシュボードが同じ場所から
fetch()できるようにするため。technical-practice/ 配下だとPagesの配信対象
フォルダの外になり、ダッシュボードから読めなくなる)

このモジュール自体はファイルを書き出すところまでで、git add/commit/push は
行わない(GitHub Actionsワークフロー側のステップが担当する)。
"""

from __future__ import annotations

import json
import math
import os

_TECHNICAL_PRACTICE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TECHNICAL_PRACTICE_DIR)
HISTORY_DIR = os.path.join(_REPO_ROOT, "docs", "data", "history")


def _sanitize_for_json(obj):
    """Python標準のjson.dumpsはNaN/InfinityをそのままNaN/Infinityという
    リテラルで出力してしまうが、これは正式なJSON仕様(RFC 8259)には存在せず、
    ブラウザのJSON.parse()はエラーで拒否する(実際に2026-09-15、セクター/
    テーマのday_change_pct計算でNaNが混入し、ダッシュボード全体が
    「データなし」表示になる不具合が発生した)。json.dumpsに渡す前に
    NaN/InfinityをJSON標準のnullへ変換しておく。"""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def save_snapshot(result: dict, history_dir: str = HISTORY_DIR) -> str:
    """resultを data/history/<date>.json として保存し、latest.json も更新する。
    戻り値: 書き込んだ日付ファイルのパス。"""
    os.makedirs(history_dir, exist_ok=True)
    date_str = result["date"]
    path = os.path.join(history_dir, f"{date_str}.json")
    payload = json.dumps(_sanitize_for_json(result), ensure_ascii=False, indent=2, default=str)

    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)

    latest_path = os.path.join(history_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(payload)

    return path


def list_history_dates(history_dir: str = HISTORY_DIR) -> list[str]:
    """保存済みの日付一覧(YYYY-MM-DD)を昇順で返す。"""
    if not os.path.isdir(history_dir):
        return []
    dates = []
    for name in os.listdir(history_dir):
        if name == "latest.json" or not name.endswith(".json"):
            continue
        dates.append(name[: -len(".json")])
    return sorted(dates)


def load_snapshot(date_str: str, history_dir: str = HISTORY_DIR) -> dict | None:
    path = os.path.join(history_dir, f"{date_str}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
