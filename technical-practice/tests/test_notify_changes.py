"""notify_changes.py の単体テスト。GitHub APIへの実通信は行わず、
build_notification()の通知要否判定ロジックのみを検証する。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from notify_changes import build_notification


def _snapshot(date, overall_trend_state="correction", warning_flags=None):
    return {
        "date": date,
        "overall_trend_state": overall_trend_state,
        "warning_flags": warning_flags or [],
    }


def test_no_previous_snapshot_returns_none():
    # 初回実行(前日データがない)では、状態変化を比較しようがないため通知しない。
    latest = _snapshot("2026-09-17")
    assert build_notification(latest, None) is None


def test_no_change_returns_none():
    latest = _snapshot("2026-09-17", warning_flags=[{"id": "a", "label": "A", "active": False}])
    prev = _snapshot("2026-09-16", warning_flags=[{"id": "a", "label": "A", "active": False}])
    assert build_notification(latest, prev) is None


def test_overall_trend_state_change_triggers_notification():
    latest = _snapshot("2026-09-17", overall_trend_state="correction")
    prev = _snapshot("2026-09-16", overall_trend_state="confirmed_uptrend")
    result = build_notification(latest, prev)
    assert result is not None
    title, body = result
    assert "2026-09-17" in title
    assert "confirmed_uptrend" in body and "correction" in body


def test_newly_active_flag_triggers_notification():
    latest = _snapshot("2026-09-17", warning_flags=[
        {"id": "leader_breakdown", "label": "リーダー株の崩れ", "active": True, "detail": "60%が50日線割れ"},
    ])
    prev = _snapshot("2026-09-16", warning_flags=[
        {"id": "leader_breakdown", "label": "リーダー株の崩れ", "active": False, "detail": "10%が50日線割れ"},
    ])
    result = build_notification(latest, prev)
    assert result is not None
    _, body = result
    assert "リーダー株の崩れ" in body


def test_already_active_flag_does_not_retrigger():
    # 既に点灯し続けているフラグは、毎日再通知しない(初めて点灯した日だけ通知)。
    latest = _snapshot("2026-09-17", warning_flags=[
        {"id": "leader_breakdown", "label": "リーダー株の崩れ", "active": True, "detail": "70%が50日線割れ"},
    ])
    prev = _snapshot("2026-09-16", warning_flags=[
        {"id": "leader_breakdown", "label": "リーダー株の崩れ", "active": True, "detail": "60%が50日線割れ"},
    ])
    assert build_notification(latest, prev) is None


def test_flag_deactivation_does_not_trigger_alone():
    # フラグが消灯したこと自体は(悪いニュースではないため)通知しない。
    latest = _snapshot("2026-09-17", warning_flags=[
        {"id": "leader_breakdown", "label": "リーダー株の崩れ", "active": False, "detail": ""},
    ])
    prev = _snapshot("2026-09-16", warning_flags=[
        {"id": "leader_breakdown", "label": "リーダー株の崩れ", "active": True, "detail": ""},
    ])
    assert build_notification(latest, prev) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
