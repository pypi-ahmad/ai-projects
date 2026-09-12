"""Generic OpenAI-compatible endpoint -- base URL and key are operator
config (OPENAI_BASE_URL / OPENAI_API_KEY), unlike Agnes's fixed URL.
`complete()` is called only from src/providers/registry.py::dispatch."""

from __future__ import annotations

import os

from src.providers.base import ProviderResult
from src.providers.openai_style import complete_via_openai_client


def complete(model: str, messages: list[dict], max_tokens: int | None) -> ProviderResult:
    return complete_via_openai_client(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL"),
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
