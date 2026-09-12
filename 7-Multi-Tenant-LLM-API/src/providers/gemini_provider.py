"""Verified against installed google-genai==2.23.0 source:
`client.models.generate_content` accepts a plain string for `contents` and
a plain dict for `config`; usage lives on `response.usage_metadata`;
`google.genai.errors.APIError` is the common base for both `ClientError`
and `ServerError`. Key is checked before constructing the client for the
same reason as the OpenAI-style providers (deterministic, network-free
503). `complete()` is called only from src/providers/registry.py::dispatch."""

from __future__ import annotations

import os

from google import genai
from google.genai.errors import APIError

from src.providers.base import ProviderResult
from src.providers.errors import UpstreamUnavailableError


def complete(model: str, messages: list[dict], max_tokens: int | None) -> ProviderResult:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise UpstreamUnavailableError("missing platform API key")

    client = genai.Client(api_key=api_key)
    contents = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    config = {"max_output_tokens": max_tokens} if max_tokens is not None else None

    try:
        response = client.models.generate_content(model=model, contents=contents, config=config)
    except APIError as exc:
        raise UpstreamUnavailableError(str(exc)) from exc

    usage = response.usage_metadata
    return ProviderResult(
        text=response.text or "",
        in_tokens=(usage.prompt_token_count or 0) if usage else 0,
        out_tokens=(usage.candidates_token_count or 0) if usage else 0,
    )
