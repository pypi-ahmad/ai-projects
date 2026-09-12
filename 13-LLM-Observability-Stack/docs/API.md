# API

FastAPI app at `src/obs/api/app.py`. Binds `127.0.0.1` only.

```
uv run python -m obs.api [--host 127.0.0.1] [--port 8000]
```

## Auth

GET endpoints are always open. POST endpoints require the `X-Admin-Token`
header only if `OBS_ADMIN_TOKEN` is set in the environment; otherwise they're
open too (`src/obs/api/auth.py`). The token is defense in depth, not the
primary boundary — that's the `127.0.0.1` bind.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/demo/complete` | body: `{messages, provider, model}`. Calls `TracedClient.complete` (only `provider: "ollama"` is wired up). Returns `{text, trace_id, in_tokens, out_tokens, ttft_ms}`. Adapter failure -> 502 (trace still recorded). |
| GET | `/v1/traces/{id}` | full `Trace` (spans + usage). 404 if unknown. |
| GET | `/v1/traces?route=&model=&since=&status=` | matching span rows, from `obs.export.query`. |
| GET | `/v1/alerts` | all alerts, `obs.alerts.list_alerts`. |
| POST | `/v1/alerts/{id}/ack` | marks acked, returns the updated alert. 404 if unknown. |
| POST | `/v1/ingest` | body: a full `Trace` JSON (matching `docs/SCHEMA.md`). Exports it through the same registered exporters as a locally-created trace, without creating new spans. 409 if `trace_id` already exists. |

## Exporters

Registered on startup (FastAPI `lifespan`), not at import time — importing
`obs.api.app` has no filesystem side effects. Uses
`obs.export.register_default_exporters()` (JSONL + SQLite), same as any
other entry point.
