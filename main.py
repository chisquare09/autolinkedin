from __future__ import annotations

import os
import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query

from app.config import Settings
from app.pubsub import PubSubPublisher
from app.webhook import authorize

app = FastAPI(title="LinkedIn Activity Tracker")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook")
def webhook(
    payload: dict[str, Any],
    authorization: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> dict[str, str]:
    settings = Settings.from_env()
    try:
        authorize(
            {"authorization": authorization or ""},
            mode=settings.webhook_auth_mode,
            bearer_token=settings.webhook_bearer_token,
            query_secret=secret or "",
            expected_secret=settings.webhook_secret,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    job_id = str(uuid.uuid4())
    report_date = datetime.now(timezone.utc).isoformat()
    message = {
        "job_id": job_id,
        "payload": payload,
        "reporting_date": report_date,
    }
    try:
        settings.validate()
        if settings.processing_mode == "direct":
            process_job(message)
            return {"status": "processed", "job_id": job_id}
        PubSubPublisher(settings.pubsub_topic).publish(message)
    except Exception as exc:
        detail = "Unable to process webhook job" if settings.processing_mode == "direct" else "Unable to queue webhook job"
        raise HTTPException(status_code=503, detail=detail) from exc
    return {"status": "accepted", "job_id": job_id}


def process_job(message: dict[str, Any]) -> None:
    """Process one job in either direct prototype or Pub/Sub delivery mode."""
    from app.gemini_client import GeminiTextGenerator
    from app.processor import process_payload
    from app.sheets_store import SheetsStore

    settings = Settings.from_env()
    payload = message["payload"]
    job_id = str(message["job_id"])
    sheets = SheetsStore(settings.output_spreadsheet_id)
    mappings = sheets.read_customer_info()
    client = GeminiTextGenerator(os.environ["GEMINI_API_KEY"], settings.gemini_model_name)
    report_date = datetime.fromisoformat(message["reporting_date"].replace("Z", "+00:00"))
    post_rows, weekly_rows, errors = process_payload(payload, mappings, client, report_date, settings.reporting_timezone)
    sheets.upsert_post_details(post_rows)
    sheets.upsert_weekly_summary(weekly_rows)
    if errors:
        print({"job_id": job_id, "processing_errors": errors})


def process_pubsub_message(message: dict[str, Any]) -> None:
    process_job(message)


@app.post("/pubsub")
def pubsub_push(envelope: dict[str, Any]) -> dict[str, str]:
    """Process a Pub/Sub push envelope and acknowledge only after processing."""
    message = envelope.get("message", {})
    encoded = message.get("data")
    if not encoded:
        raise HTTPException(status_code=400, detail="Pub/Sub message data is missing")
    try:
        decoded = json.loads(base64.b64decode(encoded).decode("utf-8"))
        process_pubsub_message(decoded)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Pub/Sub job") from exc
    return {"status": "processed"}
