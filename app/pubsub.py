from __future__ import annotations

import json
from typing import Any

from google.cloud import pubsub_v1


class PubSubPublisher:
    def __init__(self, topic: str) -> None:
        if not topic:
            raise ValueError("Pub/Sub topic is required")
        self._publisher = pubsub_v1.PublisherClient()
        self._topic = topic

    def publish(self, message: dict[str, Any]) -> str:
        future = self._publisher.publish(
            self._topic,
            json.dumps(message, ensure_ascii=False).encode("utf-8"),
        )
        return future.result()
