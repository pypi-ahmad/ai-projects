# Technical reference

Facts here are sourced from the Ollama and Qdrant docs (checked 2026-09-11),
not assumed. Update this file if either project changes these contracts.

## Embed model output size

| Model | Default embedding dimension | MRL-supported range |
|---|---|---|
| `qwen3-embedding:0.6b` | 1024 | 32–1024 |
| `qwen3-embedding:4b` | 2560 | 32–2560 |

Source: Qwen3-Embedding model card (Hugging Face) — both sizes support
Matryoshka Representation Learning (MRL), i.e. a prefix of the full
embedding is itself a valid, usable embedding at lower quality.

### Requesting a smaller dimension (MRL truncation)

Ollama's `/api/embed` accepts a `dimensions` request parameter that
truncates the model's output to that size server-side (this is what
exercises the model's MRL support — it is not a generic truncation hack
bolted on by Ollama). If you use this:

- **Document the chosen dimension wherever the collection is created** —
  the Qdrant collection's vector size must match exactly.
- Every vector in a collection must use the *same* dimension. Changing the
  configured dimension is a breaking change requiring a rebuild, same as
  changing the model entirely (see `docs/RUNBOOK.md`).
- Default (Phase 1 assumption): use each model's full default dimension —
  1024 for `qwen3-embedding:0.6b`, 2560 for `qwen3-embedding:4b`. Only set
  `dimensions` explicitly if a later phase needs the smaller footprint.

## Distance metric

**Cosine** (`qdrant_client.models.Distance.COSINE`).

Qdrant normalizes vectors on upload when the collection uses Cosine
distance, and implements the metric as a dot product over the normalized
vectors. Practical effect: the `score` a query returns *is* the cosine
similarity, not a distance — higher score means more similar.

```python
from qdrant_client import models

client.create_collection(
    collection_name="semantic_cache",
    vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE),
)
```

(`size` must equal the active embed model's output dimension — 1024 for
the default `qwen3-embedding:0.6b`.)

## Threshold units

The threshold is a **cosine similarity score**, compared as `score >=
threshold`, in the same units Qdrant's Query API returns.

```python
client.query_points(
    collection_name="semantic_cache",
    query=query_vector,
    limit=1,
    score_threshold=THRESHOLD,  # "return points with scores better than this"
)
```

- Range is theoretically [-1, 1]; in practice, on-topic query pairs from
  the same embedding model score well above 0.
- `score_threshold` is applied by Qdrant itself (server-side filter on the
  Query API), not recomputed in application code — the app's job is to
  interpret an empty/below-threshold result as a miss.
