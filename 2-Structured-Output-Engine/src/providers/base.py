"""Shared provider interface: chat-style messages in, raw text out. No
schema validation here (see docs/TECHNICAL.md and engine/result.py) — a
later phase wires provider output through StructuredResult.

Every adapter talks HTTP directly via httpx so requests are mockable in
tests without live API keys (see tests/test_providers.py). Two HTTP-layer
behaviors are shared by every adapter: retry once on a 5xx response (2
attempts total; no retry on other statuses or on timeouts), and translate
error responses into a ProviderError with a stable `code` instead of an
httpx exception/traceback reaching the caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import httpx

DEFAULT_TIMEOUT_S = 30.0


class ProviderError(Exception):
    """A provider failure with a stable, catchable `code` — never a bare
    exception/stack trace surfaced to a UI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __repr__(self) -> str:
        return f"ProviderError(code={self.code!r}, message={self.message!r})"


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    model: str
    raw: dict


class Provider(Protocol):
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ProviderResponse: ...


def request_with_retry(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """`client.request(method, url, **kwargs)` with the shared retry policy:
    2 attempts total, retried only when the first attempt returns a 5xx.
    Network/timeout errors are not retried — they become a ProviderError
    immediately."""
    response: httpx.Response | None = None
    for attempt in range(2):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", f"{method} {url} timed out") from exc
        except httpx.ConnectError as exc:
            raise ProviderError("connection_error", f"Could not connect to {url}: {exc}") from exc
        if response.status_code >= 500 and attempt == 0:
            continue
        return response
    assert response is not None  # loop always assigns or raises
    return response


def embed_schema_in_system_prompt(messages: list[dict[str, str]], json_schema: dict) -> list[dict[str, str]]:
    """Fallback for providers/servers without a structured-output API: ask
    for compliant JSON in plain language instead of constraining decoding."""
    instruction = (
        "Respond with a single JSON object only — no markdown, no explanation — "
        f"matching exactly this JSON Schema:\n{json.dumps(json_schema)}"
    )
    return [{"role": "system", "content": instruction}, *messages]


def raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status in (401, 403):
        raise ProviderError(
            "unauthorized", f"{response.request.url} returned {status} — check the API key."
        )
    if status == 404:
        raise ProviderError(
            "not_found", f"{response.request.url} returned 404 — check the base URL/model name."
        )
    if status >= 400:
        raise ProviderError(
            "http_error", f"{response.request.url} returned {status}: {response.text[:300]}"
        )
