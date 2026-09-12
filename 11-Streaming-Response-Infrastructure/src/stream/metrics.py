"""Uniform timing wrapper for any adapter's chunk stream.

Every adapter and every consumer (smoke tests, the SSE server) measures TTFT
and inter-token gaps through this one wrapper, so the clock logic exists
exactly once instead of once per adapter.

Not currently on `stream.api`'s request path -- `StreamSession` times
itself directly (see `stream.session`). This module operates on
`stream.providers.base.TokenChunk`, the adapter contract the live
providers don't use; see that file for why both contracts exist.
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from stream.providers.base import TokenChunk


@dataclass(frozen=True, slots=True)
class TimedChunk:
    chunk: TokenChunk
    elapsed_s: float
    """Seconds since the first chunk was requested (stream start)."""
    gap_s: float | None
    """Seconds since the previous chunk. None for the first chunk."""


async def time_stream(chunks: AsyncIterator[TokenChunk]) -> AsyncIterator[TimedChunk]:
    start = time.monotonic()
    last: float | None = None
    async for chunk in chunks:
        now = time.monotonic()
        gap = None if last is None else now - last
        last = now
        yield TimedChunk(chunk=chunk, elapsed_s=now - start, gap_s=gap)


def ttft_s(timed_chunks: list[TimedChunk]) -> float | None:
    """Time to first chunk carrying non-empty text, or None if none did."""
    for tc in timed_chunks:
        if tc.chunk.text:
            return tc.elapsed_s
    return None
