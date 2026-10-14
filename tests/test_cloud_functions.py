from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).parents[1]


def load_module(folder: str) -> ModuleType:
    path = ROOT / "cloud_function" / folder / "main.py"
    spec = importlib.util.spec_from_file_location(f"{folder}_main", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules() -> tuple[ModuleType, ModuleType]:
    return load_module("phantom_function"), load_module("summarize_function")


def mappings() -> list[dict[str, str]]:
    return [
        {
            "customer_name": "ABC",
            "linkedin_profile_url": "https://www.linkedin.com/company/abc",
        },
        {
            "customer_name": "XYZ",
            "linkedin_profile_url": "https://www.linkedin.com/company/xyz",
        },
    ]


def payload() -> dict:
    return {
        "resultObject": [
            {
                "profileUrl": "https://www.linkedin.com/company/abc/",
                "postUrl": "https://www.linkedin.com/feed/update/1",
                "postDate": "2026-10-05T01:00:00Z",
                "postContent": "ABC post",
            },
            {
                "profileUrl": "https://www.linkedin.com/company/xyz/",
                "postUrl": "https://www.linkedin.com/feed/update/2",
                "postDate": "2026-10-06T01:00:00Z",
                "postContent": "XYZ post",
            },
            {
                "profileUrl": "https://www.linkedin.com/company/abc/",
                "error": "Company Activity Page not loading",
            },
        ]
    }


def test_both_function_packages_normalize_the_same_posts(modules) -> None:
    phantom, summarize = modules
    args = (payload(), mappings(), "Australia/Brisbane")

    phantom_posts, phantom_errors = phantom.normalize_posts(*args)
    summarize_posts, summarize_errors = summarize.normalize_posts(*args)

    assert phantom_posts == summarize_posts
    assert phantom_errors == summarize_errors
    assert phantom_errors == [{
        "customer_name": "ABC",
        "profile_url": "https://www.linkedin.com/company/abc",
        "message": "Company Activity Page not loading",
    }]


def test_date_range_filters_posts_before_summarization(modules) -> None:
    _, summarize = modules

    posts, errors = summarize.normalize_posts(
        payload(),
        mappings(),
        "Australia/Brisbane",
        "2026-10-06",
        "2026-10-06",
    )

    assert [post["customer_name"] for post in posts] == ["XYZ"]
    assert errors[0]["customer_name"] == "ABC"


def test_date_range_validation_rejects_invalid_and_reversed_dates(modules) -> None:
    _, summarize = modules

    with pytest.raises(ValueError, match="valid ISO dates"):
        summarize.request_date_range({
            "start_date": "2026-02-30",
            "end_date": "2026-03-01",
        })
    with pytest.raises(ValueError, match="on or before"):
        summarize.request_date_range({
            "start_date": "2026-10-07",
            "end_date": "2026-10-01",
        })


def test_post_summary_retries_once_when_sentence_limit_is_exceeded(modules, monkeypatch) -> None:
    _, summarize = modules
    responses = iter([
        {"summaries": [{
            "index": 1,
            "sentences": [
                "First sentence.",
                "Second sentence.",
                "Third sentence.",
                "Fourth sentence.",
            ],
        }]},
        {"summaries": [{
            "index": 1,
            "sentences": ["First sentence.", "Second sentence."],
        }]},
    ])
    calls = []

    def fake_gemini(contents, system_instruction, response_schema):
        calls.append(contents)
        assert response_schema == summarize.POST_SUMMARY_RESPONSE_SCHEMA
        return next(responses)

    monkeypatch.setattr(summarize, "gemini_json", fake_gemini)
    result = summarize.summarize_posts([{
        "post_date": "2026-10-06T01:00:00Z",
        "post_content": "Post content",
    }])

    assert result == ["First sentence. Second sentence."]
    assert len(calls) == 2
    assert "previous response failed validation" in calls[1]


def test_post_summary_rejects_repeated_invalid_sentence_arrays(
    modules, monkeypatch
) -> None:
    _, summarize = modules
    response = {"summaries": [{
        "index": 1,
        "sentences": [
            "First sentence.",
            "Second sentence.",
            "Third sentence.",
            "Fourth sentence.",
        ],
    }]}
    monkeypatch.setattr(summarize, "gemini_json", lambda *_args: response)

    with pytest.raises(ValueError, match="invalid post sentence array"):
        summarize.summarize_posts([{
            "post_date": "2026-10-06T01:00:00Z",
            "post_content": "Post content",
        }])


def test_weekly_error_status_is_customer_specific(modules, monkeypatch) -> None:
    _, summarize = modules

    class FakeSheet:
        def __init__(self, rows=None):
            self.rows = rows or []

        def get_all_values(self):
            return self.rows

        def row_values(self, row):
            return self.rows[0] if self.rows else []

        def append_rows(self, rows, value_input_option=None):
            self.rows.extend(rows)

        def batch_update(self, updates):
            return None

    class FakeBook:
        def __init__(self):
            self.sheets = {
                "customer_info": FakeSheet([
                    ["customer_name", "linkedin_profile_url"],
                    ["ABC", "https://www.linkedin.com/company/abc"],
                    ["XYZ", "https://www.linkedin.com/company/xyz"],
                ]),
                "post_details": FakeSheet([summarize.POST_HEADERS]),
                "weekly_summary": FakeSheet([summarize.WEEK_HEADERS]),
            }

        def worksheet(self, title):
            return self.sheets[title]

    monkeypatch.setenv("OUTPUT_SPREADSHEET_ID", "spreadsheet")
    monkeypatch.setenv("REPORTING_TIMEZONE", "Australia/Brisbane")
    monkeypatch.setattr(summarize, "sheets_client", lambda: type(
        "Client", (), {"open_by_key": lambda self, key: FakeBook()}
    )())
    monkeypatch.setattr(
        summarize,
        "summarize_posts",
        lambda posts: [f"Summary for {post['customer_name']}" for post in posts],
    )
    monkeypatch.setattr(
        summarize,
        "weekly_summary",
        lambda customer, posts: f"Weekly {customer}",
    )

    result = summarize.process_payload(
        payload(),
        datetime(2026, 10, 6, tzinfo=timezone.utc),
    )

    assert result["processing_errors"] == ["Company Activity Page not loading"]
    assert result["customer_count"] == 2
