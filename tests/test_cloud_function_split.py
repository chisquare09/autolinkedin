from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from flask import Flask
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request


ROOT = Path(__file__).parents[1]


def load_function_module(folder: str) -> ModuleType:
    path = ROOT / "cloud_function" / folder / "main.py"
    spec = importlib.util.spec_from_file_location(f"{folder}_main", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(
    payload: dict[str, Any],
    *,
    path: str = "/",
    method: str = "POST",
) -> Request:
    environ = EnvironBuilder(
        path=path,
        method=method,
        json=payload,
        headers={"Authorization": "Bearer token"},
    ).get_environ()
    return Request(environ)


def call_in_app(module: ModuleType, handler: Any, request: Request) -> Any:
    app = Flask(module.__name__)
    with app.app_context():
        return handler(request)


@pytest.fixture
def function_modules() -> tuple[ModuleType, ModuleType]:
    return (
        load_function_module("phantom_function"),
        load_function_module("summarize_function"),
    )


def test_split_functions_keep_legacy_ingestion_response_contract(
    monkeypatch: pytest.MonkeyPatch,
    function_modules: tuple[ModuleType, ModuleType],
) -> None:
    phantom, _ = function_modules
    monkeypatch.setenv("WEBHOOK_BEARER_TOKEN", "token")
    monkeypatch.setenv("OUTPUT_SPREADSHEET_ID", "spreadsheet")

    monkeypatch.setattr(
        phantom,
        "ingest_results",
        lambda payload: {
            "stored_row_count": 2,
            "new_row_count": 1,
            "sheet": "phantom_result",
        },
    )

    response = call_in_app(
        phantom,
        phantom.phantom_webhook,
        request({"action": "ingest_results", "resultObject": []}),
    )

    assert response[1] == 200
    body = response[0].get_json()
    assert body["status"] == "processed"
    assert body["stored_row_count"] == 2
    assert body["new_row_count"] == 1
    assert body["sheet"] == "phantom_result"
    assert body["job_id"]


def test_split_functions_keep_legacy_summarization_response_contract(
    monkeypatch: pytest.MonkeyPatch,
    function_modules: tuple[ModuleType, ModuleType],
) -> None:
    _, summarize = function_modules
    monkeypatch.setenv("WEBHOOK_BEARER_TOKEN", "token")
    monkeypatch.setenv("OUTPUT_SPREADSHEET_ID", "spreadsheet")
    class FakeClient:
        def open_by_key(self, spreadsheet_id: str) -> object:
            assert spreadsheet_id == "spreadsheet"
            return object()

    monkeypatch.setattr(summarize, "sheets_client", lambda: FakeClient())

    captured: dict[str, Any] = {}

    def fake_process_payload(payload: dict[str, Any], reporting_date: datetime) -> dict[str, Any]:
        captured["payload"] = payload
        captured["reporting_date"] = reporting_date
        return {
            "post_count": 1,
            "new_post_count": 1,
            "customer_count": 1,
            "processing_errors": [],
            "processed_weeks": ["2026-09-14"],
        }

    monkeypatch.setattr(summarize, "process_payload", fake_process_payload)
    payload = {
        "action": "process_week",
        "payload": {"resultObject": [{"postUrl": "https://example.test/post"}]},
        "reporting_date": "2026-09-16T00:00:00Z",
    }

    response = call_in_app(
        summarize,
        summarize.summarization_webhook,
        request(payload),
    )

    assert response[1] == 200
    body = response[0].get_json()
    assert body["status"] == "processed"
    assert body["post_count"] == 1
    assert body["new_post_count"] == 1
    assert body["customer_count"] == 1
    assert body["processing_errors"] == []
    assert body["processed_weeks"] == ["2026-09-14"]
    assert body["job_id"]
    assert captured["payload"] == payload["payload"]
    assert captured["reporting_date"] == datetime(2026, 9, 16, tzinfo=timezone.utc)


def test_split_functions_reject_cross_function_actions(
    monkeypatch: pytest.MonkeyPatch,
    function_modules: tuple[ModuleType, ModuleType],
) -> None:
    phantom, summarize = function_modules
    monkeypatch.setenv("WEBHOOK_BEARER_TOKEN", "token")

    phantom_response = call_in_app(
        phantom,
        phantom.phantom_webhook,
        request({"action": "process_week"}),
    )
    summarize_response = call_in_app(
        summarize,
        summarize.summarization_webhook,
        request({"action": "ingest_results"}),
    )

    assert phantom_response[1] == 503
    assert "action must be 'ingest_results'" in phantom_response[0].get_json()["error"]
    assert summarize_response[1] == 503
    assert "action must be 'process_week'" in summarize_response[0].get_json()["error"]


def test_independent_packages_produce_same_normalized_post(
    function_modules: tuple[ModuleType, ModuleType],
) -> None:
    phantom, summarize = function_modules
    mappings = [
        {
            "customer_name": "ABC",
            "linkedin_profile_url": "https://www.linkedin.com/company/abc",
        }
    ]
    payload = {
        "resultObject": [
            {
                "profileUrl": "https://www.linkedin.com/company/abc/",
                "postUrl": "https://www.linkedin.com/feed/update/1",
                "postDate": "2026-09-15T01:00:00Z",
                "postContent": "A post",
            }
        ]
    }
    reporting_window = phantom.reporting_window(
        datetime(2026, 9, 16, tzinfo=timezone.utc),
        "Australia/Brisbane",
    )

    phantom_posts, phantom_errors = phantom.normalize_posts(
        payload, mappings, reporting_window
    )
    summarize_posts, summarize_errors = summarize.normalize_posts(
        payload, mappings, reporting_window
    )

    assert phantom_posts == summarize_posts
    assert phantom_errors == summarize_errors
