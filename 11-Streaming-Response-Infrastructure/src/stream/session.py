"""In-memory per-stream session: event log, bounded buffer, replay, backpressure.

Wired to real HTTP in `stream.api` (phase 4) -- see PHASES.md. This is the
session buffer from docs/ARCHITECTURE.md: `append` records tokens,
`replay(after_id)` is what a reconnect reads to resume from `Last-Event-ID`,
and both eviction rules (`max_events`, `ttl_s`) count toward `dropped_count`
-- data a reconnect can no longer recover.

`buffer_len`/`ack`/`pump` are a second, separate concept from that replay
buffer: how far behind the *live* SSE writer is, not how much replay history
is retained. Acking never touches the replay deque or `dropped_count` from
eviction -- it only tells the backpressure pump it can keep pulling.

Must not: hold any per-request/HTTP state (that's `stream.api`'s job) or
call out to a provider directly (that's `stream.providers.*`, driven
through `pump()` below). Next module to read: `stream.api`, which is the
only thing that constructs a `StreamSession` and drives `pump()`/`tail()`.
"""

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass

from stream.config import BackpressureConfig


@dataclass(frozen=True, slots=True)
class Event:
    id: int
    type: str
    data: str
    ts_monotonic: float


@dataclass(frozen=True, slots=True)
class SessionMetrics:
    ttft_ms: float | None
    token_count: int
    done_reason: str | None


class StreamSession:
    """One generation's event log. `max_events` bounds memory, `ttl_s` bounds age."""

    def __init__(self, id: str, max_events: int = 256, ttl_s: float = 300.0) -> None:
        self.id = id
        # created_at is wall-clock (time.time()) for display/logging only;
        # every duration/eviction comparison below uses time.monotonic(),
        # which is immune to system clock changes. Don't diff the two.
        self.created_at = time.time()
        self.max_events = max_events
        self.ttl_s = ttl_s
        # One counter, four causes: max_events overflow, ttl_s expiry, and
        # pump()'s two backpressure fallbacks (evict_oldest/record_dropped).
        # It answers "did the client lose anything replayable", not "why".
        self.dropped_count = 0
        self.done_reason: str | None = None
        self.connect_count = 0

        self._start = time.monotonic()
        self._t_first: float | None = None
        self._token_count = 0
        self._next_id = 0
        self._events: deque[Event] = deque(maxlen=max_events)
        self._acked_id = 0
        self._new_event = asyncio.Event()

    def _evict_expired(self, now: float) -> None:
        # ttl_s is seconds of buffer age, not session age -- an event is
        # evicted `ttl_s` after it was appended, regardless of when the
        # session started.
        while self._events and now - self._events[0].ts_monotonic > self.ttl_s:
            self._events.popleft()
            self.dropped_count += 1

    def _append_event(self, event_type: str, data: str) -> Event:
        now = time.monotonic()
        self._evict_expired(now)
        if len(self._events) == self._events.maxlen:
            self.dropped_count += 1  # about to overflow -- deque(maxlen=..) will drop the oldest
        self._next_id += 1
        event = Event(id=self._next_id, type=event_type, data=data, ts_monotonic=now)
        self._events.append(event)
        self._new_event.set()
        return event

    def append(self, token: str) -> Event:
        if self._t_first is None:
            self._t_first = time.monotonic()
        self._token_count += 1
        return self._append_event("token", token)

    def replay(self, after_id: int) -> list[Event]:
        """Currently-buffered events with id > after_id. Evicted ids are just absent."""
        return [e for e in self._events if e.id > after_id]

    async def tail(self, after_id: int) -> AsyncIterator[Event]:
        """Replay buffered events after `after_id`, then yield new ones as they
        arrive, until the session is done (the terminal `done`/`error` event
        is included). This is what a GET route iterates for both a fresh
        stream and a `Last-Event-ID` reconnect -- same code path either way.

        Safe to call more than once concurrently for the same session (e.g.
        two open connections to one session_id): each call tracks its own
        `last` cursor and `replay()` is a pure read, so `_new_event` being a
        single shared Event (not a per-caller queue) can't cause one reader
        to consume a wakeup meant for another.
        """
        last = after_id
        for event in self.replay(last):
            yield event
            last = event.id
        while self.done_reason is None or last < self._next_id:
            await self._new_event.wait()
            self._new_event.clear()
            for event in self.replay(last):
                yield event
                last = event.id

    def complete(self) -> Event:
        self.done_reason = "complete"
        return self._append_event("done", "")

    def fail(self, code: str) -> Event:
        self.done_reason = code
        return self._append_event("error", code)

    def metrics(self) -> SessionMetrics:
        ttft_ms = None if self._t_first is None else (self._t_first - self._start) * 1000
        return SessionMetrics(
            ttft_ms=ttft_ms, token_count=self._token_count, done_reason=self.done_reason
        )

    @property
    def last_id(self) -> int:
        """The highest event id ever assigned, whether or not it's still buffered."""
        return self._next_id

    @property
    def reconnects(self) -> int:
        """`connect_count` counts every GET, including the first read; this is just the resumes."""
        return max(self.connect_count - 1, 0)

    @property
    def buffer_len(self) -> int:
        """Events appended but not yet acked by the live SSE writer."""
        return self._next_id - self._acked_id

    def ack(self, event_id: int) -> None:
        """The live writer has sent up through `event_id`; let the pump keep pulling."""
        self._acked_id = max(self._acked_id, event_id)

    def evict_oldest(self) -> None:
        """Force-drop the oldest buffered (still-replayable) event. Backpressure only."""
        if self._events:
            self._events.popleft()
            self.dropped_count += 1

    def record_dropped(self) -> None:
        """Count a token discarded before ever being buffered. Backpressure only."""
        self.dropped_count += 1

    async def wait_until_drained(self, low_watermark: int, poll_interval_s: float) -> None:
        # ponytail: polls rather than waking on ack() -- fine at these
        # watermark sizes; switch to an asyncio.Event set from ack() if a
        # profiler ever shows this loop mattering.
        while self.buffer_len > low_watermark:
            await asyncio.sleep(poll_interval_s)


async def pump(
    provider: AsyncIterator[str],
    session: StreamSession,
    config: BackpressureConfig,
    *,
    can_pause: bool = True,
) -> None:
    """Pull tokens from `provider` into `session`, honoring backpressure.

    `can_pause=True` -- FakeProvider, Ollama, or anything else where we own
    the read loop: once `buffer_len` hits `high_watermark`, simply don't ask
    the provider for the next token until it drains to `low_watermark`.
    `can_pause=False` -- a provider whose upstream keeps producing whether we
    read it or not: apply `config.drop_oldest_replayable` instead of
    blocking, since blocking wouldn't stop anything from piling up anyway.
    """
    async for token in provider:
        if session.buffer_len >= config.high_watermark:
            if can_pause:
                await session.wait_until_drained(config.low_watermark, config.poll_interval_s)
            elif config.drop_oldest_replayable:
                session.evict_oldest()
            else:
                session.record_dropped()
                continue
        session.append(token)
