from __future__ import annotations

import json
from typing import Any

from .models import MappingRecord, NormalizedPost, ReportingWindow
from .normalization import normalize_profile_url
from .date_windows import is_in_window


def parse_result_object(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("resultObject", payload.get("result", []))
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError as exc:
            raise ValueError("resultObject is not valid JSON") from exc
    if not isinstance(result, list):
        raise ValueError("resultObject must be a list")
    return [item for item in result if isinstance(item, dict)]


def normalize_posts(
    payload: dict[str, Any],
    mappings: list[MappingRecord],
    window: ReportingWindow,
    timezone_name: str = "Australia/Brisbane",
) -> tuple[list[NormalizedPost], list[str]]:
    by_url = {normalize_profile_url(row.linkedin_profile_url): row for row in mappings}
    posts: list[NormalizedPost] = []
    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in parse_result_object(payload):
        if raw.get("error"):
            errors.append(str(raw["error"]))
            continue
        profile_raw = raw.get("profileUrl") or raw.get("authorUrl") or raw.get("url")
        try:
            profile_url = normalize_profile_url(str(profile_raw or ""))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        mapping = by_url.get(profile_url)
        if mapping is None:
            errors.append(f"profile is not in customer_info: {profile_url}")
            continue
        post_date = str(raw.get("postDate") or raw.get("postTimestamp") or raw.get("timestamp") or "")
        try:
            if not is_in_window(post_date, window, timezone_name):
                continue
        except ValueError as exc:
            errors.append(str(exc))
            continue
        post_url = str(raw.get("postUrl") or raw.get("sharedPostUrl") or "").strip()
        content = str(raw.get("postContent") or raw.get("textContent") or "").strip()
        if not post_url or not content:
            errors.append(f"post missing URL or content for {profile_url}")
            continue
        post = NormalizedPost(
            customer_name=mapping.customer_name,
            linkedin_profile_url=profile_url,
            post_url=post_url,
            post_date=post_date,
            post_content=content,
            post_type=str(raw.get("type") or ""),
            like_count=raw.get("likeCount", ""),
            comment_count=raw.get("commentCount", ""),
            repost_count=raw.get("repostCount", ""),
            view_count=raw.get("viewCount", ""),
            img_url=str(raw.get("imgUrl") or ""),
            video_url=str(raw.get("videoUrl") or ""),
        )
        if post.key() not in seen:
            seen.add(post.key())
            posts.append(post)
    return posts, errors
