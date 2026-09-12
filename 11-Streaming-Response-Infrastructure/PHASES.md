# Phases

Product: SSE streaming infrastructure. Backpressure, reconnect (Last-Event-ID),
TTFT and inter-token timing. Not a chatbot, not RAG, no Docker/nginx.

Native Windows 11, no WSL2, no Docker. Windows paths. `run.cmd` runs the
server.

Each phase touches only its own files, updates this doc, and stops. Phase
numbers track actual build order, decided live each phase, not a fixed plan
drafted up front; they get renumbered whenever the next ask isn't what an
earlier draft guessed. That's happened four times so far (session buffer
pulled into phase 2, SSE format/backpressure into phase 3, the FastAPI
routes into phase 4, all three provider adapters collapsed into one phase 5
instead of three). Check this file's phase count before trusting a stale
number from earlier in the conversation.

## Environment (checked, not assumed)

- Ollama running at `http://127.0.0.1:11434`, RTX 4060 8 GB (Ollama's own
  process does the GPU inference; the API process is CPU-only). Allowed
  models (exact strings, verified present via `/api/tags`):
  `granite4.1:3b`, `qwen3.5:2b`, `qwen3.5:0.8b`, `qwen3-vl:2b`,
  `qwen3-embedding:0.6b`, `qwen3-embedding:4b`, `translategemma:4b`,
  `AuditAid/PaddleOCR-VL-1.6-0.9B`. Smoke model: `qwen3.5:0.8b`.
- Env keys present in this process (checked via the user-env-variable skill
  checker, presence only, values never read): `AGNESAI_API_KEY`,
  `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `GOOGLE_API_KEY`.
  - The catalogued Agnes variable is **`AGNESAI_API_KEY`**, not
    `AGNES_API_KEY`. Gemini uses `GOOGLE_API_KEY` (no `GEMINI_API_KEY` here).
  - A present key means "can attempt a smoke test", not "verified". See
    `stream.config.PROVIDERS`.
- No `.env.example`; this machine's global Claude Code settings deny
  reading/writing `.env*` files. Env docs live in `docs/RUNBOOK.md` instead.

## Providers (phase 5 verification results)

| Provider | Models | Key | Status |
|---|---|---|---|
| Ollama | `qwen3.5:0.8b` (smoke), `qwen3.5:2b`, `granite4.1:3b` for longer streams | none (local) | **Verified**; live streamed reply + usage |
| OpenAI-compatible | `gpt-5.6-luna`, `gpt-5.6-terra`, medium effort | `OPENAI_API_KEY` + `OPENAI_BASE_URL` | **Verified**; live streamed reply + usage |
| Agnes AI | `agnes-2.5-flash` | `AGNESAI_API_KEY`, base `https://apihub.agnes-ai.com/v1` | **Verified**; live streamed reply + usage, reuses the OpenAI-compatible adapter (confirmed compatible via its own docs) |
| Gemini | `gemini-3.5-flash-lite`, `gemini-3.7-flash` | `GOOGLE_API_KEY` | **Built, not verified**; request reaches the API correctly, but this environment's `GOOGLE_API_KEY` is rejected (`400 API_KEY_INVALID`). Needs a valid key to actually confirm streaming end-to-end. |

## Phase 1; Scaffold, contracts, docs (done)

`src/stream/providers/base.py` (`TokenChunk`, `StreamAdapter`),
`providers/fake.py` (`FakeAdapter`), `metrics.py` (`time_stream`/`ttft_s`),
`config.py` (model allowlist, `PROVIDERS` status table). Docs: `README.md`,
`docs/{ARCHITECTURE,SSE,METRICS,RUNBOOK}.md`. `requirements.txt` stub.
`tests/test_fake_adapter.py`.

## Phase 2; Session buffer: events, replay, eviction (done)

No HTTP. `src/stream/session.py`: `Event`, `StreamSession` (`append`,
`replay(after_id)`, `complete()`/`fail(code)`, `metrics()`), bounded by
`max_events`/`ttl_s`, both counting into `dropped_count`. `providers/fake.py`:
added `FakeProvider` (raw string tokens). `tests/test_session.py`.

