# Data model

All implemented; Pydantic models + SQLite (same db file for
`Prompt`/`Version`/`Pointer`/`Experiment`/`Assignment`/`Outcome`; `Outcome`
additionally appends to a JSONL audit log).

## Prompt

A named slot. Owns a history of versions, nothing else.

| Field | Type | Notes |
|---|---|---|
| `name` | text, PK | slug, e.g. `summarize-ticket` |
| `description` | text, nullable | set on first `publish`, not updated after |
| `created_at` | text (ISO 8601 UTC) | |

## Version

Immutable; `publish` only ever inserts, never updates. Version number is a
monotonic int per prompt (1, 2, 3, ...), not content-addressed: publishing
identical content twice still creates a new row. Body lives on disk at
`data/prompts/<name>/<version>.md` and is never overwritten; SQLite holds
its sha256 and is re-verified against the file on every `get`
(`IntegrityError` on mismatch).

| Field | Type | Notes |
|---|---|---|
| `prompt_id` | text, PK part, FK -> Prompt.name | |
| `version` | int, PK part | monotonic per prompt, starts at 1 |
| `label` | text, nullable | optional nickname, e.g. `baseline` |
| `sha256` | text | of the body at publish time |
| `body_path` | text | `data/prompts/<name>/<version>.md` |
| `config_json` | text (JSON: `model`, `provider`, `temperature`, `max_tokens`) | |
| `created_at` | text (ISO 8601 UTC) | |
| `author` | text | required, caller-supplied |
| `changelog` | text | required, free text |
| `immutable` | int, `CHECK(immutable = 1)` | always true; documents the invariant |

## Pointer

Single version per (prompt, env); `prod` or `staging`. No weights, no
splitting yet.

| Field | Type | Notes |
|---|---|---|
| `prompt_id` | text, PK part, FK -> Prompt.name | |
| `env` | text, PK part, `CHECK(env IN ('prod','staging'))` | |
| `version` | int, FK -> Version.version | |
| `updated_at` | text (ISO 8601 UTC) | |

## pointer_history *(internal; audit log, not on the public API)*

Every `set_pointer`/`rollback` appends a row here; `rollback` reads it to
find what the pointer was before its current value, then reassigns it.
Not a public entity in its own right, but it's what makes rollback
possible; see [RUNBOOK.md](RUNBOOK.md).

| Field | Type | Notes |
|---|---|---|
| `id` | int, PK, autoincrement | |
| `prompt_id` | text | |
| `env` | text | |
| `version` | int | |
| `action` | text, `CHECK(action IN ('set','rollback'))` | |
| `created_at` | text (ISO 8601 UTC) | |

## Experiment

A named A/B(/n) test over a prompt. `arms` is stored as a JSON array
(`arms_json`), validated at write and read time to have >=1 arm, unique
arm names, and integer weights summing to exactly 100.

| Field | Type | Notes |
|---|---|---|
| `id` | int, PK, autoincrement | |
| `name` | text | human label, e.g. `tone-test` |
| `prompt_name` | text, FK -> Prompt.name | |
| `status` | text, `CHECK(status IN ('draft','running','paused','stopped'))` | |
| `arms` (`arms_json`) | JSON list of `{name, version, weight}` | `version` FK-checked against Version at creation |
| `sticky_salt` | text | auto-generated (`secrets.token_hex(8)`) if not given |
| `start_at`, `end_at` | text (ISO 8601 UTC), nullable | metadata only; not enforced by `resolve` |
| `created_at` | text (ISO 8601 UTC) | |

A partial unique index (`prompt_name` where `status='running'`) keeps at
most one running experiment per prompt.

## Assignment

The sticky record of "this `user_key`, under this experiment, got this
arm"; written once (`INSERT OR IGNORE`) on first resolve, read on every
one after. See [SPLIT.md](SPLIT.md).

| Field | Type | Notes |
|---|---|---|
| `experiment_id` | int, PK part, FK -> Experiment.id | |
| `user_key` | text, PK part | |
| `arm` | text | the arm name chosen |
| `version` | int | the version that arm mapped to at assignment time |
| `created_at` | text (ISO 8601 UTC) | |

## Outcome

Written to SQLite (queryable, updatable) and appended to a JSONL file
(`data/outcomes.jsonl`, immutable audit log; one line per `record`, one
more per `track`). `request_id` identifies the row; `user_key` is hashed
before either store ever sees it.

| Field | Type | Notes |
|---|---|---|
| `request_id` | text, PK | caller-supplied or `uuid4().hex` |
| `ts` | text (ISO 8601 UTC) | set at `record` time |
| `user_key_hash` | text | `sha256(user_key)`; raw value never stored |
| `prompt_name` | text | |
| `version` | int | |
| `arm` | text, nullable | `None` when resolved via the plain pointer |
| `experiment_id` | int, nullable | `None` when resolved via the plain pointer |
| `latency_ms` | real | from `ExecutionResult` |
| `ok` | bool | from `ExecutionResult` |
| `thumbs` | int, nullable (`1` \| `-1`) | set later via `track` |
| `task_ok` | bool, nullable | set later via `track` |
| `tokens_out` | int, nullable | set later via `track` |
| `custom` (`custom_json`) | JSON object | set later via `track` |

`OutcomeStore.summary(experiment_id)` aggregates these into per-arm
descriptive stats (not stored, computed on read): `count`, `ok`,
`thumbs_up`, `thumbs_down`, `task_ok` (raw counts) plus `ok_rate`,
`thumbs_net`, `avg_latency_ms`, `p50_latency_ms` (derived; plain
arithmetic and `statistics.median`, no significance testing or Bayesian
inference). Rendered as a table by the UI's Outcomes tab.
