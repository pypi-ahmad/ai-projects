# Alerts

Implemented in `src/obs/alerts/`. Config in `config/alerts.yaml`.

Rolling window stats are computed on read (`src/obs/alerts/stats.py`) — no
materialized rollup table. Every evaluation pass re-queries
`spans`/`traces`/`usage` and aggregates in Python (`statistics.quantiles`
for p50/p95). Evaluated per `(route, model)` pair; spans with no `model` set
are excluded (a "per route+model" rule isn't meaningful for a span that
names no model).

## Rules

| Rule | Fires when | Default |
|---|---|---|
| `error_rate` | error rate over the last `window_n` requests for a route+model > `threshold` | on |
| `latency_regression` | current-window p95 latency > `k` × baseline p95 (baseline = previous UTC day's p95; falls back to the first hour of data ever recorded's p50 if no previous-day data exists) | on |
| `cost_sum_hour` | sum of `cost_est` for the current UTC hour > `budget_usd` | on |
| `ttft_p50` | p50 of `ttft_ms` over the last `window_n` requests > `threshold_ms` | on |
| `traffic_drop` | current request rate < `drop_ratio` × baseline rate (traffic "die-off") | **off** |
| `unpriced_burst` | fraction of usage rows with pricing `"UNPRICED"` over the last `window_n` > `threshold` | **off** |

Exact thresholds/windows: `config/alerts.yaml`.

## Cooldown (idempotency)

`cooldown_minutes` (config, default 30) — once a rule fires for a given
`(rule, route)`, no new alert for that same `(rule, route)` is created until
the cooldown elapses, even if the rule would still fire. Dedup key is
`(rule, route)` only, not `model` — a route with several models sharing the
same rule name shares one cooldown clock.

## Alert row

`id`, `rule`, `severity`, `route`, `model`, `window` (human-readable
description of what was evaluated, e.g. `"last_50"` or
`"last_50_vs_prev_day_p95"`), `value`, `threshold`, `trace_ids` (sample, up
to 5), `ts`, `acked`. Stored in `data/obs.db`'s `alerts` table
(`src/obs/alerts/store.py`).

## Evaluator

```
uv run python -m obs.alerts.eval --once
```

One pass over every `(route, model)` pair with activity in the last 24
hours, all enabled rules. Not a daemon/loop yet — run it on a schedule
externally (Task Scheduler, a cron-like wrapper) if continuous evaluation
is wanted.

## Ack

`obs.alerts.ack_alert(alert_id)` (library), `POST /v1/alerts/{id}/ack`
(API, `docs/API.md`), and the Streamlit alert inbox's "Ack" button
(`src/obs/ui/app.py`) all set `acked=true`. No unacking.

## Not implemented

- The Phase 1 idea of an optional local-LLM anomaly note. There is no
  `llm_note` field on `Alert` (`src/obs/alerts/models.py`) — an earlier
  version of this doc incorrectly claimed there was.
