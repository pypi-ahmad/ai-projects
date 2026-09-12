# Technical notes

## Stack

| Choice | Why (only stated where the code makes it obvious) |
|---|---|
| `uv` + `uv_build` | `pyproject.toml`'s `[build-system]` targets `uv_build`; `[tool.uv.build-backend] module-name = "obs"` exists because the package name (`obs`, under `src/`) differs from the project name (`llm-observability-stack`) — `uv_build`'s default module-name inference wouldn't find it otherwise. |
| `pydantic` | Every schema in the tree (`Span`, `Trace`, `Usage`, `SpanContext`, `Alert`, the `alerts.yaml`/API request/response models) is a pydantic `BaseModel` — used for both runtime validation and JSON (de)serialization at the API boundary and in SQLite/JSONL round-trips. |
| `sqlite3` (stdlib) | The only persistence engine; no ORM. Schema is raw SQL in `src/obs/export/sqlite.py` and `src/obs/alerts/store.py`. |
| `FastAPI` + `uvicorn` | `src/obs/api/app.py`; pydantic models double as request/response schemas here for free. |
| `Streamlit` + `altair` + `pandas` | `src/obs/ui/app.py`. `altair` specifically renders the trace waterfall as a `mark_bar()` chart with `x`/`x2` encoding (start/end times); `pandas` is the `DataFrame` these charts and `st.dataframe` calls consume. |
| `requests` | `src/obs/ui/api_client.py` only — the Streamlit process talks to the FastAPI process over real HTTP, not via a Python import, since `run.cmd` starts them as two separate processes. |
| `PyYAML` | `config/alerts.yaml` and `config/prices.yaml` loaders (`src/obs/alerts/config.py`, `src/obs/metrics/pricing.py`). |
| `urllib` (stdlib, not `requests`) | `src/obs/providers/ollama.py` makes its one HTTP call with stdlib `urllib.request` rather than `requests` — no comment in the code states why, so the reason is unclear from this file; it is the only place in `src/` that avoids `requests`. |

## Invariants and gotchas

- **`trace_id` uniqueness**: `traces.trace_id` is the SQLite primary key
  (`src/obs/export/sqlite.py`). `POST /v1/ingest` checks
  `get_trace(trace.trace_id)` first and returns `409` on a match
  (`src/obs/api/app.py`) rather than letting the insert raise.
- **Redaction is unconditional; full-text storage is opt-in**: every
  `span.set_prompt(text)` call computes a sha256 hash + 120-char preview
  regardless of configuration (`src/obs/trace/redact.py`); the raw text is
  additionally stored in `attrs["full_prompt"]` only if
  `OBS_STORE_PROMPTS` is `"true"` (case-insensitive) at the moment
  `set_prompt` runs (`src/obs/trace/tracer.py`). There is no per-span
  override — it's a single process-wide environment variable read.
- **`ts` vs. `start_ns`/`end_ns` are different clocks**: `Span.ts` is a
  wall-clock ISO-8601 UTC string (`datetime.now(UTC).isoformat()`),
  captured specifically so daily JSONL rotation and `since=` filtering have
  something comparable across process restarts. `start_ns`/`end_ns` come
  from `time.monotonic_ns()`, which has no fixed epoch — subtracting two
  monotonic timestamps is only meaningful within a span pair recorded by
  the same process's clock (this is what the trace waterfall in
  `src/obs/ui/app.py` does, relative to that trace's own earliest span).
- **Alert cooldown key is `(rule, route)`, not `(rule, route, model)`**:
  `src/obs/alerts/store.py`'s `in_cooldown` intentionally ignores `model`.
  A route served by two different models that both trip the same rule
  share one cooldown clock — documented in `docs/ALERTS.md`.
- **`(route, model=None)` pairs are excluded from evaluation**:
  `src/obs/alerts/stats.py`'s `distinct_route_models` filters out spans
  with no `model` set (e.g. a plain container/root span) — a "per
  route+model" rule isn't meaningful for a span that names no model. Not
  filtering this out previously caused one rule's own alert to
  cooldown-suppress another rule's alert on the same route within a single
  evaluation pass — the fix and its cause are recorded in
  `docs/ARCHITECTURE.md`'s phase history in earlier revisions of this repo.
- **Idempotent re-registration**: `obs.export.register_default_exporters()`
  and rule evaluation are safe to call more than once — they only append
  to or read from existing structures. Nothing de-duplicates repeated
  `register_exporter` calls, though: calling it twice with two
  `SqliteExporter` instances means every trace gets written to SQLite
  twice.

## Error handling

- **Exporters never raise to the caller.** `_run_exporters`
  (`src/obs/trace/tracer.py`) wraps each exporter call in `try/except
  Exception`, logging and continuing. A span's own status/error fields
  reflect whether the *traced code* raised, not whether export succeeded.
- **API error mapping** (`src/obs/api/app.py`): unknown `trace_id`/`alert_id`
  -> `404`; duplicate ingest `trace_id` -> `409`; missing/invalid
  `X-Admin-Token` when `OBS_ADMIN_TOKEN` is set -> `401`
  (`src/obs/api/auth.py`); an adapter exception during
  `POST /v1/demo/complete` is caught and re-raised as `HTTPException(502,
  ...)` — the underlying trace is still recorded and exported first, since
  the exception is caught only after the `with Tracer.start(...)` block
  exits.
- **Ollama connection failure**: `src/obs/providers/ollama.py` catches
  `urllib.error.URLError` and re-raises `RuntimeError(f"Ollama request to
  {base_url} failed: {exc}")` — this is what surfaces as the API's `502`
  body.
- **Missing config files degrade, not crash**: `load_alerts_config` and
  `load_prices` (`src/obs/alerts/config.py`, `src/obs/metrics/pricing.py`)
  both check `path.exists()` and return defaults/`{}` rather than raising
  if `config/alerts.yaml` or `config/prices.yaml` is absent.

## Persistence paths

- `data/obs.db` — SQLite, tables `traces`, `spans`, `usage`
  (`src/obs/export/sqlite.py`), `alerts` (`src/obs/alerts/store.py`).
- `data/traces/YYYYMMDD.jsonl` — one JSON object per line per span,
  rotated by the UTC date in that span's `ts` (`src/obs/export/jsonl.py`).
- Both are created on first write (`mkdir(parents=True, exist_ok=True)` +
  `CREATE TABLE IF NOT EXISTS`) — no separate migration step.
- No other persistence exists in this repo: no log files (see
  `docs/RUNBOOK.md`), no cache directory beyond `.ruff_cache`/`__pycache__`.
