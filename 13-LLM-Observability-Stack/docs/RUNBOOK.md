# Runbook

## Start

```
run.cmd
```

Opens two console windows (Windows `start "title" cmd /k ...`, per
`run.cmd`): one for `uv run python -m obs.api` (FastAPI on
`127.0.0.1:8000`), one for `uv run streamlit run src\obs\ui\app.py
--server.port 7017`. `run.cmd` runs `uv sync --all-groups` first.

Or start each directly (works on any OS `uv` supports):

```
uv run python -m obs.api --host 127.0.0.1 --port 8000
uv run streamlit run src/obs/ui/app.py --server.port 7017
```

## Stop

Close each console window `run.cmd` opened, or Ctrl+C in whichever
terminal is running the direct commands above. Neither process is a
background service or daemon; nothing restarts them automatically.

## Seed demo data

```
uv run python scripts/seed_demo_data.py
```

Writes 30 synthetic traces (some marked `status="error"`, some slower via
`time.sleep`) through the real `Tracer` + registered exporters, so
`data/obs.db` and `data/traces/` have something in them.

## Logs

Neither service configures a log file. `uv run python -m obs.api` (uvicorn)
and `uv run streamlit run ...` (Streamlit) both log to the console of
whichever window is running them. `src/obs/trace/tracer.py` uses Python's
`logging` module for exporter failures (`logger.warning("exporter failed",
exc_info=True)`) — this also goes to the console, not a file, since nothing
in the tree calls `logging.basicConfig` with a file handler.

## Failure modes visible in the code

- **`No data at <path>`** / **`No spans for <day>`** — printed by
  `uv run python -m obs.export --day <day> --summary`
  (`src/obs/export/__main__.py`) when `data/obs.db` doesn't exist yet or has
  no rows for that day. Not an error; means nothing has been traced yet
  (for that day).
- **`Ollama request to <base_url> failed: <exc>`** — raised as a
  `RuntimeError` by `src/obs/providers/ollama.py` when the local Ollama
  server can't be reached; surfaces through `POST /v1/demo/complete` as an
  HTTP `502` with that text in the response body.
- **`missing or invalid X-Admin-Token`** — HTTP `401` from any POST
  endpoint when `OBS_ADMIN_TOKEN` is set in the environment but the request
  either omits `X-Admin-Token` or sends the wrong value
  (`src/obs/api/auth.py`).
- **`trace not found` / `alert not found`** — HTTP `404` from the relevant
  GET/POST-by-id endpoints when the id doesn't exist.
- **`trace_id already exists`** — HTTP `409` from `POST /v1/ingest` if the
  submitted `trace_id` is already in `data/obs.db`.
- **Port already bound** — `uv run python -m obs.api` will fail to start if
  something else is already using the requested port (default `8000`), or
  if the OS itself blocks binding to it (observed once in this environment
  as a Windows `WinError 10013` on port `8000`, unrelated to this code —
  resolved by picking a different `--port`). Streamlit will similarly fail
  on a busy `--server.port`.
