"""FAKE adapter -- test-only. Never wire this into a real provider config.

Emulates chunked output with an artificial per-chunk delay so backpressure,
reconnect, and timing logic can be exercised without a live model. Real
provider adapters (Ollama, OpenAI-compatible, Agnes, Gemini) always stream
their own genuine chunks; this is the one place a stream is manufactured, and
it says so.

`FakeAdapter` (the `TokenChunk`/`StreamAdapter` shape, see `base.py`) and
`FakeProvider` (the plain-`str` shape `stream.session.pump` expects) are
deliberately two different classes for two different, unrelated contracts
-- not duplication to consolidate.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence

from stream.providers.base import TokenChunk

DEFAULT_TEXT = "The quick brown fox jumps over the lazy dog."


class FakeAdapter:
    """Splits `text` on spaces and yields one word per chunk, `delay_s` apart."""

    def __init__(self, text: str = DEFAULT_TEXT, delay_s: float = 0.05) -> None:
        self.text = text
        self.delay_s = delay_s

    async def stream(self, prompt: str) -> AsyncIterator[TokenChunk]:
        del prompt  # fake adapter ignores the prompt; it always replays `self.text`
        words = self.text.split(" ")
        for i, word in enumerate(words):
            await asyncio.sleep(self.delay_s)
            yield TokenChunk(text=word if i == 0 else f" {word}")
        yield TokenChunk(text="", done=True)


class FakeProvider:
    """Test-only. Yields plain `tokens` one at a time, `delay_s` apart.

    Feeds `StreamSession.append` directly -- unlike `FakeAdapter`/
    `StreamAdapter`, there's no `TokenChunk` here; the session layer only
    ever sees raw strings.
    """

    def __init__(self, tokens: Sequence[str], delay_s: float = 0.0) -> None:
        self.tokens = tokens
        self.delay_s = delay_s

    async def __aiter__(self) -> AsyncIterator[str]:
        for token in self.tokens:
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield token
