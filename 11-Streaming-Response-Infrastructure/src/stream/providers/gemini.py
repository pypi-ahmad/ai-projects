"""Gemini streaming adapter -- native REST, verified by fetching
https://ai.google.dev/api/generate-content directly (not assumed):

    POST {base}/models/{model}:streamGenerateContent?alt=sse&key=API_KEY

SSE `data: {...}` lines, each a `GenerateContentResponse`; text lives at
`candidates[].content.parts[].text`, real usage (when present) at
`usageMetadata` -- captured opportunistically, never fabricated.

Every example on that page authenticates via `?key=`, not a header, so
that's what this uses. Our internal `messages` (`role`+`content`, OpenAI/
Ollama-style) get translated to Gemini's `contents`/`system_instruction`
shape: `assistant` -> `model`, `system` messages pulled out of `contents`
into `system_instruction` (a separate top-level field, confirmed by the
`system_instruction` mentions on that page).
"""

import json
from collections.abc import AsyncIterator

import httpx2 as httpx

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class GeminiAdapter:
    def __init__(
        self,
        model: str,
        messages: list[dict[str, str]],
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.messages = messages
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.usage: dict[str, int] | None = None
        self._transport = transport

    def _body(self) -> dict:
        system_text = "\n".join(m["content"] for m in self.messages if m["role"] == "system")
        contents = [
            {
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in self.messages
            if m["role"] != "system"
        ]
        body: dict = {"contents": contents}
        if system_text:
            body["system_instruction"] = {"parts": [{"text": system_text}]}
        return body

    async def __aiter__(self) -> AsyncIterator[str]:
        url = f"{self.base_url}/models/{self.model}:streamGenerateContent"
        # api_key rides in the URL, per the API's own auth scheme (see the
        # module docstring) -- an HTTP client error raised against this
        # request can embed the full URL, key included. stream.api never
        # surfaces a raw exception to a client for exactly this reason.
        params = {"alt": "sse", "key": self.api_key}
        async with (
            httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport) as client,
            client.stream("POST", url, params=params, json=self._body()) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = json.loads(line.removeprefix("data:").strip())
                usage = chunk.get("usageMetadata")
                if usage:
                    self.usage = usage
                for candidate in chunk.get("candidates", []):
                    for part in candidate.get("content", {}).get("parts", []):
                        text = part.get("text")
                        if text:
                            yield text
