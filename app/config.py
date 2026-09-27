from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    output_spreadsheet_id: str
    pubsub_topic: str
    pubsub_subscription: str
    gemini_model_name: str
    reporting_timezone: str
    webhook_auth_mode: str
    webhook_bearer_token: str
    webhook_secret: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            output_spreadsheet_id=os.getenv("OUTPUT_SPREADSHEET_ID", ""),
            pubsub_topic=os.getenv("PUBSUB_TOPIC", ""),
            pubsub_subscription=os.getenv("PUBSUB_SUBSCRIPTION", ""),
            gemini_model_name=os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash"),
            reporting_timezone=os.getenv("REPORTING_TIMEZONE", "Australia/Brisbane"),
            webhook_auth_mode=os.getenv("WEBHOOK_AUTH_MODE", "bearer"),
            webhook_bearer_token=os.getenv("WEBHOOK_BEARER_TOKEN", ""),
            webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
        )

    def validate(self) -> None:
        required = {
            "OUTPUT_SPREADSHEET_ID": self.output_spreadsheet_id,
            "PUBSUB_TOPIC": self.pubsub_topic,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        if self.webhook_auth_mode == "bearer" and not self.webhook_bearer_token:
            raise ValueError("WEBHOOK_BEARER_TOKEN is required in bearer mode")
        if self.webhook_auth_mode == "query_secret" and not self.webhook_secret:
            raise ValueError("WEBHOOK_SECRET is required in query_secret mode")
