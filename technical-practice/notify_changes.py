"""
notify_changes.py
==================
前日からの地合い判定・警戒フラグの変化を検知し、通知が必要な場合は
GitHub Issueを自動作成する(GitHub Actionsのメール通知経由でユーザーに届く)。

Fable 5.1によるダッシュボードレビューで、「心の準備をするのが目的なら、
毎日見に行かなくても変化に気づける仕組みが確実」との指摘があった。
一番設定不要な方法として、GitHub Actionsから標準のGITHUB_TOKENだけで
動くGitHub Issue自動作成を採用した(LINE/Slack等は追加のトークン設定が必要)。

通知条件:
- overall_trend_state(総合判定)が前日から変化した
- warning_flags(警戒チェックリスト)のいずれかが新たに点灯した
  (前日は消灯・今日は点灯。既に点灯し続けている場合は再通知しない)

必要な環境変数(GitHub Actions上で自動提供):
  GITHUB_TOKEN, GITHUB_REPOSITORY (actions/checkout等と同様、workflow側で
  暗黙に渡されるものを利用する)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

import history_store

GITHUB_API_URL = "https://api.github.com"
DASHBOARD_URL = "https://masatomaro-bot.github.io/ai-bubble-watch/"


def build_notification(latest: dict, prev: dict | None) -> tuple[str, str] | None:
    """通知すべき変化があれば (title, body) を返す。なければNone。"""
    lines = []

    curr_state = latest.get("overall_trend_state")
    prev_state = (prev or {}).get("overall_trend_state")
    if prev is not None and curr_state != prev_state:
        lines.append(f"- 総合判定: {prev_state} → {curr_state}")

    curr_flags = {f["id"]: f for f in latest.get("warning_flags", [])}
    prev_flags = {f["id"]: f for f in (prev or {}).get("warning_flags", [])} if prev is not None else {}
    for fid, f in curr_flags.items():
        was_active = bool((prev_flags.get(fid) or {}).get("active"))
        if f.get("active") and not was_active:
            lines.append(f"- 新たに点灯: {f.get('label')}({f.get('detail', '')})")

    if not lines:
        return None

    title = f"地合い変化通知 {latest.get('date')}"
    body = (
        "\n".join(lines)
        + f"\n\nダッシュボード: {DASHBOARD_URL}\n\n"
        + "※これは自動生成された通知です。判定ロジック・数値の正確性は保証されません。"
        "投資判断の根拠にはしないでください。"
    )
    return title, body


def create_issue(repo: str, token: str, title: str, body: str) -> None:
    url = f"{GITHUB_API_URL}/repos/{repo}/issues"
    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-bubble-watch-bot",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def main() -> None:
    dates = history_store.list_history_dates()
    if not dates:
        print("[info] 履歴がまだありません。通知をスキップします。", file=sys.stderr)
        return

    latest = history_store.load_snapshot(dates[-1])
    prev = history_store.load_snapshot(dates[-2]) if len(dates) >= 2 else None

    notification = build_notification(latest, prev)
    if notification is None:
        print("[info] 通知が必要な変化はありませんでした。", file=sys.stderr)
        return

    title, body = notification
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        print(
            "[warn] GITHUB_REPOSITORY/GITHUB_TOKENが設定されていないため、Issue作成をスキップします。",
            file=sys.stderr,
        )
        print(f"[info] 通知内容:\n{title}\n{body}", file=sys.stderr)
        return

    try:
        create_issue(repo, token, title, body)
        print(f"[info] 通知Issueを作成しました: {title}", file=sys.stderr)
    except urllib.error.HTTPError as e:
        print(f"[warn] Issue作成に失敗しました({e.code}): {e.read()!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
