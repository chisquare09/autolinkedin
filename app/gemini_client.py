from __future__ import annotations

import logging
import time

from google import genai


logger = logging.getLogger(__name__)


class GeminiTextGenerator:
    def __init__(self, api_key: str, model_name: str) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required")
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name

    def generate(self, contents: str, system_instruction: str = "") -> str:
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=contents,
                    config={
                        "response_mime_type": "application/json",
                        "system_instruction": system_instruction,
                    },
                )
                break
            except Exception as exc:
                message = str(exc).upper()
                transient = "503" in message or "UNAVAILABLE" in message
                if not transient or attempt == max_attempts - 1:
                    raise
                delay = 2 ** attempt
                logger.warning(
                    "Gemini temporarily unavailable; retrying in %s seconds "
                    "(attempt %s/%s)",
                    delay,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(delay)
        if not response.text:
            raise RuntimeError("Gemini returned an empty response")
        return response.text
