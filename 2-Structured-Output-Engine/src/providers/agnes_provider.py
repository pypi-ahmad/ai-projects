"""Agnes AI — OpenAI-compatible Chat Completions endpoint (verified against
https://wiki.agnes-ai.com/en/docs/agnes-25-flash: same request/response
shape as OpenAI, Bearer auth, base URL below). That page's request-parameter
table lists model/messages/temperature/top_p/max_tokens/stream/tools/
tool_choice — no response_format or json_schema field — so structured
output always falls back to embedding the schema in the prompt here,
rather than assuming the endpoint would accept response_format.
"""

from __future__ import annotations

import httpx

from .base import DEFAULT_TIMEOUT_S, ProviderResponse, embed_schema_in_system_prompt
from .openai_compatible import OpenAICompatibleProvider

BASE_URL = "https://apihub.agnes-ai.com/v1"
DEFAULT_MODEL = "agnes-2.5-flash"


class AgnesProvider(OpenAICompatibleProvider):
    API_KEY_ENV_VAR = "AGNES_API_KEY"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            model, api_key=api_key, base_url=BASE_URL, reasoning_effort=None, timeout=timeout, client=client
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        if json_schema is not None:
            messages = embed_schema_in_system_prompt(messages, json_schema)
        return super().complete(messages, json_schema=None, temperature=temperature, max_tokens=max_tokens)
