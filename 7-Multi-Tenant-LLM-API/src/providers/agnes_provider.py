"""Agnes AI -- an OpenAI-compatible endpoint at a fixed base URL (per spec,
not configurable via env). `complete()` is called only from
src/providers/registry.py::dispatch."""

from __future__ import annotations

import os

from src.providers.base import ProviderResult
from src.providers.openai_style import complete_via_openai_client

AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"


def complete(model: str, messages: list[dict], max_tokens: int | None) -> ProviderResult:
    # This dev machine has AGNESAI_API_KEY configured, not AGNES_API_KEY --
    # see .env.example. Accept either so either naming works.
    api_key = os.environ.get("AGNES_API_KEY") or os.environ.get("AGNESAI_API_KEY")
    return complete_via_openai_client(
        api_key=api_key,
        base_url=AGNES_BASE_URL,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
