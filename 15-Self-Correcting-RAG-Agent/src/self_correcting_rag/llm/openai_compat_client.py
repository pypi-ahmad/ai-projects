"""Shared OpenAI-compatible Chat Completions client, reused by both the Agnes
AI provider and the generic openai_compatible provider -- Agnes AI's own docs
(wiki.agnes-ai.com) describe it as an OpenAI-compatible Chat Completions
integration at the same /v1/chat/completions shape, so one client suffices.
"""

from openai import OpenAI


class OpenAICompatibleProvider:
    def __init__(self, *, api_key: str, base_url: str, reasoning_effort: str | None = None) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._reasoning_effort = reasoning_effort

    def complete(self, *, system: str, user: str, model: str) -> str:
        kwargs: dict = {}
        if self._reasoning_effort is not None:
            kwargs["reasoning_effort"] = self._reasoning_effort
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        return response.choices[0].message.content or ""
