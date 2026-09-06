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
