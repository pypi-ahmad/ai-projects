# Memory Policies

## Eviction

- **Working** (`WorkingMemory.evict()`, `src/memory/working.py`); while
  `total_tokens() > token_cap` (default 1500): repeatedly remove the oldest
  unpinned item that is not the latest user-role item, and package it as a
  `CompressJob`. Never touches a pinned item or the latest user item, even
  if that means staying over cap. Never drops data silently; every
  eviction produces a `CompressJob` for `compress.py`'s `Compressor` to
  consume, orchestrated by `Orchestrator.tick()` (`src/memory/orchestrator.py`).
- **Episodic** (`EpisodicMemory.evict(session_id, policy)`,
  `src/memory/episodic.py`); scoped to one session. Two independent
  triggers: rows older than `max_age_days`, and total row count over
  `max_rows`. In both cases, only rows with `pinned = False` and
  `salience < salience_threshold` are removable; among those, lowest
  salience goes first, oldest breaking ties. Same invariant as working
  memory: never removes a protected row, even if the session stays over
  cap. Unlike working memory, this is a hard delete; no `CompressJob`,
  episodic is already the compressed form.
- **Semantic** (`SemanticMemory`, `src/memory/semantic.py`); no eviction
  yet, only `invalidate(fact_id)`, which sets `invalidated_at` and leaves
  the point in Qdrant. Neither `search()` nor `recall()` filters on
  `invalidated_at`; nothing reads it yet. Real eviction (max-fact-count,
  low-confidence pruning, or none) is still TBD.

## Compress triggers

- Working buffer exceeds its token budget (primary trigger) --
  `Orchestrator.tick()` step 1, every tick, no-op if under cap.
- Explicit flush (e.g., end of session); not implemented.
- Turn-count threshold, if token budget alone proves too bursty in
  practice; not implemented.

## Distillation (Phase 5)

`Orchestrator.tick(distill=True)`; opt-in, not automatic on every tick:

1. Take the most recent `distill.recent_episodes_n` episodes (config, default 20).
2. `Distiller.distill()` asks the compress model for 0-5 standalone facts
   (JSON, schema-constrained via Ollama's `format=`). Invalid JSON gets
   exactly one repair attempt, always with `config.COMPRESS_MODEL_DEFAULT`
   regardless of which model produced the bad output. Still invalid, or
   provider unreachable at any point: zero facts, not a crash.
3. Each candidate fact is checked against existing facts in its namespace
   via `SemanticMemory.search(..., k=1)`; a top score `>=
   semantic.near_dup_threshold` (config, default 0.92) skips the insert
   (near-dup, not stored again) rather than upserting a duplicate.
4. "No new entities invented" is a prompt instruction only; nothing here
   mechanically verifies it against the source episodes.

## Recall packing (Phase 6)

`recall(query, session_id, token_budget)` (`src/memory/recall.py`) is a
deliberately simple/greedy packer; explicitly told not to vendor
`3-Context-Assembly-Service`'s budget allocator. Three tiers, in this order:

1. **Working**; always included, newest-first, no query relevance
   filtering. If the recall `token_budget` is smaller than what's actually
   in working memory, it gets trimmed to fit (oldest dropped first, same
   direction as its own eviction) rather than blowing the budget.
2. **Semantic**; whatever budget remains after working, spent on facts
   ranked by `(confidence, score)` descending, highest first.
3. **Episodic**; whatever's left after that: keyword matches (via
   `search_keyword`, which now sanitizes the query; see
   `src/memory/episodic.py`) first, then most-recent, deduped.

Each tier's items are considered in that priority order; the first
candidate that doesn't fit in the remaining budget stops that tier (no
reordering to squeeze in a smaller item later). This is the resolution of
an ambiguity in the spec ("always include working" vs. a priority list
that names semantic first); working gets a guaranteed reservation, then
the stated semantic-over-episodic priority governs what's left.
