"""Ollama streaming chat adapter.

Verified via context7 against https://docs.ollama.com/api/chat and
https://docs.ollama.com/api/streaming, not assumed: `/api/chat` streams
`application/x-ndjson`, one JSON object per line, each carrying a partial
`message.content`. The final line (`done: true`) carries the real
token-usage fields (`prompt_eval_count`/`eval_count`) -- captured here,
never fabricated before that line actually arrives.

A reasoning model (`qwen3.5:0.8b` included) streams its chain-of-thought
through a *separate* `message.thinking` field first, with `content` staying
empty for the whole thinking phase -- confirmed live, not assumed, after the
bench CLI reported 14-43s TTFTs for that model (see PHASES.md). This
adapter only ever surfaces `content` as tokens (`thinking` is a different
kind of output, not "the answer"), so pass `think=False` if you want a fast,
directly-comparable TTFT instead of one that includes reasoning time.
"""

import json
from collections.abc import AsyncIterator

import httpx2 as httpx

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class OllamaAdapter:
    def __init__(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        think: bool | str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.messages = messages
        self.think = think
        self.base_url = base_url
        self.usage: dict[str, int | None] | None = None
        self._transport = transport

    async def __aiter__(self) -> AsyncIterator[str]:
        body: dict = {"model": self.model, "messages": self.messages, "stream": True}
        if self.think is not None:
            body["think"] = self.think
        async with (
            httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport) as client,
            client.stream("POST", f"{self.base_url}/api/chat", json=body) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                if chunk.get("done"):
                    self.usage = {
                        "prompt_tokens": chunk.get("prompt_eval_count"),
                        "completion_tokens": chunk.get("eval_count"),
                    }
