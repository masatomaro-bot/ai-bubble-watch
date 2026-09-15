"""history_store.py (地合い結果のJSON履歴保存)の単体テスト。
実ファイルシステムへの書き込みはpytestのtmp_pathフィクスチャで隔離する。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

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


def test_save_snapshot_sanitizes_nan_and_infinity_to_null(tmp_path):
    # 2026-09-15の実データ実行で実際に発生した回帰テスト: セクター/テーマの
    # day_change_pct計算がNaNを返すことがあり、これをそのままjson.dumpsすると
    # NaNという(JSON仕様上は不正な)リテラルが出力され、ブラウザ側の
    # JSON.parse()がエラーになってダッシュボードが「データなし」表示に
    # なっていた。NaN/InfinityはJSON標準のnullとして保存されるべき。
    result = {
        "date": "2026-09-15",
        "sectors": {"XLK": {"day_change_pct": float("nan"), "rs_ratio": 101.27}},
        "bad_inf": float("inf"),
        "bad_neg_inf": float("-inf"),
        "ok_value": 1.5,
    }
    saved_path = save_snapshot(result, history_dir=str(tmp_path))

    with open(saved_path, encoding="utf-8") as f:
        raw_text = f.read()

    # 「NaN」「Infinity」という生のトークンがファイルに含まれていないこと
    # (=ブラウザの厳格なJSON.parse()でも読める状態であること)を確認する。
    # strictなJSONパーサをJavaScript同様の挙動で模倣する: parse_constantに
    # 到達したら(NaN/Infinityトークンが残っていれば)例外にする。
    def _reject_constant(token):
        raise ValueError(f"invalid JSON constant encountered: {token}")

    parsed = json.loads(raw_text, parse_constant=_reject_constant)  # 例外が出なければOK

    assert parsed["sectors"]["XLK"]["day_change_pct"] is None
    assert parsed["bad_inf"] is None
    assert parsed["bad_neg_inf"] is None
    assert parsed["ok_value"] == 1.5


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