- **No distance→similarity conversion is needed for our metric.** Verified
  two ways, not assumed: (1) Qdrant's own migration docs
  ("diagnosing-discrepancies") give `score` as directly comparable to
  `np.dot(query, target) / (norm(query) * norm(target))` — the standard
  cosine similarity formula, not a distance; (2) empirically, with real
  `qwen3-embedding:0.6b` vectors, a paraphrase of a stored query scored
  `0.9655` and an unrelated query scored `0.5133` against the same stored
  vector — both consistent with "higher = more similar" and with the
  0.89 default threshold separating them correctly. (Distance metrics
  like Euclidean work the other way in Qdrant's own API — lower is
  better there — which is the case this conversion note exists to guard
  against; it doesn't apply to Cosine.)
- Default threshold: **0.89**, from `config/cache.yaml`'s `threshold` key
  (`PolicyConfig`, `docs/CACHE_POLICY.md`) — not the `CACHE_SCORE_THRESHOLD`
  env var mentioned in earlier phases, which `src/cache/service.py` no
  longer reads. Override per-instance with `SemanticCache(score_threshold=...)`,
  or retune a live instance with the `score_threshold` property (what the
  Streamlit UI's slider does, `src/ui/app.py`) — neither touches the
  index, since threshold is a comparison cutoff, not a property of stored
  vectors (`docs/RUNBOOK.md`).

### Empirical threshold calibration (Phase 6)

Measured live against real `qwen3-embedding:0.6b` vectors, comparing each
seeded FAQ query (`scripts/seed_demo.py`) to a natural paraphrase a user
might actually type:

| Original | Paraphrase | Cosine score |
|---|---|---|
| "How do I reset my password?" | "How can I reset my password?" | 0.9441 |
| "What is your refund policy?" | "What's your policy on refunds?" | 0.9297 |
| "Is there a free trial?" | "Do you have a free trial?" | 0.9257 |
| "How can I contact support?" | "How do I get in touch with customer support?" | 0.8509 |
| "Where is my order?" | "How do I track my order?" | 0.8112 |
| "How do I reset my password?" | "I forgot my password, how do I change it?" | 0.8063 |
| "What is your refund policy?" | "Can I get a refund?" | 0.7722 |
| "What are your business hours?" | "What time do you open and close?" | 0.7704 |
| "What are your business hours?" | "When are you open?" | 0.7589 |

**Takeaway: at the 0.89 default, only 3 of these 9 natural paraphrases
hit.** Close-to-literal rewording (reusing most of the same words) scores
0.92+; genuine rewording with different vocabulary commonly lands in the
0.75–0.85 range for this model on short FAQ-style text — well short of
0.89. This isn't a bug in the threshold logic, it's real recall/precision
tuning data: 0.89 favors precision (few false hits) over recall (catching
more real paraphrases). If recall matters more for your traffic, this is
evidence to lower `config/cache.yaml`'s `threshold` — a decision left to
you, not changed here.

## Namespace isolation

**Decision: one Qdrant collection for the whole cache, isolated by a
mandatory payload filter — not one collection per namespace.** Why:

- `data/cache/index_meta.json` (above) is a single, cache-wide file
  recording one embed model/dimension. One collection keeps that
  assumption true; per-namespace collections would need per-namespace
  index metadata and a rebuild policy that tracks each one separately.
- Namespace count is expected to be small and caller-controlled, not
  needing collection-level isolation (shard limits, per-tenant physical
  storage) that per-namespace collections would exist to provide.

The filter is not optional decoration: `src/store/qdrant_store.py`
builds every filter through one function, `_namespace_conditions()`, and
every method that can touch more than a single known point ID (`search`,
`find_exact`, `delete_namespace`, `count(namespace=...)`) goes through it.
There is no code path that queries or deletes across the whole collection
without a namespace condition attached (`tests/test_service.py::test_namespaces_do_not_leak`
verifies a record in one namespace is invisible to a lookup in another,
even for identical query text).

`producer_model` rides the same mechanism as a second, optional filter
condition (`CacheKey`/`get(..., producer_model=...)` in `docs/CACHE_POLICY.md`).

## Qdrant point IDs

Qdrant (including local/embedded mode) accepts only an unsigned integer or
a string parseable as a UUID as a point ID — an arbitrary string raises
`ValueError`. `CacheRecord.id` is typed `str` (Phase 2) but every caller
must populate it with `str(uuid.uuid4())`-style values; `src/cache/__main__.py`
does this for CLI-created records.

## Ollama contract this repo depends on

- Endpoint: `POST http://localhost:11434/api/embed`
- Request fields used: `model`, `input` (`str` for a single embed, `list[str]`
  for batch — both hit the same endpoint), optionally `dimensions` for MRL
  truncation.
- `keep_alive` (set `0` to unload immediately after the call — see the 4060
  note in `README.md`) is part of the contract but **not yet wired into
  `src/embed/ollama_client.py`** (Phase 3 didn't need it) — add it when a
  phase actually implements the idle-unload behavior.
- Ollama must be running and the target model pulled before any lookup —
  see `docs/RUNBOOK.md`.
- Implementation: `src/embed/ollama_client.py` (`embed_one`, `embed_batch`),
  using stdlib `urllib` — no `requests`/`ollama` package dependency. Raises
  `OllamaEmbedError` on any HTTP failure or unreachable host.

## Index metadata (`data/cache/index_meta.json`)

Sidecar file recording which embed model (and dimension) the vector index
was built with — `src/store/index_meta.py`.

```python
class IndexMeta(BaseModel):
    embed_model: str
    dim: int
    mrl_dim: int | None = None  # set only if `dim` came from explicit MRL truncation
```

Before a lookup searches the index, `ensure_embed_model_matches(meta,
requested_model=..., requested_dim=...)` compares the request's embed
model and effective dimension (`mrl_dim` if set, else `dim`) against this
file. A mismatch raises `RebuildRequiredError` (`.code ==
"REBUILD_REQUIRED"`) instead of searching against incompatible vectors —
see `docs/RUNBOOK.md`.
