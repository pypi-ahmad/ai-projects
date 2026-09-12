# Memory Schemas

## WorkingItem

Pydantic v2, `src/memory/working.py`.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | defaults to `uuid4().hex` |
| `role` | `"user" \| "assistant" \| "tool" \| "system"` | |
| `text` | `str` | |
| `token_count` | `int` | via `count_tokens()`; tiktoken `cl100k_base`, deterministic |
| `ts` | `datetime` | defaults to `now(UTC)` |
| `pinned` | `bool` | default `False`; pinned items are never evicted |
| `source_id` | `str \| None` | optional back-reference, default `None` |

## CompressJob

Pydantic v2, data only (no LLM call), `src/memory/working.py`.

| Field | Type | Notes |
|---|---|---|
| `item` | `WorkingItem` | the evicted item to compress |
| `reason` | `str` | default `"evicted_overflow"` |

## Episode

Pydantic v2, `src/memory/episodic.py`. Table `episodes` (SQLite), FTS5
mirror `episodes_fts` synced by triggers.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | defaults to `uuid4().hex` |
| `session_id` | `str` | every read (`list`, `search_keyword`) is scoped to one session |
| `ts` | `datetime` | defaults to `now(UTC)` |
| `type` | `"utterance" \| "tool" \| "decision" \| "compress_summary"` | |
| `text` | `str` | |
| `token_count` | `int` | via `count_tokens()` (reused from `working.py`) |
| `refs` | `list[str]` | working-item ids or tool names; stored as JSON |
| `salience` | `float` | `0.0`-`1.0`, default `0.5` |
| `pinned` | `bool` | default `False`; pinned rows are never evicted |

## EvictionPolicy

Pydantic v2, data only, `src/memory/episodic.py`.

| Field | Type | Notes |
|---|---|---|
| `max_rows` | `int \| None` | per-session cap, default `None` (no cap) |
| `max_age_days` | `float \| None` | default `None` (no cap) |
| `salience_threshold` | `float` | **no default**; caller must choose; rows with `salience >= threshold` are protected alongside pinned rows |

## Fact

Pydantic v2, `src/memory/semantic.py`. No separate SQLite metadata table --
the full model is the Qdrant point's payload, keyed by `fact_id`.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | defaults to `uuid4().hex`; reformatted to dashed UUID for the Qdrant point id |
| `text` | `str` | the thing embedded |
| `embedding_model` | `str` | defaults to `config.EMBED_MODEL` (`qwen3-embedding:0.6b`) |
| `created_at` | `datetime` | defaults to `now(UTC)` |
| `source_episode_id` | `str \| None` | default `None` |
| `confidence` | `float` | `0.0`-`1.0`, default `0.5` (not spec-mandated, mirrors `Episode.salience`'s default) |
| `namespace` | `str` | a `session_id`, or the literal string `"global"`; exact-match filter, no implicit union |
| `invalidated_at` | `datetime \| None` | default `None`; neither `search()` nor `recall()` filters it out; nothing reads this field yet |

`index_meta.json` (`data/memory/index_meta.json`): `{"embed_model": str,
"dim": int}`, written on first run from a live probe embedding. A later
mismatch against `config.EMBED_MODEL` raises `RebuildRequiredError`
(`src/memory/semantic.py`) rather than silently mixing vector spaces.

## CompressResult / DistillResult

Pydantic v2, data only, `src/memory/compress.py`.

| Model | Field | Type | Notes |
|---|---|---|---|
| `CompressResult` | `text` | `str` | LLM summary, or the extractive fallback |
| | `reason` | `str` | `"llm_summary"` or `"EXTRACTIVE_FALLBACK"` |
| `DistillResult` | `facts` | `list[str]` | 0-5 items; 0 is valid (nothing worth keeping) |

## MemoryConfig / MemoryReport

Pydantic v2, `src/memory/orchestrator.py`. `MemoryConfig` loads from
`config/memory.yaml` (missing file or missing keys fall back to the
defaults below).

| Section.field | Default | Notes |
|---|---|---|
| `episodic.max_rows` | `500` | per session |
| `episodic.max_age_days` | `30` | |
| `episodic.salience_threshold` | `0.6` | |
| `semantic.near_dup_threshold` | `0.92` | dedup cutoff during distill |
| `distill.recent_episodes_n` | `20` | episodes considered per distill pass |

No `working.token_cap` here; `WorkingMemory`'s cap is a constructor arg on
an instance the `Orchestrator` never creates itself, so a `MemoryConfig`
field for it would never be wired to anything. (Phase 7 removed exactly
that, plus an unused `distill.max_facts`; the 5-fact cap lives on
`DistillResult` in compress.py, nowhere else.)

`MemoryReport`: `working_evicted`, `episodes_written`, `episodes_evicted`,
`facts_distilled`, `facts_deduped` (all `int`, default `0`), plus
`compress_reason_counts: dict[str, int]`; what `Orchestrator.tick()`
changed on that call.

## ProvenanceEntry / PackedMemory

Pydantic v2, `src/memory/recall.py`.

| Model | Field | Type | Notes |
|---|---|---|---|
| `ProvenanceEntry` | `id` | `str` | the `WorkingItem`/`Episode`/`Fact` id |
| | `store` | `str` | `"working"` \| `"episodic"` \| `"semantic"` |
| | `score` | `float \| None` | only `"semantic"` entries carry a score; `None` for the other two |
| `PackedMemory` | `text` | `str` | the assembled, budget-fitted text |
| | `token_count` | `int` | tokens actually used (`<= token_budget`) |
| | `provenance` | `list[ProvenanceEntry]` | one entry per included item, in pack order |
