from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .date_windows import reporting_window
from .models import MappingRecord, NormalizedPost, ReportingWindow
from .normalization import deduplicate_mappings
from .phantom_parser import normalize_posts
from .summarization import TextGenerator, summarize_customer_week, summarize_posts


def build_customer_rows(
    mappings: list[MappingRecord],
    posts: list[NormalizedPost],
    window: ReportingWindow,
    client: TextGenerator,
) -> tuple[list[dict[str, Any]], list[NormalizedPost]]:
    now = datetime.now(timezone.utc).isoformat()
    by_customer: dict[str, list[NormalizedPost]] = defaultdict(list)
    for post in posts:
        by_customer[post.customer_name].append(post)
    customers = {mapping.customer_name for mapping in mappings}
    summaries = {
        customer: summarize_customer_week(client, customer, by_customer.get(customer, []))
        for customer in customers
    }
    rows = [
        {
            "customer_name": customer,
            "week_start": window.week_start,
            "week_end": window.week_end,
            "post_count": len(by_customer.get(customer, [])),
            "weekly_synthesis": summaries[customer],
            "processed_at": now,
            "processing_status": "processed",
            "processing_error": "",
        }
        for customer in sorted(customers)
    ]
    return rows, posts


def process_payload(
    payload: dict[str, Any],
    mapping_rows: list[dict[str, str]],
    client: TextGenerator,
    reporting_date: datetime,
    timezone_name: str = "Australia/Brisbane",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    mappings = [MappingRecord(**row) for row in deduplicate_mappings(mapping_rows)]
    window = reporting_window(reporting_date, timezone_name)
    posts, errors = normalize_posts(payload, mappings, window, timezone_name)
    post_summaries = summarize_posts(client, posts)
    post_rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for post, summary in zip(posts, post_summaries):
        row = post.as_dict()
        row.update({
            "week_start": window.week_start,
            "week_end": window.week_end,
            "content_summary": summary,
            "processing_status": "processed",
            "processing_error": "",
            "processed_at": now,
        })
        post_rows.append(row)
    customer_rows, _ = build_customer_rows(mappings, posts, window, client)
    if errors:
        error_text = "; ".join(errors)
        for row in customer_rows:
            row["processing_status"] = "partial"
            row["processing_error"] = error_text
    return post_rows, customer_rows, errors
