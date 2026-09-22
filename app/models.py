from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MappingRecord:
    customer_name: str
    linkedin_profile_url: str


@dataclass(frozen=True)
class ReportingWindow:
    week_start: str
    week_end: str


@dataclass(frozen=True)
class NormalizedPost:
    customer_name: str
    linkedin_profile_url: str
    post_url: str
    post_date: str
    post_content: str
    post_type: str = ""
    like_count: Any = ""
    comment_count: Any = ""
    repost_count: Any = ""
    view_count: Any = ""
    img_url: str = ""
    video_url: str = ""
    content_summary: str = ""
    processing_status: str = "pending"
    processing_error: str = ""
    processed_at: str = ""

    def key(self) -> tuple[str, str, str]:
        return (self.customer_name, self.linkedin_profile_url, self.post_url)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
