"""history_store.py (地合い結果のJSON履歴保存)の単体テスト。
実ファイルシステムへの書き込みはpytestのtmp_pathフィクスチャで隔離する。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from history_store import list_history_dates, load_snapshot, save_snapshot


def test_save_snapshot_writes_dated_file_and_latest(tmp_path):
    result = {"date": "2026-09-14", "overall_trend_state": "correction", "nested": {"a": 1}}
    saved_path = save_snapshot(result, history_dir=str(tmp_path))

    assert os.path.exists(saved_path)
    assert os.path.exists(os.path.join(str(tmp_path), "latest.json"))

    loaded = load_snapshot("2026-09-14", history_dir=str(tmp_path))
    assert loaded == result


def test_list_history_dates_excludes_latest_and_sorts(tmp_path):
    for d in ["2026-09-12", "2026-09-10", "2026-09-11"]:
        save_snapshot({"date": d}, history_dir=str(tmp_path))

    dates = list_history_dates(history_dir=str(tmp_path))
    assert dates == ["2026-09-10", "2026-09-11", "2026-09-12"]


def test_load_snapshot_returns_none_for_missing_date(tmp_path):
    assert load_snapshot("2026-01-01", history_dir=str(tmp_path)) is None


def test_list_history_dates_returns_empty_for_missing_dir(tmp_path):
    missing = os.path.join(str(tmp_path), "does-not-exist")
    assert list_history_dates(history_dir=missing) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
