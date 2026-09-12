# Schema

Implemented in `src/obs/trace/models.py` (Pydantic). Matches this doc.

## SpanContext

| Field | Type | Notes |
|---|---|---|
| `trace_id` | str | shared by every span in a trace |
| `span_id` | str | unique per span |
| `parent_id` | str \| None | `None` on the root span |

## Span

| Field | Type | Notes |
|---|---|---|
| `ctx` | SpanContext | identity |
| `name` | str | e.g. `"retrieve"`, `"generate"`, `"judge"` |
| `kind` | `"client"` \| `"internal"` | default `"internal"` |
| `provider` | str \| None | set via `span.set(provider=...)` |
| `model` | str \| None | set via `span.set(model=...)` |
| `ts` | str | wall-clock ISO 8601 UTC, captured at span start (added Phase 3 — `start_ns`/`end_ns` are monotonic, not calendar time, and can't drive daily file rotation or `since` queries) |
| `start_ns` / `end_ns` | int | `time.monotonic_ns()` |
| `latency_ms` | float \| None | computed on span exit |
| `status` | `"ok"` \| `"error"` | `"error"` set automatically if the `with` block raises |
| `error` | str \| None | `str(exception)` when status is `"error"` |
| `usage` | Usage \| None | set via `span.set_usage(...)` |
| `attrs` | dict[str, Any] | free-form; also holds `prompt_hash`/`prompt_preview`/`full_prompt` (see `docs/PRIVACY.md`) |

## Usage

| Field | Type |
|---|---|
| `in_tokens` | int \| None |
| `out_tokens` | int \| None |
| `cost_est` | float \| None — filled in at export time from `config/prices.yaml` if not already set (see below) |
| `ttft_ms` | float \| None |

Pricing (`obs.metrics.estimate_cost`): looks up `Span.model` in
`config/prices.yaml` (USD per 1000 tokens, in/out separately). Unknown model
-> `cost_est=None`, pricing flag `"UNPRICED"`. Ollama models in the config
default to 0 (local compute), so they're `"PRICED"` at zero, not unpriced.
An already-set `cost_est` is trusted as-is and reported `"PRICED"`. The
`"PRICED"`/`"UNPRICED"` flag itself is a storage-layer/export concept (an
extra column in `usage`, an extra key in the JSONL `usage` object) — it is
not a field on the in-memory `Usage` model.

## Trace

| Field | Type | Notes |
|---|---|---|
| `trace_id` | str | |
| `spans` | list[Span] | appended as each span exits |
| `attrs` | dict[str, Any] | free-form; recognized keys: `tenant`, `route`, `prompt_name`, `prompt_version`; set via `span.set_trace(...)` (any span handle in the trace, added Phase 3) |

## Alert

Implemented in `src/obs/alerts/models.py` (Pydantic). Persisted in
`data/obs.db`'s `alerts` table (`src/obs/alerts/store.py`). See
`docs/ALERTS.md` for the rules that produce these.

| Field | Type | Notes |
|---|---|---|
| `id` | str | uuid4 hex |
| `rule` | str | e.g. `"error_rate"` |
| `severity` | `"critical"` \| `"warning"` \| `"info"` | from the rule's config |
| `route` | str \| None | |
| `model` | str \| None | |
| `window` | str | human-readable, e.g. `"last_50"`, `"current_hour"` |
| `value` | float | the computed value that tripped the rule |
| `threshold` | float | the threshold it was compared against |
| `trace_ids` | list[str] | sample, up to 5 |
| `ts` | str | wall-clock ISO 8601 UTC, when the alert fired |
| `acked` | bool | default `false`; set via `obs.alerts.ack_alert(id)` |

## Storage (Phase 3)

- SQLite `data/obs.db`: tables `traces` (trace_id, ts, route, attrs JSON),
  `spans` (one row per span, FK to traces), `usage` (one row per span that
  has usage, FK to spans, includes `cost_est`/`pricing`). See
  `src/obs/export/sqlite.py` for exact columns.
- JSONL `data/traces/YYYYMMDD.jsonl`: one line per span (flattened, same
  fields as above), rotated by the UTC date in the span's `ts`.
- Both are registered exporters (`obs.export.register_default_exporters()`)
  — not automatic on import. Each exporter failure is logged and does not
  stop the other (`obs.trace.tracer`'s per-exporter try/except).
- Reads: `obs.export.get_trace(trace_id)` reconstructs a full `Trace`
  (spans + usage) from SQLite. `obs.export.query(route=, model=, since=,
  status=)` returns matching span rows as dicts, left-joined with their
  trace's `route` and their `usage` row (`in_tokens`/`out_tokens`/
  `cost_est`/`pricing`/`ttft_ms`, null if the span has no usage).
