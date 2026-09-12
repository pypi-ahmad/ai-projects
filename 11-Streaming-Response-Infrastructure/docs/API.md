# API

## Endpoints

### `POST /v1/stream/start`

Body (all fields optional — an empty body runs a `fake` stream):

```json
{"provider": "ollama", "model": "qwen3.5:0.8b", "messages": [{"role": "user", "content": "hi"}]}
```

`provider` is one of `fake`, `ollama`, `openai_compatible`, `agnes`,
`gemini`. Creates a session, starts its background provider pump, and
returns JSON (not SSE):

```json
{"session_id": "…", "sse_url": "/v1/stream/…"}
```

**`503`, not a session, when the provider can't be attempted** — checked
*before* anything is created, so a bad request never produces a session that
opens an SSE connection just to hang or error mid-stream:

- provider unknown, or not yet verified (`stream.config.PROVIDERS[...]
  .enabled` is `False` — see PHASES.md for current status per provider)
- provider needs a key and it's missing from the process environment right
  now (checked live, not just trusted from `PROVIDERS`)
- `model` isn't in that provider's allowlist (`stream.config
  .MODEL_ALLOWLIST`)

Body on any of these: `{"error": "provider_unavailable", "detail": "..."}`.

If the provider *did* pass those checks but then fails mid-stream (network
error, upstream 5xx, etc.) — that can't be caught at `start` time, since the
first byte hasn't been requested yet. It surfaces as `session.fail
("provider_error")`, i.e. a normal terminal `error` SSE event, not a 503 and
not a hang; see `_produce()` in `stream.api`.

### `GET /v1/stream/{session_id}`

The one and only place SSE bytes come out, for both a fresh read and a
reconnect. Reads the resume point from, in order of preference:

1. `Last-Event-ID` request header (what a real browser `EventSource` sends
   automatically on reconnect).
2. `?last_event_id=` query parameter (fallback for a client that can't set
   custom headers on the request that opens an `EventSource` — there is no
   API to do that from a browser).

Response: `text/event-stream`, body = one `retry:` directive, then
`session.tail(after_id)` — whatever's still buffered after that id, then new
events live, with a heartbeat comment if nothing arrives for 15s.

If `session_id` isn't known (never existed, or already reaped): `410 Gone`,
body is one `error` SSE event (`data: session_expired`). No `retry:` on
this response — 410 means don't come back for this id.

If the session is known but already `done` and the given id is caught up
(`after_id >= session.last_id`): `204 No Content`, empty body. Per the SSE
spec, a browser `EventSource` tries to reconnect even after a clean,
successful end of body — 204 is the one response that tells it to stop for
good. Without this, `client.html`'s `EventSource` would poll a finished
stream forever at the `retry:` interval.

### `GET /v1/metrics/{session_id}`

`{ttft_ms, tokens, done_reason}` from `StreamSession.metrics()`. `404` if
unknown. Meaningful once `done_reason` is set; returns whatever's
accumulated so far either way.

### `GET /client.html`

Serves `src/ui/client.html` (same origin as the API, so no CORS setup is
needed) — a plain browser `EventSource` demo: Start / Reconnect-from-
last-event-id / Disconnect buttons, live token rendering, and both
client-side TTFT (`EventSource` construction → first `token` event) and the
server's own `GET /v1/metrics` numbers once done.

## Why POST-returns-JSON-then-GET, not the alternatives

Three shapes were on the table:

1. POST returns the SSE body directly on the same response.
2. POST returns `303 See Other` to a GET url.
3. **POST returns `{session_id, sse_url}` JSON; caller GETs it. (chosen)**

(3) means the *only* thing that ever opens an `EventSource`-shaped
connection is a GET, so a reconnect (browser or our own client, phase 6) is
just "GET the same url again, maybe with `Last-Event-ID`" — no special case
for "the first read happens to be riding on the POST response." (1) would
need a second, different code path for reconnects. (2) works but forces an
extra round trip through a redirect for no benefit over just handing back
the URL directly.

## Session lifecycle

The background pump (provider → session) starts at POST time and is
independent of any GET connection — dropping the connection doesn't stop
generation, and a reconnect just resumes reading the same `StreamSession`
from the in-memory `_sessions` registry. Every `GET /v1/stream/{id}`
increments `session.connect_count`; `session.reconnects` is that minus the
first read.

`logs/streams.jsonl` gets one line per session, written once `_produce()`
finishes (success or `provider_error`): `session_id`, `provider`, `model`,
`ttft_ms`, `tokens`, `reconnects`, `dropped` (`session.dropped_count`), `ok`
(`done_reason == "complete"`). Anything that happens to the session *after*
that — a client reconnecting post-`done` to re-read the tail — isn't
reflected in that row; it's a snapshot at generation-end, not a live tail
of the session's full lifetime.

Not built yet: removing a session from `_sessions` after it's done for some
grace period (right now completed sessions stay resumable/replayable in
memory until the process restarts, bounded only by `StreamSession`'s own
`max_events`/`ttl_s` event eviction — the *session* itself never expires on
its own yet, only its older events do). Also not built: a mid-stream `error`
event when a reconnect's `Last-Event-ID` is older than everything the buffer
still has (today it just silently replays whatever's left — no gap is
possible in the currently-tested paths, since nothing is evicted at the
default `max_events=256`/`ttl_s=300`, but this is the honest gap between
that promise in `docs/ARCHITECTURE.md` and what's implemented).
