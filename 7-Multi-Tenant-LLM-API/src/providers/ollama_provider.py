"""Verified against installed ollama==0.6.2 source: `Client.chat()` returns
a `ChatResponse` with `.message.content`, `.prompt_eval_count` (in),
`.eval_count` (out); an unreachable host is re-raised by the client itself
as stdlib `ConnectionError` (it catches httpx.ConnectError internally).

`complete()` is called only from src/providers/registry.py::dispatch, never
imported directly by route code."""

from __future__ import annotations

import os

import ollama

from src.providers.base import ProviderResult
from src.providers.errors import UpstreamUnavailableError


def complete(model: str, messages: list[dict], max_tokens: int | None) -> ProviderResult:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    client = ollama.Client(host=host)
    options = {"num_predict": max_tokens} if max_tokens is not None else {}

    try:
        response = client.chat(model=model, messages=messages, options=options)
    except ConnectionError as exc:
        raise UpstreamUnavailableError(str(exc)) from exc

    return ProviderResult(
        text=response.message.content or "",
        in_tokens=response.prompt_eval_count or 0,
        out_tokens=response.eval_count or 0,
    )