## Phase 3; SSE format + backpressure pump (done)

Still no HTTP. `src/stream/sse.py`: `sse_format(event)` (WHATWG-verified),
`heartbeat()`, `heartbeat_ticker()`. `src/stream/session.py`, added:
`buffer_len`/`ack(event_id)` (separate concept from the replay ring ;
acking never touches `dropped_count` or the deque), free function
`pump(provider, session, config, *, can_pause)` honoring
`stream.config.BackpressureConfig`'s `high_watermark`/`low_watermark`
hysteresis, with a drop-policy fallback (`drop_oldest_replayable`, default
`False`) for a provider that can't be paused. `tests/test_sse.py`,
`tests/test_backpressure.py`.

## Phase 4; FastAPI routes: start, resume, reconnect, 410 (done)

Added `fastapi`, `uvicorn` (main deps), `httpx2` (dev dep; Starlette's
`TestClient` deprecated plain `httpx`; confirmed by actually hitting that
warning and fixing it, not guessed).

- `src/stream/session.py`, added: `tail(after_id)`; an async generator a
  route iterates for *both* a fresh read and a reconnect; replays the
  buffer then yields new events live via an internal `asyncio.Event` set on
  every append (no polling here, unlike `wait_until_drained`).
- `src/stream/sse.py`, added: `retry_directive(ms)` (standalone `retry:`
  field).
