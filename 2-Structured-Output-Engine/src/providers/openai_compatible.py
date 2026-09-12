"""OpenAI-style Chat Completions provider (verified current shape against
the OpenAI API reference: `response_format: {type: "json_schema", ...}`
for structured outputs, `reasoning_effort` for reasoning models).

Works against any OpenAI-compatible endpoint via OPENAI_BASE_URL — built
for gpt-5.6-luna / gpt-5.6-terra (NOTES.md: "medium effort"), hence the
`reasoning_effort` default. AgnesProvider subclasses this for Agnes AI's
Chat Completions endpoint, which is OpenAI-compatible but does not
document a response_format/json_schema parameter (checked directly against
https://wiki.agnes-ai.com/en/docs/agnes-25-flash) — it overrides
`complete()` to fall back to prompt-embedded schema unconditionally.
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


class OpenAICompatibleProvider:
    API_KEY_ENV_VAR = "OPENAI_API_KEY"
    BASE_URL_ENV_VAR = "OPENAI_BASE_URL"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        reasoning_effort: str | None = "medium",
        timeout: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        api_key = api_key if api_key is not None else os.environ.get(self.API_KEY_ENV_VAR)
        base_url = base_url if base_url is not None else os.environ.get(self.BASE_URL_ENV_VAR)
        if not api_key:
            raise ProviderError("missing_api_key", f"{self.API_KEY_ENV_VAR} is not set")
        if not base_url:
            raise ProviderError("missing_base_url", f"{self.BASE_URL_ENV_VAR} is not set")

        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.reasoning_effort = reasoning_effort
        self._client = client or httpx.Client(timeout=timeout)

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        payload: dict = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": json_schema, "strict": True},
            }

        response = request_with_retry(
            self._client,
            "POST",
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        raise_for_status(response)
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        return ProviderResponse(text=text, model=data.get("model", self.model), raw=data)
