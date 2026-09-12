# Runbook

## Start

```
run.cmd
```

From the repo root. Sets up `.venv` and installs `requirements.txt` if
needed, then opens two console windows: the API on
`http://127.0.0.1:8765` and the Streamlit UI on `http://127.0.0.1:7018`
(port from `.streamlit/config.toml`).

To start only one piece (both from the repo root):

```
uv run --python .venv python -m uvicorn src.tools.api:app --host 127.0.0.1 --port 8765
uv run --python .venv streamlit run src/tools/ui.py
```

The UI calls the API at a hardcoded `http://127.0.0.1:8765`
(`src/tools/ui.py`, `API_BASE_URL`) — start the API first, or the UI shows
`Can't reach the API at http://127.0.0.1:8765: ...` and stops
(`st.stop()` in `ui.py`).

## Stop

Close the two console windows `run.cmd` opened. There is no separate stop
script or command; `run.cmd`'s own final message says exactly this
("close those windows to stop them").

## Logs

`data/logs/runs.jsonl` — one JSON object per loop iteration, appended by
every call to `loop.run()` (via the CLI or `POST /v1/loop`). Not written
to by `POST /v1/call` or manual calls from the UI's "Manual call" tab,
which go straight to `sandbox.execute_with_retry()` without going through
`loop.run()`. The file is not rotated; it grows for as long as the loop is
used.

Console output: whichever window is running the API or UI shows uvicorn's
/ Streamlit's own request logs. There is no separate application log file
beyond `runs.jsonl`.

## Common failures

These are inferred from the actual error strings and code paths in the
repo, not a general troubleshooting guide.

**"Can't reach the API at http://127.0.0.1:8765: ..." (in the Streamlit
UI)** — the API isn't running, or is running on a different port. Start
it (see Start above); the port is not currently configurable without
editing `src/tools/ui.py`'s `API_BASE_URL` constant.

**A port is already in use.** Neither `run.cmd` nor `uvicorn`/`streamlit`
retries on a different port; the process that tried to bind will error
and exit (or, for `uvicorn`, print a bind error and shut down). Find what
already holds the port:

```
netstat -ano | findstr :8765
netstat -ano | findstr :7018
```

The last column is a PID; `tasklist /FI "PID eq <pid>"` names the process.
Either stop that process or change the port (`--port` for uvicorn in
`run.cmd`; `[server] port` in `.streamlit/config.toml` for Streamlit).

**`RuntimeError: missing environment variable: <NAME>`** — raised by
`providers._require_env` when constructing `OpenAICompatibleProvider`
(`OPENAI_BASE_URL`, `OPENAI_API_KEY`), `AgnesProvider` (`AGNESAI_API_KEY`),
or `GeminiProvider` (`GOOGLE_API_KEY`) without that variable set in the
environment the process was started in. Not caught anywhere — via the CLI
this is a Python traceback; via `POST /v1/loop` this is an HTTP 500 with
no special-cased error body (see `docs/TECHNICAL.md`, Error handling).
`ollama` (the default provider) does not require any variable —
`OLLAMA_HOST` falls back to `http://localhost:11434` if unset.

**Ollama connection failures** (e.g. Ollama not running, or `OLLAMA_HOST`
pointing at nothing) surface as a `requests.exceptions.RequestException`
raised out of `OllamaProvider.chat()`, uncaught the same way as the
missing-env-var case above — a traceback from the CLI, an HTTP 500 from
`POST /v1/loop`.

**`{"ok": false, "error": {"code": "NOT_FOUND", ...}}` from `POST
/v1/call`** — the `name` in the request body doesn't match a registered
tool. `GET /v1/tools` lists the five that are registered
(`calc`, `now`, `json_query`, `write_note`, `read_note`).

**`{"ok": false, "error": {"code": "PERMISSION_DENIED", ...}}`** —
only reachable by a caller that explicitly passes a `requested`
permission set exceeding what the tool declared; none of the built-in
call paths (CLI, API, UI) do this today, so this would only show up from
code calling `sandbox.execute`/`execute_with_retry` directly with a custom
`requested` argument.

**`{"ok": false, "error": {"code": "TIMEOUT", ...}}`** — the tool's `fn`
ran longer than its `timeout_s`. Per `docs/TECHNICAL.md`, the underlying
thread is not killed and keeps running in the background.

**A traceback mentioning `path traversal rejected`** — `write_note`/
`read_note` called with a `name` argument that's absolute or escapes
`data/sandbox/<run_id>/` via `..`; raised by `sandbox.sandbox_path()` and
turned into an `EXEC_ERROR` `ToolResult` by `sandbox.execute()` (not a
raw crash, if reached through `execute`/`execute_with_retry`).
