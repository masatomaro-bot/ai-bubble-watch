"""
sheets_writer.py
================
Google Sheets への書き込みユーティリティ。既存の慈愛の観察台パイプライン
(yfinance -> Google Sheets -> GitHub Actions) と同じ認証方式(サービスアカウント)
を想定している。

必要な環境変数:
  GOOGLE_SERVICE_ACCOUNT_JSON : サービスアカウントの認証情報JSON(文字列そのもの、
                                 またはJSONファイルへのパス)
  SPREADSHEET_ID              : 書き込み先スプレッドシートのID
"""

from __future__ import annotations

import json
import os

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    raw = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    if os.path.exists(raw):
        creds = Credentials.from_service_account_file(raw, scopes=SCOPES)
    else:
        info = json.loads(raw)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)

    _client = gspread.authorize(creds)
    return _client


def ensure_worksheet(spreadsheet_id: str, worksheet_name: str, header: list) -> None:
    client = _get_client()
    sh = client.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
        if not ws.row_values(1):
            ws.append_row(header)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=max(len(header), 10))
        ws.append_row(header)


def append_rows(spreadsheet_id: str, worksheet_name: str, rows: list[list]) -> None:
    client = _get_client()
    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    ws.append_rows(rows, value_input_option="USER_ENTERED")


def upsert_row(
    spreadsheet_id: str,
    worksheet_name: str,
    row: list,
    key_col_index: int = 0,
) -> None:
    """`row[key_col_index]`(通常は日付文字列)と同じ値を持つ既存行があれば
    その行を上書きし、なければ末尾に追記する。

    workflow_dispatchでの手動再実行やcronの重複起動で、同じ日付の行が
    何行も増えていく問題(2026-09-13に複数回実行して発覚)への対応。
    """
    client = _get_client()
    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)

    key_value = str(row[key_col_index])
    col_values = ws.col_values(key_col_index + 1)  # gspreadは1-indexed

    existing_row_number = None
    for i, v in enumerate(col_values, start=1):
        if i == 1:
            continue  # ヘッダー行
        if v == key_value:
            existing_row_number = i
            break

    if existing_row_number is not None:
        end_col_letter = gspread.utils.rowcol_to_a1(1, len(row)).rstrip("1")
        ws.update(
            f"A{existing_row_number}:{end_col_letter}{existing_row_number}",
            [row],
            value_input_option="USER_ENTERED",
        )
    else:
        ws.append_row(row, value_input_option="USER_ENTERED")


def read_last_row(spreadsheet_id: str, worksheet_name: str) -> list | None:
    """指定シートの最終データ行(ヘッダーを除く)をlistで返す。データが
    ヘッダーのみ、またはシートが空の場合はNoneを返す。"""
    client = _get_client()
    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    values = ws.get_all_values()
    if len(values) < 2:
        return None
    return values[-1]


def read_last_row_excluding_date(
    spreadsheet_id: str,
    worksheet_name: str,
    exclude_date: str,
    date_col_index: int = 0,
) -> list | None:
    """末尾から遡って、date_col_indexの値がexclude_dateと一致しない最初の
    行を返す。累積値(A/Dラインなど)の計算で、同じ日に何度も再実行しても
    二重加算しないようにするためのもの(upsert_rowで同日再実行時は最終行が
    exclude_date=今日自身になるため、その1つ前の"本当の前営業日"を拾う)。"""
    client = _get_client()
    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    values = ws.get_all_values()
    for row in reversed(values[1:]):  # ヘッダーを除き末尾から
        if len(row) > date_col_index and row[date_col_index] != exclude_date:
            return row
    return None
