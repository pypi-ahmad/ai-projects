"""SSE wire-format encoding.

Fields verified against the WHATWG spec, not assumed -- see docs/SSE.md.
Consumes `stream.session.Event`, wired to the real `GET /v1/stream/{id}`
route in `stream.api` (phase 4). FastAPI (checked via context7) also ships
its own `fastapi.sse.EventSourceResponse`/`ServerSentEvent`, which could take
over this encoding -- kept hand-rolled instead so it's testable without a
framework. See PHASES.md.

Must not: know about `StreamSession`, HTTP, or any provider -- pure
byte-formatting of an already-built `Event`. Next: `stream.api`, which is
the only caller.
"""

import asyncio
from collections.abc import AsyncIterator

from stream.session import Event

_DEFAULT_HEARTBEAT_COMMENT = "ping"


def sse_format(event: Event) -> bytes:
    """One complete SSE event: `event:`, `id:`, one or more `data:` lines, blank line.

    Always emits at least one `data:` line, even for empty `event.data` --
    per spec, an event with *no* `data:` field at all has an empty data
    buffer and is never dispatched to the client.
    """
    lines = [f"event: {event.type}", f"id: {event.id}"]
    lines.extend(f"data: {line}" for line in event.data.split("\n"))
    lines.append("")  # blank line: terminates and dispatches the event
    return ("\n".join(lines) + "\n").encode("utf-8")


def heartbeat(comment: str = _DEFAULT_HEARTBEAT_COMMENT) -> bytes:
    """SSE comment line -- invisible to the client's event handlers.

    Sent periodically so proxies don't kill an idle-looking connection (the
    spec's own authoring note suggests ~every 15s); also lets our client
    tell "stalled generation, connection alive" apart from a dead one.
    """
    return f": {comment}\n\n".encode("utf-8")


async def heartbeat_ticker(interval_ms: int) -> AsyncIterator[bytes]:
    """Yields a heartbeat every `interval_ms`, forever, until the caller stops iterating."""
    interval_s = interval_ms / 1000
    while True:
        await asyncio.sleep(interval_s)
        yield heartbeat()


def retry_directive(ms: int) -> bytes:
    """SSE `retry:` field alone -- advises the client's reconnect delay.

    Valid standalone (no `data:`), per spec: a `retry:` field updates the
    reconnection time whether or not the block it's in ever dispatches.
    """
    return f"retry: {ms}\n\n".encode("utf-8")
