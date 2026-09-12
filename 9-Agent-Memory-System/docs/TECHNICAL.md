# Technical notes

## Stack

| Concern | Choice | Why (from code/comments) |
|---|---|---|
| Data models | Pydantic v2 (`BaseModel`) | Used for every persisted or returned record (`WorkingItem`, `Episode`, `Fact`, `MemoryReport`, etc.) across all of `src/memory/`; no dataclasses or plain dicts used for these. |
| Token counting | `tiktoken`, encoding `cl100k_base` | Comment in `src/memory/config.py`: "Same approach as the Context Assembly Service project"; noted there as approximate (~5-10% high) for the actual Ollama models in use, called conservative for budget enforcement. |
| Episodic storage | `sqlite3` (standard library) + FTS5 virtual table | `episodic.py` docstring: FTS5 availability was checked directly against this machine's Python before relying on it ("no LIKE fallback: if a deployment's sqlite3 lacks FTS5, table creation fails loudly at startup"). |
| Semantic storage | `qdrant-client`, `QdrantClient(path=...)` (embedded mode) | `semantic.py` docstring: runs embedded, no server, no Docker; the full `Fact` is stored as the point payload rather than in a separate table. |
| Embeddings / compression | `ollama` Python package | Only external service call in the codebase; model names are constants in `config.py`, not user input. |
| Config file format | YAML (`config/memory.yaml`) via `pyyaml` | Read once, at `Orchestrator` construction, by `orchestrator.py:load_memory_config()`. |
| UI | Streamlit | `src/memory/ui.py`; `@st.cache_resource` used to keep one `WorkingMemory`/`EpisodicMemory`/`SemanticMemory` per running process. |
| Packaging | `uv`, `uv_build` backend | `pyproject.toml` `[build-system]`; `uv.lock` is the lockfile, `requirements.txt` is a generated export of it. |

## Invariants

- **Working memory eviction never removes a pinned item or the most
  recent user-role item**, even if the buffer stays over its token cap
  as a result (`WorkingMemory.evict()` / `_pick_evictable()`,
  `working.py`). Every item it does evict becomes a `CompressJob` --
  eviction never silently discards data.
- **Episodic eviction is the same shape**: rows with `pinned = True` or
  `salience >= salience_threshold` are never removed, even if the
  session stays over `max_rows`/`max_age_days`
  (`EpisodicMemory.evict()`, `episodic.py`). Unlike working memory, this
  is a hard SQL `DELETE` -- there is no `CompressJob` equivalent for
  episodic eviction.
- **`search_keyword` sanitizes its input.** The raw query is reduced to
  bare word tokens joined with `OR` (`_to_fts_query`, `episodic.py`)
  before being passed to FTS5's `MATCH`, because FTS5's own query syntax
  treats punctuation as operators and would otherwise raise
  `sqlite3.OperationalError` on ordinary natural-language questions.
- **`EpisodicMemory`'s SQLite connection is opened with
  `check_same_thread=False`** (`episodic.py`) because it is meant to be
  held by one long-lived object (e.g. `@st.cache_resource` in `ui.py`)
  across calls that may land on different threads.
- **`DistillResult` allows zero facts.** `facts: list[str]` has no
  minimum length (`compress.py`) -- an episode batch with nothing worth
  keeping is expected to distill to an empty list rather than pressure
  the model into inventing one.
- **Near-duplicate facts are skipped, not merged.** Before inserting a
  distilled fact, `Orchestrator._distill()` searches existing facts in
  the same namespace; a top match with score `>=
  MemoryConfig.semantic.near_dup_threshold` (default `0.92`) causes the
  candidate to be dropped, not upserted (`orchestrator.py`).
- **A semantic-index rebuild is enforced, not just recommended.** If
  `data/memory/index_meta.json`'s recorded `embed_model` does not match
  `config.EMBED_MODEL`, `SemanticMemory.__init__` raises
  `RebuildRequiredError` immediately rather than continuing with a
  mismatched vector space (`semantic.py`).

## Error handling

`Compressor.compress()` and `Distiller.distill()` (`compress.py`) both
catch any exception from their injected `chat_fn` (which defaults to a
real `ollama.chat` call) and degrade instead of raising:

- `Compressor` falls back to an extractive summary (first and last
  sentence of the input, `_extractive_fallback`) and reports
  `reason="EXTRACTIVE_FALLBACK"` on the returned `CompressResult`.
- `Distiller` returns `DistillResult(facts=[])`. If the model's JSON
  fails to parse, exactly one repair attempt is made, always with
  `config.COMPRESS_MODEL_DEFAULT` regardless of which model produced the
  bad output; if that also fails to parse or the call itself raises,
  the result is again an empty fact list.

The stated reason (`compress.py` module docstring): `Orchestrator.tick()`
must keep working with Ollama down. No other module in `src/` catches
exceptions this broadly; `SemanticMemory`'s embedding calls
(`ollama.embed`) are not wrapped and will raise on a connection failure.

## Persistence paths

All runtime state lives under `data/memory/` (gitignored except
`.gitkeep`):

| Path | Written by |
|---|---|
| `data/memory/working.json` | `WorkingMemory.snapshot()` (only called explicitly -- from `ui.py` after append/tick, and from `scripts/seed_demo.py`) |
| `data/memory/memory.db` | `EpisodicMemory`, on every `write()`/`evict()` (auto-committed) |
| `data/memory/qdrant/` | `SemanticMemory`, on every `upsert_fact()`/`invalidate()` |
| `data/memory/index_meta.json` | `SemanticMemory`, written once on first run (records `embed_model` and vector `dim`) |

`config/memory.yaml` and `.streamlit/config.toml` are project
configuration, committed to the repo, not runtime state.
