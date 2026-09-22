from __future__ import annotations

from typing import Any, Iterable

import gspread
import google.auth


POST_HEADERS = [
    "customer_name", "linkedin_profile_url", "post_url", "post_date", "post_content",
    "post_type", "like_count", "comment_count", "repost_count", "view_count",
    "img_url", "video_url", "week_start", "week_end", "content_summary",
    "processing_status", "processing_error", "processed_at",
]
WEEK_HEADERS = [
    "customer_name", "week_start", "week_end", "post_count", "weekly_synthesis",
    "processed_at", "processing_status", "processing_error",
]


def get_client() -> gspread.Client:
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials, _ = google.auth.default(scopes=scopes)
    return gspread.authorize(credentials)


class SheetsStore:
    def __init__(self, spreadsheet_id: str, client: gspread.Client | None = None) -> None:
        if not spreadsheet_id:
            raise ValueError("spreadsheet ID is required")
        self._spreadsheet = (client or get_client()).open_by_key(spreadsheet_id)

    def _worksheet(self, title: str, headers: list[str]) -> gspread.Worksheet:
        try:
            worksheet = self._spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            worksheet = self._spreadsheet.add_worksheet(title=title, rows=1000, cols=max(20, len(headers)))
        if not worksheet.row_values(1):
            worksheet.update("A1", [headers])
        return worksheet

    @staticmethod
    def _upsert(worksheet: gspread.Worksheet, headers: list[str], rows: Iterable[dict[str, Any]], key_fields: list[str]) -> None:
        values = worksheet.get_all_values()
        existing = {tuple(row[headers.index(field)] if len(row) > headers.index(field) else "" for field in key_fields): i + 1
                    for i, row in enumerate(values[1:], start=1)}
        updates: list[dict[str, Any]] = []
        appends: list[list[Any]] = []
        for item in rows:
            key = tuple(str(item.get(field, "")) for field in key_fields)
            row = [item.get(header, "") for header in headers]
            if key in existing:
                updates.append({"range": f"A{existing[key] + 1}", "values": [row]})
            else:
                appends.append(row)
        if updates:
            worksheet.batch_update(updates)
        if appends:
            worksheet.append_rows(appends, value_input_option="USER_ENTERED")

    def upsert_post_details(self, rows: list[dict[str, Any]]) -> None:
        worksheet = self._worksheet("post_details", POST_HEADERS)
        self._upsert(worksheet, POST_HEADERS, rows, ["customer_name", "linkedin_profile_url", "post_url"])

    def upsert_weekly_summary(self, rows: list[dict[str, Any]]) -> None:
        worksheet = self._worksheet("weekly_summary", WEEK_HEADERS)
        self._upsert(worksheet, WEEK_HEADERS, rows, ["customer_name", "week_start"])

    def read_customer_info(self) -> list[dict[str, str]]:
        worksheet = self._worksheet("customer_info", ["customer_name", "linkedin_profile_url"])
        return [dict(zip(worksheet.row_values(1), row)) for row in worksheet.get_all_values()[1:] if row]
