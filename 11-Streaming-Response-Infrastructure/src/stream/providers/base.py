"""Adapter contract every stream source (real or fake) implements.

Not the contract `stream.api` actually drives at runtime -- the live
providers (`ollama.py`, `openai_compat.py`, `gemini.py`, `fake.py`'s
`FakeProvider`) yield plain `str` chunks straight into `stream.session
.pump()`, bypassing `TokenChunk` entirely. This module and `fake.py`'s
`FakeAdapter` exist for `stream.metrics.time_stream`/its own tests; unclear
from this file alone whether that's intentional dual-contract design or a
leftover from an earlier shape -- see `stream.metrics` and
`tests/test_fake_adapter.py`.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TokenChunk:
    """One piece of a stream. Adapters yield raw text only -- no timing here.

    Timing is a cross-cutting concern applied uniformly by
    ``stream.metrics.time_stream`` so every adapter is measured the same way
    instead of each one rolling its own clock.
    """

    text: str
    done: bool = False


class StreamAdapter(Protocol):
    """A provider stream source: prompt in, token chunks out."""

    async def stream(self, prompt: str) -> AsyncIterator[TokenChunk]: ...
