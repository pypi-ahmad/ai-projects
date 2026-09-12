# Runbook

Native Windows 11 in practice; `run.cmd` is the only launcher and it's a
batch file; no WSL2/Docker step exists anywhere in the repo.

## Start

```
run.cmd
```

Runs `uv sync --all-groups`, then `uv run uvicorn stream.api:app --host
127.0.0.1 --port 8000` in the foreground. It prints, but does not start,
two more processes (run these in separate terminals if you want them):

```
uv run streamlit run src/stream/ui.py
```

serves the Streamlit consumer on `http://127.0.0.1:7015` (dark theme) ;
both values come from `.streamlit/config.toml`, not a flag. It expects the
API from `run.cmd` to already be reachable at `http://127.0.0.1:8000`
(hardcoded `API_BASE` in `src/stream/ui.py`).

`http://127.0.0.1:8000/client.html` is the static `EventSource` demo,
served by the FastAPI app itself (`GET /client.html` in `src/stream/api.py`)
; nothing separate to start for it.

## Stop

Ctrl-C the `run.cmd` window (and any Streamlit terminal). Nothing else is
running: no daemon, no separate worker process, no database to shut down
cleanly. State is in-memory only; see below.

## State

Everything about in-flight and finished-but-not-yet-restarted sessions
lives in one process's RAM: `stream.api._sessions` (the registry) and each
`StreamSession`'s own event buffer (`src/stream/session.py`). Consequences,
verified from the code, not assumed:

- Restarting the server loses every session. A client holding an old
  `session_id`/`sse_url` gets the normal "unknown session" response
  (`410` on the SSE route, `404` on `/v1/metrics`); there is nothing
  server-side distinguishing "never existed" from "existed before a
  restart."
- Running more than one `uvicorn` worker (e.g. `--workers 2`) is not
  supported by this design: a session created by one worker's `POST
  /v1/stream/start` isn't in another worker's memory, so a later `GET`
  routed to a different worker would 410 even though the session is
  technically still running elsewhere.
- The only thing that survives a restart is `logs/streams.jsonl`
  (append-only, on disk), and only for sessions that had already finished
  before the restart.

## Logs

`logs/streams.jsonl` (directory auto-created on first write; gitignored).
One JSON line per finished session, written once by
`stream.api._log_session()` when `_produce()` returns. Fields and meaning:
`docs/METRICS.md`. There is no other log file and no structured
server/access log configured anywhere in the repo; `uvicorn`'s own
default stdout logging is whatever `uvicorn` does by default; nothing in
this repo configures it further.

## Common failures, from the actual error strings in the code

| What you see | Where it comes from | What it means |
|---|---|---|
| `POST /v1/stream/start` → `503`, `{"error": "provider_unavailable", "detail": "<VAR> is not set"}` | `src/stream/config.py` `PROVIDER_KEY_VARS` checked live in `src/stream/api.py` `_build_adapter` | The named env var isn't set in the server process's environment. It's read once per request via `os.environ`; setting it in your shell after the server process already started won't be seen until the process is restarted. |
| `503`, `detail` matching a `PROVIDERS[...].reason` string (e.g. mentioning `GOOGLE_API_KEY was rejected`) | `src/stream/config.py` `PROVIDERS` | That provider's `enabled` is `False` in code. As of this tree, `gemini` is the only one; its own recorded reason is an invalid `GOOGLE_API_KEY` (`400 API_KEY_INVALID` from Google), not a code bug. |
| `503`, `detail` = `"model '...' is not allowed for provider '...'"` | `src/stream/api.py` `_build_adapter` vs. `MODEL_ALLOWLIST` in `config.py` | The requested `model` string isn't in that provider's fixed allowlist. |
| SSE stream ends with `event: error` / `data: provider_error`, and/or `logs/streams.jsonl` shows `"ok": false` | `src/stream/api.py` `_produce()`, catches any exception from `pump()` | The provider adapter raised mid-stream (e.g. Ollama not running, a network error, an unexpected non-2xx from the provider). The real exception is deliberately not logged or surfaced anywhere; the code comment in `_produce()` notes it can contain request URLs with API keys in them (Gemini authenticates via a `?key=` query parameter); so `provider_error` is all that's visible from outside the process. |
| `GET /v1/stream/{id}` → `410`, one `error` SSE event, `data: session_expired` | `src/stream/api.py` `get_stream` | `session_id` isn't in `_sessions`; never existed, or the process restarted since it did. |
| `GET /v1/metrics/{id}` → `404`, `{"error": "not_found"}` | `src/stream/api.py` `get_metrics` | Same underlying condition as above, different status code because this route isn't an SSE stream. |
| `GET /v1/stream/{id}` → `204`, empty body | `src/stream/api.py` `get_stream` | The session is already `done` and the given `Last-Event-ID`/`?last_event_id=` is already caught up; nothing left to replay. Intentional (see `docs/API.md`), not an error. |

## Dependencies at runtime

- Ollama, reachable at `http://127.0.0.1:11434` (`stream/providers/ollama.py`
  default), only if the `ollama` provider is used. Nothing in this repo
  starts or manages an Ollama process.
- Outbound HTTPS to whatever `OPENAI_BASE_URL` points at, to
  `https://apihub.agnes-ai.com` (hardcoded), and to
  `https://generativelanguage.googleapis.com` (hardcoded); only for
  requests that use those providers.
- No other runtime dependency (no database, no cache, no message broker)
  appears in `pyproject.toml` or `src/`.

## Firewall

Windows Defender Firewall does not filter loopback (`127.0.0.1`) traffic.
`run.cmd` binds `uvicorn` to `127.0.0.1` explicitly; changing that to
`0.0.0.0` or a LAN address (not done anywhere in this repo) would trigger a
Windows inbound-connection prompt the first time.

## Env vars this app reads

No `.env`/`.env.example` file exists in the repo. These names are read
directly from the process environment in `src/stream/config.py`/
`src/stream/api.py`:

```
OPENAI_API_KEY       # openai_compatible provider
OPENAI_BASE_URL      # openai_compatible provider
AGNESAI_API_KEY      # agnes provider (base URL is hardcoded, not an env var)
GOOGLE_API_KEY       # gemini provider
```

`ollama` needs none.
