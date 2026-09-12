# Technical notes

## Stack, and why (only where the code says so)

- **FastAPI + Starlette + uvicorn** — the whole HTTP surface
  (`src/stream/api.py`) is one `FastAPI()` app; `run.cmd` runs it via
  `uvicorn stream.api:app`. No reason for FastAPI specifically is stated in
  code; it's simply what `api.py` is built on.
- **`httpx2`**, not `httpx` — every provider adapter and both consumers
  (`stream/ui.py`, the bench tool indirectly via adapters) import
  `httpx2 as httpx`. `pyproject.toml` depends on `httpx2>=2.12.0` directly
  (main dependency, not a test-only one). No in-repo comment states why
  `httpx2` over `httpx`; `PHASES.md` records that Starlette's `TestClient`
  raised a deprecation warning pointing at `httpx2`, which is the traceable
  reason, but that reasoning lives in the project log, not the code itself.
- **`pydantic`** — only used for `stream.api`'s two request models
  (`Message`, `StartRequest`), i.e. FastAPI's own request-body validation;
  it is a transitive dependency of FastAPI, not separately declared in
  `pyproject.toml`.
- **Streamlit** — `src/stream/ui.py`'s own docstring states the reason
  directly: Streamlit's rerun model doesn't drive a browser `EventSource`
  well from Python, so it instead does a synchronous `httpx2` stream read
  inside a generator and renders it with `st.write_stream`.
- **No ORM, no database driver, no queue client** anywhere in
  `pyproject.toml` or `src/`.

## Invariants

- **One writer per `StreamSession`.** Tokens only ever reach a session
  through `StreamSession.append()`, called from `stream.session.pump()`,
  called from exactly one `_produce()` background task per session
  (`src/stream/api.py`). No code path calls `append()`/`complete()`/
  `fail()` concurrently for the same session.
- **`Event.id` is monotonically increasing per session, starting at 1**
  (`StreamSession._next_id`, incremented in `_append_event`). `replay()`
  and `tail()` rely on this ordering to detect "nothing new since
  `after_id`".
- **A session's terminal state is set exactly once.** `complete()` sets
  `done_reason = "complete"`; `fail(code)` sets `done_reason = code`.
  Nothing in `stream.api` calls both for the same session — `_produce()`'s
  `try/except` calls `fail()` on any exception and returns, or falls
  through to `complete()` on success, never both (`src/stream/api.py`,
  `_produce`).
- **`sse_format()` always emits at least one `data:` line**, even for an
  empty `Event.data` (`src/stream/sse.py`, function docstring) — per the
  SSE spec an event with no `data:` field at all never dispatches
  client-side, so `done`/`error` events (whose `data` can be empty) still
  need one.

## Error handling

- **`POST /v1/stream/start` validates before creating anything.**
  `_build_adapter()` raises `ProviderUnavailable` for an unknown provider,
  a provider whose `PROVIDERS[...].enabled` is `False`, a missing required
  env var, or a disallowed model; the route catches that and returns `503`
  with `{"error": "provider_unavailable", "detail": ...}` before a
  `StreamSession` or background task exists (`src/stream/api.py`,
  `start_stream`).
- **A provider failure after `start` never crashes silently.**
  `_produce()` wraps `pump()` in `try/except Exception`, calling
  `session.fail("provider_error")` on any error. The code comment there is
  explicit about why: an uncaught exception would leave `done_reason`
  unset forever, hanging `tail()`'s wait loop for any client reading that
  session, and the real exception text is never surfaced client-side
  because (for Gemini specifically) it can contain the request URL with
  the API key in it.
- **Malformed `Last-Event-ID`/`?last_event_id=` doesn't error.**
  `_parse_after_id()` catches `ValueError` from `int(...)` and returns `0`
  — treated the same as "no reconnect point given", not rejected
  (`src/stream/api.py`).
- **An unknown `session_id` on `GET /v1/stream/{id}`** returns `410` with
  one `error` SSE event (`data: session_expired`); on `GET
  /v1/metrics/{id}` it returns `404` with `{"error": "not_found"}` — two
  different status codes for the same "not found" condition, because one
  route is a `text/event-stream` response and the other a plain JSON one
  (verified: both branches are in `src/stream/api.py`, not inferred).
- **A finished session already caught up (`after_id >= session.last_id`)**
  returns `204 No Content` with no body, so a browser `EventSource` (which
  otherwise retries even after a clean end of stream, per the SSE spec)
  stops reconnecting.

## Persistence paths

- **None, for session state.** `StreamSession`s and the `_sessions`
  registry are plain in-process Python objects; nothing is written to disk
  or a database for them.
- **`logs/streams.jsonl`** (directory created on first write via
  `Path.mkdir(parents=True, exist_ok=True)`, `src/stream/api.py`,
  `_log_session`) is the one append-only, disk-persisted output: one JSON
  line per finished session, written once when `_produce()` returns
  (success or failure). Field list and meaning: `docs/METRICS.md`.
