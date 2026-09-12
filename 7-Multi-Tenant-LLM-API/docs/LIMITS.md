# Rate Limits & Token Budgets

Implemented in `src/quota/limiter.py::check_quota()`, called before an
upstream request would be made, in this order:

1. tenant active (else `TenantSuspendedError`, 403 — from `src/auth/errors.py`, reused as-is)
2. model allowed for tenant (else `MODEL_NOT_ALLOWED`, 403)
3. provider allowed for tenant (else `PROVIDER_NOT_ALLOWED`, 403)
4. rpm (else `RATE_RPM`, 429 + `Retry-After`)
5. rpd (else `RATE_RPD`, 429 + `Retry-After`)
6. `max_tokens_per_req`, only if the client sent a `max_tokens` (else `MAX_TOKENS_PER_REQUEST`, 400)
7. monthly token budget: `used_this_period + estimated_this_request <= token_budget_month` (else `BUDGET_MONTH`, 429 + `Retry-After`)

All limits live in `plan_limits` (one row per tenant, Phase 2 schema).

## Rate limit (rpm, rpd)

- **Unit:** requests per tenant, counted per `tenant_id` — shared across
  all of a tenant's keys, not one counter per key.
- **rpm:** sliding 60-second window. A request is counted once it
  completes and `record_usage()` writes its `usage_events` row (see
  "Accounting order" below) — a request that itself gets rejected by
  quota never reaches upstream, so it never adds to the count.
- **rpd:** fixed window, UTC calendar day (00:00:00 UTC to next
  00:00:00 UTC) — not a rolling 24h window.
- **On exceed:** `429`, no upstream call made, `Retry-After` in seconds:
  time until the oldest in-window request ages out (rpm) or time until
  next UTC midnight (rpd).

## Token budget (monthly)

- **Unit:** total tokens (`in_tokens + out_tokens`) per tenant, summed
  across all providers/models.
- **Reset period:** one calendar month, starting on `plan_limits.budget_reset_day`
  (day-of-month, clamped to the last valid day for short months — e.g.
  reset day 31 becomes Feb 28/29). Not a rolling 30 days.
- **On exceed:** `429` before the upstream call, `Retry-After` = seconds
  until the next period start. A request is never sent to a paid provider
  once the tenant is over budget for the current period.

## max_tokens_per_req

Only checked if the client's request includes a `max_tokens` value; not
enforced when absent (nothing to compare against). Rejects with
`MAX_TOKENS_PER_REQUEST` (400 — not a rate/budget issue, a request-shape
issue) if the client asked for more completion tokens than the tenant's
plan allows per request.

## Estimating "this request" for the budget check (Phase 5)

`POST /v1/chat` (`src/api/app.py::_estimate_tokens`) has no tokenizer:
prompt tokens are approximated as `len(content) // 4` summed across
messages. The completion side only adds the client's own `max_tokens` *if
they sent one* — an unspecified `max_tokens` adds 0, not the plan's
`max_tokens_per_req` ceiling. Assuming the worst case (the per-request cap)
for every uncapped request would falsely reject a tenant with a modest
budget who simply never bounds `max_tokens`; the "Accounting order" below
is what actually catches an unexpectedly large completion, not a
speculative estimate here.

## Accounting order

Quota is checked *before* the upstream call (`check_quota`); usage is
recorded *after* it completes (`src/usage/service.py::record_usage`,
always — success or failure). Two consequences:

- An over-budget tenant never reaches a paid provider (cost control).
- **If the actual token count from a completed call pushes the tenant over
  budget, that response is still returned in full — v1 does not truncate
  mid-response (there's no streaming in v1 to truncate mid-stream anyway).
  `record_usage` writes the real total regardless; the *next* call's
  `check_quota` reads that updated sum and is the one that gets rejected.**
  No separate "over budget" flag or cap exists — this falls out of the
  check-before / record-after order for free.

## Implementation note (why no in-memory counters)

rpm, rpd, and the monthly budget are all computed by querying
`usage_events` for the relevant time window, not a separate in-memory
bucket or persisted counter table. `usage_events` is already written after
every completed call and already persists to SQLite, so "a restart doesn't
reset the day/month budget" holds for all three limits with no extra state
to keep in sync or flush.

`# ponytail:` marks this in `src/quota/limiter.py`: one tenant's full
`usage_events` history gets scanned (via its indexed `tenant_id`) on every
check. Fine at this project's scale; add an index on `(tenant_id, ts)` or
switch rpm to an in-memory counter with periodic flush if profiling ever
says otherwise.

## Not safe for multiple processes

**This project assumes exactly one `uvicorn` process** (`run.cmd` starts a
single worker; no `--workers N`, no multiple replicas behind a load
balancer). `check_quota` (read) and `record_usage` (write) are two
separate SQLite statements with no cross-request lock between them — two
concurrent requests for the same tenant can both read "under the limit"
before either one's usage is recorded, letting the tenant briefly exceed
rpm/rpd/budget by a request or two. A single process's own thread pool
already has this same race in miniature; it's bounded by how many
concurrent requests one tenant can have in flight at once, which is small
enough here to accept. It gets meaningfully worse across *processes*
(each with independent Python-level state, or if this were ever pointed at
Postgres instead of file-based SQLite as a shared backend) and isn't
something this design defends against. A real fix (a DB-level
`SELECT ... FOR UPDATE`-equivalent, a single-writer queue, or moving
counters to something built for this like Redis) is out of scope unless
multi-process deployment is actually needed.

## Checking remaining quota

```
uv run python -m src.quota.cli <tenant_name>
```

Prints rpm/rpd/budget used vs. limit for that tenant, and the current
budget period's start/reset time.
