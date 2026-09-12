"""FastAPI SSE endpoint -- source of truth for the stream.

`POST /v1/stream/start` `{provider, model, messages}` (all optional, default
to a `fake` run) creates a session and returns `{session_id, sse_url}` as
JSON, not SSE. Both the first read and every reconnect are then a plain
`GET` on `sse_url` -- see docs/API.md for why this shape won over returning
the SSE body directly from the POST, or a 303 redirect to GET.

A provider that isn't verified (`stream.config.PROVIDERS[...].enabled` is
False) or is missing its API key fails `start` with `503` immediately --
never a session that opens an SSE connection just to hang or error mid-
stream. See PHASES.md for which providers are verified as of this phase.

`GET /v1/stream/{session_id}` replays anything buffered after Last-Event-ID
(header, or `?last_event_id=` for a client that can't set custom headers),
then tails new events live, heartbeating when idle. The chosen provider is
pumped into the session by a background task started at POST time,
independent of any one GET connection -- a dropped connection doesn't stop
generation, and a reconnect just resumes reading the same session.

`GET /v1/metrics/{session_id}` returns `StreamSession.metrics()` as JSON --
meaningful once the stream is `done`, but returns whatever's accumulated so
far either way.

Security: `session_id` is the only access control on a stream -- an
unguessable `uuid4().hex`, not paired with any other auth. Anyone who has
it can read or reconnect to it. `provider`/`model`/`messages` are the only
client-controlled inputs; every base_url/api_key an adapter uses comes from
server-side env vars in `stream.config`, never from the request body.

Must not: talk to a provider directly (that's `stream.providers.*`, only
ever reached through `stream.session.pump`) or hold state beyond
`_sessions`/the log file below. Next: `stream.session` for `StreamSession`
itself.
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Header, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from stream.config import (
    AGNES_API_KEY_VAR,
    AGNES_BASE_URL,
    GEMINI_API_KEY_VAR,
    GEMINI_BASE_URL,
    MODEL_ALLOWLIST,
    OPENAI_API_KEY_VAR,
    OPENAI_BASE_URL_VAR,
    PROVIDER_KEY_VARS,
    PROVIDERS,
    BackpressureConfig,
)
from stream.providers.fake import FakeProvider
from stream.providers.gemini import GeminiAdapter
from stream.providers.ollama import OllamaAdapter
from stream.providers.openai_compat import OpenAICompatAdapter
from stream.session import Event, StreamSession, pump
from stream.sse import heartbeat, retry_directive, sse_format

app = FastAPI()

_RETRY_MS = 3000
_HEARTBEAT_INTERVAL_S = 15.0
_FAKE_TOKENS = ["alpha", "beta", "gamma", "delta", "epsilon"]
_FAKE_DELAY_S = 0.02

_sessions: dict[str, StreamSession] = {}

# Relative to the process's current working directory at request time, not
# to this file -- run from a different cwd and the log lands somewhere
# else. Deliberately anchored differently from the path below, which must
# resolve regardless of cwd since it's served as a file response.
_LOG_PATH = Path("logs/streams.jsonl")
_CLIENT_HTML_PATH = Path(__file__).resolve().parent.parent / "ui" / "client.html"


def _log_session(session: StreamSession, provider: str, model: str) -> None:
    """One line per finished session. Reconnects/dropped past this point (a
    client resuming after `done` to re-read the tail) aren't captured --
    this writes once, right when `_produce` finishes."""
    metrics = session.metrics()
    row = {
        "session_id": session.id,
        "provider": provider,
        "model": model,
        "ttft_ms": metrics.ttft_ms,
        "tokens": metrics.token_count,
        "reconnects": session.reconnects,
        "dropped": session.dropped_count,
        "ok": metrics.done_reason == "complete",
    }
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


class Message(BaseModel):
    role: str
    content: str


class StartRequest(BaseModel):
    provider: str = "fake"
    model: str = "fake"
    messages: list[Message] = []


class ProviderUnavailable(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


def _build_adapter(req: StartRequest) -> object:
    if req.provider == "fake":
        return FakeProvider(tokens=_FAKE_TOKENS, delay_s=_FAKE_DELAY_S)

    status = PROVIDERS.get(req.provider)
    if status is None:
        raise ProviderUnavailable(f"unknown provider {req.provider!r}")
    if not status.enabled:
        raise ProviderUnavailable(status.reason)

    key_var = PROVIDER_KEY_VARS.get(req.provider)
    if key_var is not None and key_var not in os.environ:
        raise ProviderUnavailable(f"{key_var} is not set")

    if req.model not in MODEL_ALLOWLIST[req.provider]:
        raise ProviderUnavailable(f"model {req.model!r} is not allowed for provider {req.provider!r}")

    messages = [m.model_dump() for m in req.messages]

    if req.provider == "ollama":
        return OllamaAdapter(req.model, messages)
    if req.provider == "openai_compatible":
        return OpenAICompatAdapter(
            base_url=os.environ[OPENAI_BASE_URL_VAR],
            api_key=os.environ[OPENAI_API_KEY_VAR],
            model=req.model,
            messages=messages,
        )
    if req.provider == "agnes":
        return OpenAICompatAdapter(
            base_url=AGNES_BASE_URL,
            api_key=os.environ[AGNES_API_KEY_VAR],
            model=req.model,
            messages=messages,
        )
    if req.provider == "gemini":
        return GeminiAdapter(
            req.model, messages, api_key=os.environ[GEMINI_API_KEY_VAR], base_url=GEMINI_BASE_URL
        )

    raise ProviderUnavailable(f"unknown provider {req.provider!r}")  # pragma: no cover -- unreachable


@app.post("/v1/stream/start")
async def start_stream(req: StartRequest = StartRequest()) -> JSONResponse:
    try:
        adapter = _build_adapter(req)
    except ProviderUnavailable as exc:
        return JSONResponse({"error": "provider_unavailable", "detail": exc.detail}, status_code=503)

    session_id = uuid.uuid4().hex
    session = StreamSession(id=session_id)
    _sessions[session_id] = session
    asyncio.create_task(  # noqa: RUF006 -- session outlives this request
        _produce(session, adapter, req.provider, req.model)
    )

    return JSONResponse({"session_id": session_id, "sse_url": f"/v1/stream/{session_id}"})


async def _produce(session: StreamSession, provider: object, provider_name: str, model: str) -> None:
    try:
        await pump(provider, session, BackpressureConfig(), can_pause=True)
    except Exception:
        # Never let a provider fault kill the task silently -- a session
        # with no `done_reason` set hangs `tail()` for any client reading
        # it. The real exception (which can embed request URLs / keys for
        # Gemini's query-param auth) never reaches the client-visible event.
        session.fail("provider_error")
        _log_session(session, provider_name, model)
        return
    session.complete()
    _log_session(session, provider_name, model)


@app.get("/v1/metrics/{session_id}")
async def get_metrics(session_id: str) -> JSONResponse:
    session = _sessions.get(session_id)
    if session is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    metrics = session.metrics()
    return JSONResponse(
        {
            "ttft_ms": metrics.ttft_ms,
            "tokens": metrics.token_count,
            "done_reason": metrics.done_reason,
        }
    )


@app.get("/client.html", include_in_schema=False)
async def get_client_html() -> FileResponse:
    return FileResponse(_CLIENT_HTML_PATH, media_type="text/html")


@app.get("/v1/stream/{session_id}")
async def get_stream(
    session_id: str,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    last_event_id_query: str | None = Query(default=None, alias="last_event_id"),
) -> Response:
    session = _sessions.get(session_id)
    if session is None:
        expired = Event(id=0, type="error", data="session_expired", ts_monotonic=0.0)
        return Response(
            content=sse_format(expired), status_code=410, media_type="text/event-stream"
        )

    session.connect_count += 1
    after_id = _parse_after_id(last_event_id if last_event_id is not None else last_event_id_query)

    if session.done_reason is not None and after_id >= session.last_id:
        # Nothing left to replay and nothing more is coming. Per the SSE
        # spec, a plain closed connection still makes EventSource try to
        # reconnect forever; 204 is the one response that tells it to stop.
        return Response(status_code=204)

    return StreamingResponse(_stream_body(session, after_id), media_type="text/event-stream")


def _parse_after_id(raw: str | None) -> int:
    # raw is client-controlled (Last-Event-ID header or ?last_event_id=);
    # never trust it beyond "an int, or treat as absent" -- any non-integer
    # value degrades to a fresh read rather than erroring.
    if raw is None:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0  # malformed Last-Event-ID: treat as "no reconnect point given"


async def _stream_body(session: StreamSession, after_id: int) -> AsyncIterator[bytes]:
    yield retry_directive(_RETRY_MS)
    events = session.tail(after_id)
    while True:
        try:
            event = await asyncio.wait_for(events.__anext__(), timeout=_HEARTBEAT_INTERVAL_S)
        except TimeoutError:
            yield heartbeat()
            continue
        except StopAsyncIteration:
            return
        yield sse_format(event)
        session.ack(event.id)
