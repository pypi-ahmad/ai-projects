# Cache policy

**Implemented (Phase 5).** All policy is configured in `config/cache.yaml`
(`PolicyConfig`, `src/policy/config.py`) and enforced by
`SemanticCache.put`/`.get` (`src/cache/service.py`), via the pure decision
functions in `src/policy/enforcement.py`. A missing config file falls back
to `PolicyConfig()`'s own defaults, listed below and mirrored in the YAML
file's comments — policy is never silently off.

## TTL (`ttl_seconds`)

Default `0` = never expires.

- If a `CacheRecord` passed to `put()` doesn't already set `expires_at`
  and `ttl_seconds > 0`, `put()` computes `expires_at = created_at +
  ttl_seconds` and stores that. An explicit `expires_at` on the record is
  left alone.
- `get()` checks `expires_at` on every candidate (`src/policy/enforcement.py:is_expired`)
  before considering it a match. An expired exact-match or top semantic
  candidate is **lazily deleted** (`QdrantStore.delete_point`) and
  treated as if it weren't there — the lookup falls through (exact →
  semantic; semantic candidate → the next-best candidate) rather than
  failing outright. See `docs/ARCHITECTURE.md`.
- Nothing runs a background sweep for expired entries — cleanup only
  happens when a `get()` actually touches an expired point.

## Max entries per namespace (`max_entries`)

Default `10000`; `0` = unlimited.

- Checked at the end of `put()`, not on `get()`. When a namespace exceeds
  the limit, `select_eviction_candidates()` sorts that namespace's points
  by `last_hit_at` (falling back to `created_at` for entries never hit)
  and evicts the oldest until back at the limit.
- `ponytail`: eviction fetches the whole namespace into memory to sort
  (`QdrantStore.scroll_all`) — fine at the scale a single namespace is
  expected to hold; switch to Qdrant `order_by` + a payload index on
  `last_hit_at` if a namespace grows large enough for that to matter.

## Min answer length (`min_answer_chars`)

Default `3`. `put()` rejects (raises `PolicyRejectedError`, does not
embed or store) any record whose answer, after `.strip()`, is shorter
than this — guards against caching empty, truncated, or error-placeholder
strings. A judgment-call default, not derived from real error-string
data; adjust if it over/under-rejects in practice.

## Never-cache regexes (`never_cache_regexes`)

Default patterns (see `config/cache.yaml` for the checked-in list; each
pattern controls its own case sensitivity via inline `(?i)`, there's no
global flag):

- `(?i)api[-_ ]?key` — literal "api key" and common variants.
- `(?i)\b(secret|password|passwd)\b\s*[:=]` — a secret/password being
  assigned or stated, not just the word appearing incidentally.
- `\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b` — a credit-card-shaped digit
  sequence. `ponytail`: length/shape match only, no Luhn check — swap in
  a proper card-number validator if false positives/negatives matter.

`put()` rejects if the answer matches **any** pattern. Only the answer is
checked, not the query.

## Namespace

Cache entries are scoped to a namespace so unrelated callers/apps don't
collide or leak answers into each other's lookups (e.g. two products both
asking "what's your refund policy?" should not share a cache entry unless
explicitly intended to).

- One Qdrant collection for the whole cache, not one per namespace.
  Namespace is a payload field, and every query/scroll/delete/count that
  can touch more than one point is filtered on it — see "Namespace
  isolation" in `docs/TECHNICAL.md` for the decision and why, and
  `src/store/qdrant_store.py`'s `_namespace_conditions` for the single
  choke point that builds that filter.
- Default namespace: `"default"` (`CacheKey`/`CacheRecord`, `docs/TECHNICAL.md`).

## Cross-model serving (`require_same_producer_model`)

Default `true`. This is the "unless policy allows" from `CacheKey`'s
design (`docs/TECHNICAL.md`) — it decides whether `producer_model` is
actually enforced as a filter:

- `true` (default): `get(..., producer_model=X)` only returns answers
  whose stored `producer_model` equals `X`. A `granite` answer is never
  served to a caller asking on behalf of `gemini`.
- `false`: `producer_model` is accepted by `get()` but not applied as a
  filter — any producer's cached answer is eligible. Use this only if
  cross-model answer reuse is actually acceptable for your callers.

This does not affect `put()` — every record still records its true
`producer_model`; the flag only controls whether `get()` filters on it.
