"""TracedClient: wraps a provider adapter with a span, records usage/ttft,
always exports (span export runs on __exit__ regardless of success/failure).

The "generate" span here becomes a child of whatever span is already
active in the current context (see trace/tracer.py's contextvar-based
parenting) - callers that want it nested under a "request" span (e.g.
api/app.py's /v1/demo/complete) must already be inside a `with
Tracer.start(...)` block before calling .complete().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from obs.providers.ollama import OllamaAdapter
from obs.trace import Tracer

if TYPE_CHECKING:
    from obs.providers.base import ProviderAdapter


@dataclass
class TracedCompletion:
    text: str
    trace_id: str
    in_tokens: int | None
    out_tokens: int | None
    ttft_ms: float | None


def default_adapters() -> dict[str, ProviderAdapter]:
    """Only Ollama is wired up. Agnes AI / OpenAI-compatible / Gemini adapters
    are not implemented yet - see docs/ARCHITECTURE.md."""
    return {"ollama": OllamaAdapter()}


class TracedClient:
    def __init__(self, adapters: dict[str, ProviderAdapter] | None = None) -> None:
        self.adapters = adapters if adapters is not None else default_adapters()

    def complete(
        self, messages: list[dict[str, str]], provider: str, model: str
    ) -> TracedCompletion:
        adapter = self.adapters.get(provider)
        if adapter is None:
            msg = f"no adapter registered for provider {provider!r}"
            raise ValueError(msg)

        with Tracer.start("generate", kind="client") as span:
            span.set(provider=provider, model=model)
            span.set_prompt("\n".join(m.get("content", "") for m in messages))
            result = adapter.complete(messages, model)
            span.set_usage(
                in_tokens=result.in_tokens, out_tokens=result.out_tokens, ttft_ms=result.ttft_ms
            )
            trace_id = span.trace_id

        return TracedCompletion(
            text=result.text,
            trace_id=trace_id,
            in_tokens=result.in_tokens,
            out_tokens=result.out_tokens,
            ttft_ms=result.ttft_ms,
        )
