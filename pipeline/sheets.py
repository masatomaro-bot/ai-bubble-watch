"""Google Sheets への書き込み(gspread)。

認証情報はGitHub Actions Secretsから環境変数経由で渡す想定:
  GOOGLE_SERVICE_ACCOUNT_JSON  サービスアカウントの鍵JSON(文字列そのもの)
  SPREADSHEET_ID               書き込み先スプレッドシートのID
"""
from __future__ import annotations

import json
import os

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

WATCHLIST_HEADER = [
    "Date", "Ticker", "Holding", "Sector", "Industry", "Close", "DayChangePct",
    "RelVolume", "SMA50", "SMA150", "SMA200",
    "PctFrom52wHigh", "PctFrom52wLow",
    "RSRating", "SectorRSRating", "IndustryRSRating",
    "VCPCandidate", "TrendTemplatePassCount", "TrendTemplatePass",
]

SECTOR_RS_HEADER = ["Date", "GroupType", "GroupName", "RSRating", "MemberCount"]

BREADTH_HISTORY_HEADER_BASE = [
    "Date", "PctAbove50DMA", "PctAbove200DMA", "NewHighs", "NewLows", "Advancers", "Decliners",
]


def get_client() -> gspread.Client:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    else:
        cred_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        creds = Credentials.from_service_account_file(cred_path, scopes=SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(client: gspread.Client) -> gspread.Spreadsheet:
    return client.open_by_key(os.environ["SPREADSHEET_ID"])


def _get_or_create_worksheet(
    sh: gspread.Spreadsheet, title: str, header: list[str]
) -> gspread.Worksheet:
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=max(len(header), 10))
        ws.update([header], "A1")
        return ws


def write_watchlist_latest(sh: gspread.Spreadsheet, rows: list[list]) -> None:
    """毎日その日のスナップショットで上書きする(1銘柄1行)。"""
    ws = _get_or_create_worksheet(sh, "Watchlist_Latest", WATCHLIST_HEADER)
    ws.clear()
    ws.update([WATCHLIST_HEADER] + rows, "A1")


def write_sector_rs(sh: gspread.Spreadsheet, rows: list[list]) -> None:
    """毎日その日のスナップショットで上書きする(セクター/業種ごとに1行)。"""
    ws = _get_or_create_worksheet(sh, "Sector_RS", SECTOR_RS_HEADER)
    ws.clear()
    ws.update([SECTOR_RS_HEADER] + rows, "A1")


def append_breadth_history(sh: gspread.Spreadsheet, row: list, index_names: list[str]) -> None:
    """Breadth/Distribution Dayは推移を見る指標なので、日々追記していく。"""
    header = BREADTH_HISTORY_HEADER_BASE + [f"DistDays_{name}" for name in index_names]
    ws = _get_or_create_worksheet(sh, "Breadth_History", header)
    if ws.row_values(1) != header:
        ws.update([header], "A1")
    ws.append_row(row, value_input_option=ValueInputOption.user_entered)
