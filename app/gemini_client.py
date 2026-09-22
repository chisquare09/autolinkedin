from __future__ import annotations

from google import genai


class GeminiTextGenerator:
    def __init__(self, api_key: str, model_name: str) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required")
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name

    def generate(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        if not response.text:
            raise RuntimeError("Gemini returned an empty response")
        return response.text
