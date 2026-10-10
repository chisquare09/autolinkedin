from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.date_windows import is_in_window, reporting_window
from app.models import MappingRecord
from app.normalization import deduplicate_mappings, normalize_profile_url
from app.phantom_parser import normalize_posts
from app.processor import process_payload
from app.summarization import summarize_customer_week, summarize_posts
from app.webhook import authorize


FIXTURE = json.loads(Path("fixtures/phantombuster_payload.json").read_text())


class FakeGenerator:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.system_instructions: list[str] = []

    def generate(self, contents: str, system_instruction: str = "") -> str:
        self.prompts.append(contents)
        self.system_instructions.append(system_instruction)
        if '"summaries"' in contents:
            posts_json = contents.split("Input posts:\n", 1)[1]
            count = len(json.loads(posts_json))
            return json.dumps({"summaries": [{"index": i, "summary": f"Summary {i}"} for i in range(1, count + 1)]})
        return json.dumps({"weekly_synthesis": "A concise weekly business summary."})


def test_webhook_direct_mode_processes_without_pubsub(monkeypatch: pytest.MonkeyPatch) -> None:
    import main

    processed: list[dict] = []

    def fake_process_job(message: dict) -> None:
        processed.append(message)

    monkeypatch.setenv("OUTPUT_SPREADSHEET_ID", "spreadsheet")
    monkeypatch.setenv("PROCESSING_MODE", "direct")
    monkeypatch.setenv("WEBHOOK_BEARER_TOKEN", "token")
    monkeypatch.setattr(main, "process_job", fake_process_job)

    result = main.webhook({"resultObject": []}, authorization="Bearer token")

    assert result["status"] == "processed"
    assert processed[0]["payload"] == {"resultObject": []}


def test_reporting_window_uses_monday_to_sunday_in_brisbane() -> None:
    window = reporting_window(datetime(2026, 9, 20, 13, 59, tzinfo=timezone.utc))
    assert window.week_start == "2026-09-14"
    assert window.week_end == "2026-09-20"


def test_brisbane_boundary_is_inclusive() -> None:
    from app.models import ReportingWindow
    window = ReportingWindow("2026-09-14", "2026-09-20")
    assert is_in_window("2026-09-13T14:00:00Z", window)
    assert is_in_window("2026-09-20T13:59:59Z", window)
    assert not is_in_window("2026-09-20T14:00:00Z", window)


def test_profile_url_normalization_and_mapping_deduplication() -> None:
    assert normalize_profile_url("https://www.linkedin.com/company/ABC/?feedView=all") == "https://www.linkedin.com/company/abc"
    rows = deduplicate_mappings([
        {"customer_name": "ABC", "linkedin_profile_url": "linkedin.com/company/abc/"},
        {"customer_name": "ABC", "linkedin_profile_url": "https://www.linkedin.com/company/abc/?feedView=all"},
    ])
    assert rows == [{"customer_name": "ABC", "linkedin_profile_url": "https://www.linkedin.com/company/abc"}]


def test_fixture_filters_deduplicates_and_maps_posts() -> None:
    mappings = [
        MappingRecord("ABC Information Solutions", "https://www.linkedin.com/company/abc-information-solutions"),
        MappingRecord("Airtasker", "https://www.linkedin.com/company/airtasker"),
        MappingRecord("No Activity", "https://www.linkedin.com/company/no-activity"),
    ]
    posts, errors = normalize_posts(FIXTURE, mappings, reporting_window(datetime(2026, 9, 16, tzinfo=timezone.utc)))
    assert len(posts) == 3
    assert {post.customer_name for post in posts} == {"ABC Information Solutions", "Airtasker"}
    assert any("missing URL or content" in error for error in errors) is False


def test_summarization_validates_structured_responses() -> None:
    generator = FakeGenerator()
    mappings = [MappingRecord("ABC", "https://www.linkedin.com/company/abc")]
    posts, _ = normalize_posts(
        {"resultObject": [{
            "profileUrl": "https://www.linkedin.com/company/abc",
            "postUrl": "https://www.linkedin.com/feed/update/1",
            "postDate": "2026-09-15T01:00:00Z",
            "postContent": "A post",
        }]},
        mappings,
        reporting_window(datetime(2026, 9, 16, tzinfo=timezone.utc)),
    )
    assert summarize_posts(generator, posts) == ["Summary 1"]
    assert summarize_customer_week(generator, "ABC", posts) == "A concise weekly business summary."


def test_process_payload_creates_zero_post_customer_row() -> None:
    generator = FakeGenerator()
    post_rows, weekly_rows, errors = process_payload(
        FIXTURE,
        [
            {"customer_name": "ABC Information Solutions", "linkedin_profile_url": "https://www.linkedin.com/company/abc-information-solutions"},
            {"customer_name": "Airtasker", "linkedin_profile_url": "https://www.linkedin.com/company/airtasker"},
            {"customer_name": "No Activity", "linkedin_profile_url": "https://www.linkedin.com/company/no-activity"},
        ],
        generator,
        datetime(2026, 9, 16, tzinfo=timezone.utc),
    )
    assert len(post_rows) == 3
    no_activity = next(row for row in weekly_rows if row["customer_name"] == "No Activity")
    assert no_activity["post_count"] == 0
    assert no_activity["processing_status"] == "processed"
    assert errors == []


def test_webhook_authentication() -> None:
    authorize({"authorization": "Bearer token"}, mode="bearer", bearer_token="token")
    with pytest.raises(PermissionError):
        authorize({"authorization": "Bearer wrong"}, mode="bearer", bearer_token="token")

def test_webhook_publishes_payload_and_reporting_week(monkeypatch: pytest.MonkeyPatch) -> None:
    import main

    published: list[dict] = []

    class FakePublisher:
        def __init__(self, topic: str) -> None:
            assert topic == "projects/test/topics/jobs"

        def publish(self, message: dict) -> str:
            published.append(message)
            return "message-id"

    monkeypatch.setenv("PUBSUB_TOPIC", "projects/test/topics/jobs")
    monkeypatch.setenv("WEBHOOK_BEARER_TOKEN", "token")
    monkeypatch.setattr(main, "PubSubPublisher", FakePublisher)
    monkeypatch.setattr(main, "datetime", _FixedDateTime)

    result = main.webhook({"resultObject": []}, authorization="Bearer token")

    assert result["status"] == "accepted"
    assert published[0]["payload"] == {"resultObject": []}
    assert published[0]["reporting_week"] == {
        "week_start": "2026-09-21",
        "week_end": "2026-09-27",
    }


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: timezone | None = None) -> "_FixedDateTime":
        return cls(2026, 9, 27, 12, tzinfo=tz)
