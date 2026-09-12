"""Local Ollama provider, talking /api/chat directly over HTTP (verified
against docs.ollama.com/api and the ollama-python client docs).

Structured-output support (`format` as a JSON Schema object, not just
`"json"`) was added in Ollama 0.5.0. Rather than assume the installed build
supports it, `complete()` checks `/api/version` once (cached) and falls
back to embedding the schema in the system prompt on older servers.

One heavy model at a time on an 8GB GPU: `unload()` frees VRAM immediately
(see NOTES.md / docs/RUNBOOK.md).
"""

from __future__ import annotations

import os

import httpx

from .base import (
    DEFAULT_TIMEOUT_S,
    ProviderResponse,
    embed_schema_in_system_prompt,
    raise_for_status,
    request_with_retry,
)

# Full local allowlist (NOTES.md) — only the two default models are
# exercised by the engine today; the rest are reserved for later phases.
ALLOWED_MODELS = frozenset(
    {
        "granite4.1:3b",
        "qwen3.5:2b",
        "qwen3.5:0.8b",
        "qwen3-vl:2b",
        "qwen3-embedding:0.6b",
        "qwen3-embedding:4b",
        "translategemma:4b",
        "AuditAid/PaddleOCR-VL-1.6-0.9B",
    }
)

STRUCTURED_OUTPUT_MIN_VERSION = (0, 5, 0)


class OllamaProvider:
    def __init__(
        self,
        model: str,
        *,
        host: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)
        self._supports_json_schema: bool | None = None  # detected lazily, cached

    def supports_json_schema(self) -> bool:
        if self._supports_json_schema is None:
            response = request_with_retry(self._client, "GET", f"{self.host}/api/version")
            raise_for_status(response)
            version = response.json().get("version", "0.0.0")
            parts = tuple(int(p) for p in version.split(".")[:3])
            self._supports_json_schema = parts >= STRUCTURED_OUTPUT_MIN_VERSION
        return self._supports_json_schema

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
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_schema is not None:
            if self.supports_json_schema():
                payload["format"] = json_schema
            else:
                payload["messages"] = embed_schema_in_system_prompt(messages, json_schema)

        response = request_with_retry(self._client, "POST", f"{self.host}/api/chat", json=payload)
        raise_for_status(response)
        data = response.json()
        text = data.get("message", {}).get("content", "")
        return ProviderResponse(text=text, model=data.get("model", self.model), raw=data)

    def installed_models(self) -> set[str]:
        """Locally pulled models that are also on the allowlist."""
        response = request_with_retry(self._client, "GET", f"{self.host}/api/tags")
        raise_for_status(response)
        installed = {m["model"] for m in response.json().get("models", [])}
        return installed & ALLOWED_MODELS

    def unload(self, model: str | None = None) -> None:
        """Free VRAM immediately so the next stage's model can load."""
        response = request_with_retry(
            self._client,
            "POST",
            f"{self.host}/api/generate",
            json={"model": model or self.model, "keep_alive": 0},
        )
        raise_for_status(response)
