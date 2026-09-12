"""Shared OpenAI-compatible Chat Completions client, reused by both the Agnes
AI provider and the generic openai_compatible provider.
"""

import openai
from openai import OpenAI

from src.providers.retry import call_with_retries


def is_5xx(exc: Exception) -> bool:
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


class OpenAICompatibleProvider:
    def __init__(
        self, *, api_key: str, base_url: str, reasoning_effort: str | None = None
    ) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._reasoning_effort = reasoning_effort

    def complete(
        self, *, system: str | None, user: str, model: str, think: bool | None = None
    ) -> str:
        # `think` has no equivalent here (this SDK's reasoning control is the
        # separate `reasoning_effort` param, already handled below) -- accepted
        # only so callers can pass it uniformly across providers.
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        kwargs: dict = {}
        if self._reasoning_effort is not None:
            kwargs["reasoning_effort"] = self._reasoning_effort

        def _call() -> str:
            # `**kwargs` carries only `reasoning_effort`, an optional keyword this
            # SDK's `create()` overloads all accept -- the dynamic splat just
            # doesn't match any one overload signature statically.
            response = self._client.chat.completions.create(  # ty: ignore[no-matching-overload]
                model=model, messages=messages, **kwargs
            )
            return response.choices[0].message.content or ""

        return call_with_retries(_call, is_retryable=is_5xx)
