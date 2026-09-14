"""
sheets_writer.py の upsert_row / read_last_row_excluding_date のロジックを、
実際のGoogle Sheets APIを呼ばずに検証する単体テスト。
gspreadのWorksheet/Spreadsheet/Clientをごく薄いフェイクに差し替える。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re

import pytest

import sheets_writer


class FakeWorksheet:
    def __init__(self, header, rows):
        self.header = header
        self.rows = rows  # list[list[str]] (ヘッダーを含まない)

    def col_values(self, col_idx_1based):
        idx = col_idx_1based - 1
        vals = [self.header[idx] if idx < len(self.header) else ""]
        for r in self.rows:
            vals.append(r[idx] if idx < len(r) else "")
        return vals

    def get_all_values(self):
        return [self.header] + self.rows

    def update(self, range_str, values, value_input_option=None):
        m = re.match(r"A(\d+):", range_str)
        row_number = int(m.group(1))  # 1-indexed、ヘッダーがrow1
        self.rows[row_number - 2] = [str(v) for v in values[0]]

    def append_row(self, row, value_input_option=None):
        self.rows.append([str(v) for v in row])


class FakeSpreadsheet:
    def __init__(self, worksheet):
        self._worksheet = worksheet

    def worksheet(self, name):
        return self._worksheet


class FakeClient:
    def __init__(self, spreadsheet):
        self._spreadsheet = spreadsheet

    def open_by_key(self, key):
        return self._spreadsheet


@pytest.fixture
def fake_ws(monkeypatch):
    ws = FakeWorksheet(
        header=["date", "value"],
        rows=[["2026-09-10", "10"], ["2026-09-11", "20"], ["2026-09-12", "30"]],
    )
    client = FakeClient(FakeSpreadsheet(ws))
    monkeypatch.setattr(sheets_writer, "_get_client", lambda: client)
    return ws


def test_upsert_row_overwrites_existing_date(fake_ws):
    sheets_writer.upsert_row("dummy-id", "sheet", ["2026-09-11", "999"])
    assert fake_ws.rows == [
        ["2026-09-10", "10"],
        ["2026-09-11", "999"],
        ["2026-09-12", "30"],
    ]


def test_upsert_row_appends_new_date(fake_ws):
    sheets_writer.upsert_row("dummy-id", "sheet", ["2026-09-13", "40"])
    assert fake_ws.rows[-1] == ["2026-09-13", "40"]
    assert len(fake_ws.rows) == 4


def test_read_last_row_excluding_date_skips_matching_last_row(fake_ws):
    # 最終行(2026-09-12)を除外すると、その1つ前(2026-09-11)が返る
    row = sheets_writer.read_last_row_excluding_date("dummy-id", "sheet", "2026-09-12")
    assert row == ["2026-09-11", "20"]


def test_read_last_row_excluding_date_returns_last_row_when_not_matching(fake_ws):
    row = sheets_writer.read_last_row_excluding_date("dummy-id", "sheet", "2026-09-30")
    assert row == ["2026-09-12", "30"]


def test_read_last_row_excluding_date_returns_none_when_all_match(fake_ws):
    for r in fake_ws.rows:
        r[0] = "same-date"
    row = sheets_writer.read_last_row_excluding_date("dummy-id", "sheet", "same-date")
    assert row is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
