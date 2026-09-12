"""Provider adapter protocol - what TracedClient needs from any provider.

No tracing/pricing logic here - client.py owns that. An adapter here must
be synchronous and must not raise anything client.py needs to interpret
specially; any exception just propagates and marks the span as errored.
Next file to read: ollama.py (the only adapter implemented so far).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class CompletionResult:
    text: str
    in_tokens: int | None = None
    out_tokens: int | None = None
    ttft_ms: float | None = None


class ProviderAdapter(Protocol):
    # positional-only: TracedClient always calls this positionally, and it
    # lets implementers/fakes name these params however they like.
    def complete(self, messages: list[dict[str, str]], model: str, /) -> CompletionResult: ...
