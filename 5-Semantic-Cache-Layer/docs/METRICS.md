# Metrics

**Implemented (Phase 5).** Every `put()`/`get()` call appends one JSON
line to `data/cache/metrics.jsonl` via `MetricsLogger`
(`src/metrics/logger.py`); `src/metrics/aggregator.py` reads it back and
computes hit rate per namespace over a trailing window.

## Event log (`data/cache/metrics.jsonl`)

Append-only, one `MetricsEvent` per line:

| Field | Type | Notes |
|---|---|---|
| `ts` | datetime (UTC, ISO 8601) | When the event was logged |
| `namespace` | str | |
| `event` | `hit` \| `miss` \| `put` \| `evict` \| `reject` | |
| `score` | float \| null | Cosine similarity for `hit`/`miss` (the top candidate's score even on a miss; near-miss tracking); `1.0` for an exact hit; null for `put`/`evict`/`reject` |
| `latency_ms` | float \| null | Wall-clock time for the whole `put()`/`get()` call |
| `embed_ms` | float \| null | Time in the Ollama `/api/embed` call alone; null when no embedding happened (exact hit, reject before embedding, or nothing indexed yet) |
| `exact` | bool \| null | `true`/`false` on hit/miss (exact-match short-circuit vs. semantic search); null for `put`/`evict`/`reject` |

Only `MetricsLogger.log()` writes to this file, so there is no separate sink
or format to keep in sync.

## Aggregator (`src/metrics/aggregator.py`)

`read_events(since=...)` filters by `ts`; `aggregate(events)` groups by
`namespace` and returns, per namespace:

| Metric | Definition |
|---|---|
| `hit_rate` | `hits / (hits + misses)` in the window; `null` (not `0.0`) if there were no hits or misses at all, so "no traffic" isn't confused with "0% hit rate" |
| `entries` | *Not* part of this aggregation; it's a live count, not a windowed one; use `SemanticCache.stats().entries` directly |
| `evictions`, `rejects`, `puts` | Raw counts of those events in the window |

## CLI

```
python -m src.metrics --hours 24
```

Prints per-namespace stats as JSON for the trailing N hours (default 24).

## Not yet built

- `latency_p50`/`latency_p95`: the event log has raw `latency_ms`/`embed_ms`
  per call, but nothing computes percentiles from them yet; that's an
  aggregator addition, not a logging one.
- **Savings**: still not a fixed formula; depends on knowing the cost of
  the generation step the cache avoided, which is outside this repo's
  scope (the caller's problem, per `NOTES.md`).
