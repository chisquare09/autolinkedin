from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import ReportingWindow


def reporting_window(value: datetime | date, timezone_name: str = "Australia/Brisbane") -> ReportingWindow:
    tz = ZoneInfo(timezone_name)
    if isinstance(value, date) and not isinstance(value, datetime):
        local = datetime.combine(value, time.min, tzinfo=tz)
    elif value.tzinfo is None:
        local = value.replace(tzinfo=tz)
    else:
        local = value.astimezone(tz)
    monday = (local - timedelta(days=local.weekday())).date()
    sunday = monday + timedelta(days=6)
    return ReportingWindow(monday.isoformat(), sunday.isoformat())


def parse_timestamp(value: str, timezone_name: str = "Australia/Brisbane") -> datetime:
    if not value or not isinstance(value, str):
        raise ValueError("post date is missing")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid post date: {value}") from exc
    tz = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def is_in_window(value: str, window: ReportingWindow, timezone_name: str = "Australia/Brisbane") -> bool:
    instant = parse_timestamp(value, timezone_name).astimezone(ZoneInfo(timezone_name))
    return window.week_start <= instant.date().isoformat() <= window.week_end
