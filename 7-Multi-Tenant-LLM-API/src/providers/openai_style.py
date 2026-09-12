"""Shared calling code for both the generic OpenAI-compatible provider and
Agnes AI (also an OpenAI-compatible endpoint) -- see
openai_compatible_provider.py and agnes_provider.py.

Verified against installed openai==3.13.0 source: `max_tokens` is
deprecated in favor of `max_completion_tokens`; `OpenAIError` is the common
base for both `APIConnectionError` and `AuthenticationError`, so one except
clause covers "can't reach it" and "bad key" alike. The key is checked here
before ever constructing the client so a missing key is a deterministic,
network-free 503 rather than depending on exactly how/when the SDK's own
"missing credentials" error fires.
"""

from __future__ import annotations

from openai import OpenAI, OpenAIError

from src.providers.base import ProviderResult
from src.providers.errors import UpstreamUnavailableError


def complete_via_openai_client(
    *,
    api_key: str | None,
    base_url: str | None,
    model: str,
    messages: list[dict],
    max_tokens: int | None,
) -> ProviderResult:
    if not api_key:
        raise UpstreamUnavailableError("missing platform API key")

    client = OpenAI(api_key=api_key, base_url=base_url)
    kwargs = {"max_completion_tokens": max_tokens} if max_tokens is not None else {}

    try:
        response = client.chat.completions.create(model=model, messages=messages, **kwargs)
    except OpenAIError as exc:
        raise UpstreamUnavailableError(str(exc)) from exc

    usage = response.usage
    return ProviderResult(
        text=response.choices[0].message.content or "",
        in_tokens=usage.prompt_tokens if usage else 0,
        out_tokens=usage.completion_tokens if usage else 0,
    )
