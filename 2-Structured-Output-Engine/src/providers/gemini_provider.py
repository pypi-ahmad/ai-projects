"""Gemini provider via the Developer API's REST `generateContent` endpoint
(verified against the google-genai SDK docs: base URL
https://generativelanguage.googleapis.com/v1beta, auth via a `key` query
parameter, and `generationConfig.responseJsonSchema` — the field that takes
a standard JSON Schema directly, so Pydantic's `model_json_schema()` output
needs no type-casing conversion, unlike the older `responseSchema` field
which uses Gemini's own STRING/INTEGER/OBJECT enum). Raw REST rather than
the `google-genai` SDK so requests are mockable the same way as every other
adapter here.
"""

from __future__ import annotations

import os

import httpx

from .base import (
    DEFAULT_TIMEOUT_S,
    ProviderError,
    ProviderResponse,
    raise_for_status,
    request_with_retry,
)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    API_KEY_ENV_VAR = "GOOGLE_API_KEY"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        api_key = api_key if api_key is not None else os.environ.get(self.API_KEY_ENV_VAR)
        if not api_key:
            raise ProviderError("missing_api_key", f"{self.API_KEY_ENV_VAR} is not set")
        self.model = model
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        system_instruction, contents = self._to_gemini_contents(messages)
        generation_config: dict = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_schema is not None:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseJsonSchema"] = json_schema

        payload: dict = {"contents": contents, "generationConfig": generation_config}
        if system_instruction is not None:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        response = request_with_retry(
            self._client,
            "POST",
            f"{BASE_URL}/models/{self.model}:generateContent",
            params={"key": self.api_key},
            json=payload,
        )
        raise_for_status(response)
        data = response.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(
                "unsupported_response", f"Unexpected Gemini response shape: {data!r}"
            ) from exc
        return ProviderResponse(text=text, model=data.get("modelVersion", self.model), raw=data)

    @staticmethod
    def _to_gemini_contents(messages: list[dict[str, str]]) -> tuple[str | None, list[dict]]:
        """Gemini has no 'system' role in `contents` (it's a separate
        `systemInstruction` field) and calls the assistant role 'model'."""
        system_parts: list[str] = []
        contents: list[dict] = []
        for message in messages:
            if message["role"] == "system":
                system_parts.append(message["content"])
                continue
            role = "model" if message["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message["content"]}]})
        return ("\n\n".join(system_parts) if system_parts else None), contents
