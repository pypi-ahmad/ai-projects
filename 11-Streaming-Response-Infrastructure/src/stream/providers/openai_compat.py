"""Generic OpenAI-compatible streaming chat adapter.

Verified via context7 against OpenAI's own API reference: SSE `data: {...}`
lines, `choices[0].delta.content` per chunk, a final `data: [DONE]` line.
`stream_options: {"include_usage": true}` asks for one extra usage-only
chunk (empty `choices`, real `usage`) right before `[DONE]` -- captured
opportunistically here, never fabricated if a server ignores the option
(Agnes's docs don't confirm it supports it, so usage just stays `None` for
requests where no chunk ever carries one).

Reused for any OpenAI-compatible endpoint: a real OpenAI-style deployment,
and Agnes AI (confirmed OpenAI-compatible and stream-capable via its own
docs, context7 -- see PHASES.md).
"""

import json
from collections.abc import AsyncIterator

import httpx2 as httpx

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class OpenAICompatAdapter:
    # base_url/api_key are always caller-supplied from server-side env vars
    # (see stream.config/stream.api._build_adapter); this class never reads
    # the environment itself and never receives them from request input.
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.messages = messages
        self.usage: dict[str, int] | None = None
        self._transport = transport

    async def __aiter__(self) -> AsyncIterator[str]:
        body = {
            "model": self.model,
            "messages": self.messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with (
            httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport) as client,
            client.stream(
                "POST", f"{self.base_url}/chat/completions", json=body, headers=headers
            ) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line.removeprefix("data:").strip()
                if payload == "[DONE]":
                    break
                chunk = json.loads(payload)
                usage = chunk.get("usage")
                if usage:
                    self.usage = usage
                choices = chunk.get("choices") or []
                if not choices:
                    continue  # the usage-only chunk has no choices
                content = choices[0].get("delta", {}).get("content")
                if content:
                    yield content
