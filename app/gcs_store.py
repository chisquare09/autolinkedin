from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from google.cloud import storage


class GCSRawPayloadStore:
    def __init__(self, bucket_name: str) -> None:
        if not bucket_name:
            raise ValueError("GCS bucket name is required")
        self._bucket = storage.Client().bucket(bucket_name)

    def save(self, job_id: str, payload: dict[str, Any]) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        object_name = f"scrapes/{timestamp[:8]}/{job_id}.json"
        self._bucket.blob(object_name).upload_from_string(
            json.dumps(payload, ensure_ascii=False),
            content_type="application/json",
        )
        return f"gs://{self._bucket.name}/{object_name}"