- `src/stream/api.py`:
  - `POST /v1/stream/start` → `{session_id, sse_url}` JSON (not SSE).
    Starts a background task pumping `FakeProvider` into a new
    `StreamSession`, independent of any GET connection; see
    [docs/API.md](docs/API.md) for why this shape won over returning SSE
    directly from the POST, or a 303 redirect.
  - `GET /v1/stream/{session_id}`; the only place SSE bytes go out, reads
    the resume point from `Last-Event-ID` (header, preferred) or
    `?last_event_id=` (query fallback, for a client that can't set custom
    headers), streams `retry:` then `session.tail(after_id)`, `ack()`-ing
    right after each chunk so backpressure actually reaches the pump.
    Heartbeats via `asyncio.wait_for(..., timeout=15s)` around the tail
    iterator rather than merging `heartbeat_ticker` in; simpler than
    multiplexing two generators.
  - Unknown `session_id` → `410 Gone`, body is one `error` SSE event
    (`data: session_expired`), no `retry:` (don't reconnect to a gone id).
- `tests/test_api.py` (3): reconnect after a simulated mid-stream drop has
  no duplicate or missing event ids across both connections and ends in
  `done`; the `?last_event_id=` query fallback resumes identically to the
  header; unknown session → 410 + the error event.
- `uv run pytest -q` → 22 passed.
- Docs: new `docs/API.md` (endpoint contract, the POST/GET decision, and an
  honest list of what this phase did *not* build; session-registry
  reaping, and reporting a genuine reconnect gap as an `error` event rather
  than silently replaying whatever's left). `run.cmd` is real now.
  `docs/ARCHITECTURE.md`/`SSE.md`/`METRICS.md`/`README.md` updated to match
  what's actually wired versus still open, and provider-adapter phase
  numbers bumped (5/6/7, see below).

## Phase 5; Real provider adapters, `/v1/stream/start` dispatch, metrics endpoint, bench CLI (done)

Added `httpx2` as a main dependency (adapters need a real HTTP client, not
just TestClient; same package, already pulled in as a dev dep in phase 4).

- **Adapters**, each normalizing its wire format to plain token strings
  (`AsyncIterator[str]`, matching `FakeProvider`'s shape so `pump()` doesn't
  care which one it's driving), and each capturing real provider-reported
  usage in `self.usage`; set once, from whichever chunk actually carries
  it, never fabricated before then:
  - `providers/ollama.py`; `/api/chat`, `application/x-ndjson`,
    `message.content` per line, usage (`prompt_eval_count`/`eval_count`) on
    the final `done: true` line. Verified via context7
    (docs.ollama.com/api/chat, /api/streaming).
  - `providers/openai_compat.py`; generic OpenAI-compatible SSE
    (`choices[0].delta.content`, `stream_options.include_usage` for a final
    usage-only chunk, terminated by `[DONE]` if sent). Verified via context7
    (OpenAI's own API reference). Reused as-is for **Agnes** (confirmed
    OpenAI-compatible and stream-capable via its own docs, context7); no
    Agnes-specific code needed.
  - `providers/gemini.py`; native REST, `POST .../{model}:streamGenerateContent
    ?alt=sse&key=...`, `candidates[].content.parts[].text`, usage at
    `usageMetadata`. Verified by fetching ai.google.dev's actual API
    reference page (context7 didn't have the REST wire shape, only the
    Python SDK); every example on that page authenticates via `?key=`, not
    a header, so that's what this uses. Internal `messages` get translated
    to `contents`/`system_instruction` (`assistant`→`model`, system messages
    pulled out into the separate `system_instruction` field).
  - All three take an optional `transport` param purely for testing
    (`httpx2.MockTransport`); no behavior change on the real path.
- **Live-verified**, not just built; see the provider table above. Ollama,
  OpenAI-compatible, and Agnes all streamed a real reply with real usage on
  the first try. Gemini's request reaches the API correctly but this
  environment's key is invalid.
- **Incident during verification, fixed in-session:** the first live-check
  script printed a caught exception's `str()` on the Gemini failure, which
 ; because httpx2's `HTTPStatusError` bakes the full request URL into its
  message, and Gemini's auth is a URL query param; put the real
  `GOOGLE_API_KEY` value in this session's tool output. Told the user
  immediately and recommended rotating that key. Root cause fixed two ways:
  the diagnostic script now only ever reads `status_code`/response body
  text, never `str(exc)`/a default traceback; separately, `stream.api
  ._produce()` already only did `session.fail("provider_error")` on any
  adapter exception (a fixed, safe code, never the exception itself); that
  path was never at risk, but it's the reason a similar leak can't happen
  through the running server.
- **Found while live-verifying Ollama, not before:** `qwen3.5:0.8b` is a
  reasoning model; it streams a chain-of-thought through a separate
  `message.thinking` field, `content` staying empty for the whole thinking
  phase. First bench run reported 14-43s TTFTs because of this (real
  numbers, misleading interpretation; thinking time, not "stalled").
  `OllamaAdapter` gained a `think: bool | str | None` param (verified via
  context7 that Ollama's `/api/chat` accepts it); `stream.bench` defaults
  Ollama runs to `think=False`. With it off: p50 ≈ 51ms, p95 ≈ 359ms over 5
  runs on this machine. Documented in `docs/METRICS.md` so "TTFT" isn't
  read as one universal number for a reasoning model.
- **`stream.api`:**
  - `POST /v1/stream/start` now takes `{provider, model, messages}` (all
    optional, defaults to a `fake` run; existing tests posting an empty
    body still pass unchanged). `503` before any session is created if the
    provider isn't verified (`PROVIDERS[...].enabled`), its key is missing
    from the process environment right now, or `model` isn't in
    `MODEL_ALLOWLIST` for that provider.
  - `GET /v1/metrics/{session_id}` → `{ttft_ms, tokens, done_reason}` from
    `StreamSession.metrics()`; `404` for an unknown id.
  - `_produce()` now wraps `pump()` in `try/except`: any adapter exception
    calls `session.fail("provider_error")` instead of dying silently as an
    orphaned task (which would leave `done_reason` unset forever, hanging
    `tail()` for anyone reading that session); a real necessity now that
    adapters make actual network calls, not a hypothetical.
- **`stream/bench.py`** (new): `uv run python -m stream.bench --provider
  {fake,ollama} [--model ...] [--n ...] [--think]` runs `--n` independent
  streams straight through `stream.session.pump`; no HTTP involved; and
  prints p50/p95 `ttft_ms` (linear-interpolation percentile, stdlib only).
  Works as both `python -m stream.bench` and the literal `python -m
  src.stream.bench` form; `src` resolves as an implicit namespace package
  from the project root, confirmed by actually running both, not assumed.
- `tests/test_provider_adapters.py` (4), `tests/test_start_and_metrics.py`
  (7); all offline via `httpx2.MockTransport`, no live services required
  in the regression suite. `uv run pytest -q` → 33 passed.
- Docs: `docs/API.md` (`start` request shape, 503 conditions),
  `docs/METRICS.md` (verification status per field, the reasoning-model
  TTFT caveat), `README.md`.

## Phase 6; Streamlit consumer, client.html, session log, bench CI fixture (done)

`stream.ui` (Streamlit) doesn't drive a browser `EventSource` from Python
well, so per the brief: Streamlit is a synchronous httpx2-streaming
consumer (`st.write_stream`, Streamlit's own recommended shape for any
token stream), and the actual reconnect demo lives in `client.html` instead,
where a real `EventSource` makes it trivial.

- `src/stream/ui.py`: provider/model/prompt inputs → `POST /v1/stream/start`
  → a generator parsing `GET {sse_url}`'s raw SSE lines (via `httpx2
  .Client.stream`) → `st.write_stream`. Shows client-side TTFT (first
  `token` event) and, once done, the server's own `GET /v1/metrics` numbers
  side by side; never conflated, per docs/METRICS.md's reasoning-model
  caveat. Consumer only, no HTTP logic duplicated from `stream.api`.
- `src/ui/client.html`: plain browser `EventSource`, no build step. Start /
  Reconnect / Disconnect buttons. Reconnect uses `?last_event_id=`, not a
  `Last-Event-ID` header; confirmed while writing it that `EventSource`'s
  constructor has no way to set custom request headers at all, which is
  exactly why phase 4 built the query-param fallback in the first place, not
  a hypothetical. Shows client-side TTFT and, on `done`, fetches
  `/v1/metrics/{id}` for the server-side number too.
- **Found while building this, not before:** per the SSE spec, `EventSource`
  tries to reconnect even after a clean, successful end of the response body
  (not just on error); an `EventSource` left open after `done` would poll a
  finished session forever at the `retry:` interval. Fixed in
  `stream.api.get_stream`: a reconnect to an already-`done` session with
  nothing left to replay (`after_id >= session.last_id`) now returns `204
  No Content`, the one response the spec says stops further reconnects.
  Verified live (curl) that this actually returns 204, not assumed from the
  spec text alone.
- `stream.session.StreamSession` gained `connect_count` (incremented once
  per `GET /v1/stream/{id}`) and a `reconnects` property (`connect_count -
  1`, floored at 0); the metric neither `docs/METRICS.md` nor the session
  log had a real source for before this phase.
- `logs/streams.jsonl` (gitignored): one line per finished session ;
  `session_id`, `provider`, `model`, `ttft_ms`, `tokens`, `reconnects`,
  `dropped`, `ok`. Written once by `_produce()` when generation ends;
  anything that happens to the session afterward (a late reconnect) isn't
  reflected in that row; see docs/API.md.
- `run.cmd`: `uv sync --all-groups` (this project's equivalent of "make a
  venv, pip install"; it's uv-only, see docs/RUNBOOK.md), then starts
  uvicorn on `127.0.0.1:8000`, printing (not launching; a batch file
  orchestrating several long-running processes is more fragility than this
  needs) the `client.html` URL and the `streamlit run` command (port was
  8501 as of this phase; pinned to 7015 in phase 7).
- `tests/test_bench.py`: exercises `stream.bench` end to end with
  `--provider fake` only; no GPU, no Ollama, safe for CI. `uv run pytest
  -q` → 39 passed.
- Manually smoke-tested (not just unit-tested): a real server on a scratch
  port served `client.html`, a full start→stream→reconnect-after-done→204
  →metrics→log-row round trip via curl, and `streamlit run` started clean
  with no import errors; all stopped afterward.
- Docs: `docs/API.md` (204 semantics, session-log fields, `/client.html`),
  `docs/RUNBOOK.md` (how to actually reach Streamlit/client.html),
  `README.md`.

## Phase 7; Docs audit, requirements pin, Streamlit port/theme (done)

No new features unless a test failed; none did. Docs-and-config only.

- `docs/SSE.md`: the event-type table only ever listed 3 real event types
  to begin with in code (`token`/`error`/`done`; `session._append_event`'s
  three call sites), but still listed a 4th, `meta`, tagged "not emitted
  yet". Removed `meta` from the table entirely (it was never built and
  isn't planned) rather than leave a stale "yet". `docs/ARCHITECTURE.md`'s
  mermaid diagram and flow text had the same stale `meta` mention; fixed
  for consistency, nothing else in that file touched.
- `docs/METRICS.md`: rewritten around two *actually different* schemas that
  were previously blended into one table; `logs/streams.jsonl`'s real
  fields (`session_id`, `provider`, `model`, `ttft_ms`, `tokens`,
  `reconnects`, `dropped`, `ok`, read straight from `_log_session()`) versus
  `GET /v1/metrics/{id}`'s smaller live shape (`ttft_ms`, `tokens`,
  `done_reason`). Dropped `duration_ms`/`dropped_on_backpressure` as table
  fields; the first was never implemented by either shape, the second was
  just the jsonl row's `dropped` under an older name; both now called out
  explicitly under "not tracked" rather than presented as real fields.
- `README.md`: added a copy-pasteable `curl start → curl -N stream → curl
  -N reconnect with Last-Event-ID` walkthrough, and the JS shape for a
  browser reconnect (pointing at the full version in `client.html`). New
  "State" section (in-memory, one process, restart loses the replay
  buffer; see below). Stale `duration_ms`/`dropped_on_backpressure`/`meta`
  mentions fixed to match the docs above.
- `docs/RUNBOOK.md`: matching, more operational "State" section; why one
  process only (multiple uvicorn workers wouldn't share `_sessions`, so a
  session's `GET` would 410 against the wrong worker part of the time).
- `requirements.txt`: regenerated for real via `uv export --no-hashes
  --no-dev -o requirements.txt` (confirmed `--no-dev` is the right flag via
  `uv export --help`, not assumed from the phase-1 stub comment); pinned,
  main dependencies only, `-e .` for the project itself. No longer a stub.
- `.streamlit/config.toml` (new): `[server] port = 7015`, `[theme] base =
  "dark"`. Verified both keys against this project's own installed
  Streamlit (`streamlit config show`) rather than assumed; confirmed live
  that `streamlit run src/stream/ui.py` with no CLI flags actually serves
  on 7015. `run.cmd`/`README.md`/`docs/RUNBOOK.md` port mentions updated
  from 8501 to match.
- `uv run pytest -q` → still 39 passed, unchanged; nothing here touched
  code paths tests cover.

## Remaining known gaps

Not required by anything asked so far, kept honest rather than silently
closed or silently left undocumented:

- Session-registry reaping; a completed session lives in `_sessions`
  forever until the process restarts (bounded only by each session's own
  `max_events`/`ttl_s` event eviction, not by the registry itself).
- A real gap-detected `error` event on a reconnect whose `Last-Event-ID` is
  older than everything the buffer still has; today it just silently
  replays whatever's left. No gap is reachable in any tested path (nothing
  is evicted at the default `max_events=256`/`ttl_s=300`), but
  `docs/ARCHITECTURE.md` promises this and it isn't built.
- Gemini stays `enabled=False`; this environment's `GOOGLE_API_KEY` is
  rejected (`400 API_KEY_INVALID`); the adapter itself is built and its
  request format verified reachable. Needs a valid key to actually confirm
  streaming end-to-end.
- No standalone Python SSE client library with its own backoff/jitter and a
  stall watchdog distinguishing "heartbeat but no token" from "no bytes at
  all"; `client.html` (browser `EventSource`, automatic reconnect) and
  `stream.ui` (synchronous httpx2 read to completion) cover the reconnect
  and consumption demos that were asked for, but neither is that.
