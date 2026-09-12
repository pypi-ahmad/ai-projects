# SSE wire format

Source: [WHATWG HTML §9.2, "Server-sent events"](https://html.spec.whatwg.org/multipage/server-sent-events.html)
(fields verified against spec, not assumed).

## Transport facts

- MIME type: `text/event-stream`, UTF-8 only.
- An event is built from lines, terminated by a **blank line** (that's what
  dispatches it). Recognized field names, compared literally: `event`,
  `data`, `id`, `retry`. Anything else is ignored.
- `data:`; payload. Multiple `data:` lines in one event are joined with
  `\n`. A leading space after the colon is stripped.
- `event:`; event type/name. If omitted, the type defaults to `message`.
  We always set it explicitly (see below).
- `id:`; sets the client's last-event-id. On reconnect, the client (or our
  `stream.ui` consumer) sends it back as the **`Last-Event-ID`** request
  header. Must not contain NUL/CR/LF or the field is ignored. This is how
  `stream.session`'s replay buffer knows where to resume.
- `retry:`; ASCII-digits-only integer milliseconds; sets the client's
  reconnect delay.
- A line starting with `:` is a **comment**, ignored by the parser but still
  resets any transport idle-timeout. The spec's own authoring note: send one
  every ~15s to stop proxies from killing an idle-looking connection. We use
  this for heartbeats between tokens.
- The client (`EventSource`) auto-reconnects on a dropped connection unless
  the server responds `204 No Content`, which tells it to stop for good.

## Our event names

The three event types `stream.api` actually emits; verified against
`stream.session._append_event`'s three call sites, not just this table:

| `event:` | When | `data:` payload |
|---|---|---|
| `token` | Per chunk of generated text | the provider's raw text chunk; `id:` is a monotonically increasing per-stream sequence number |
| `error` | The provider pump raised (`session.fail("provider_error")`) | a short machine-readable code, currently always `provider_error`; terminal here (the pump has already stopped), though the wire format doesn't require that in general |
| `done` | Once, terminal, normal completion (`session.complete()`) | empty `data:` (see [METRICS.md](METRICS.md) for the actual per-session numbers, reported separately, not inside this event) |

An earlier draft of this doc also listed a `meta` event (provider/model/id
sent before the first token, as a fixed origin for the client's TTFT clock).
It was never implemented; no route sends it; and isn't planned; removed
here rather than left as a stale promise. `docs/API.md`'s 410 response body
also uses the `error` event shape, outside the normal `done`-flow above.

Heartbeat comments (`: ping`) are not one of these four; they carry no
`event:`/`data:` and are never surfaced to the client's message handler,
only used to tell "stalled generation, connection alive" apart from a dead
connection.

`stream.sse.sse_format(event)` implements this encoding (phase 3), wired to
the real `GET /v1/stream/{id}` route in `stream.api` (phase 4, see
[API.md](API.md)). `heartbeat()`/`retry_directive()` are there too, both
used by that route; `heartbeat_ticker()` (phase 3) is unused by it; the
route reimplements the same idle-timeout idea via `asyncio.wait_for` so it
can interleave heartbeats with live events from one loop, instead of merging
two independent generators. Per FastAPI's own docs (checked via context7), a
native `fastapi.sse.EventSourceResponse` + `ServerSentEvent(data=...,
event=..., id=..., retry=..., comment=...)` exists and does this same
encoding; kept hand-rolled instead so `sse_format` stays unit-testable
without a framework; revisit if maintaining both starts to hurt.
