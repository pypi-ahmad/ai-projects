# Technical Notes

## Stack choices

| Choice | Rationale |
|---|---|
| `uv` (project + venv + deps) | Single tool for interpreter, venv, and dependency management; no separate pyenv/pip/virtualenv chain. |
| `pydantic-settings` | Typed, validated env-var loading with `.env` support and clear errors, for 4 providers' worth of config in one place. |
| Qdrant, local mode (`QdrantClient(path=...)`) | Disk-persisted, no server process, no Docker; empirically confirmed working on Windows in this project (pulls in `pywin32`/`portalocker` for file locking, no compile step). Holds the dense vector + full payload per chunk. |
| `bm25s` | Separate persisted lexical (BM25) index over chunk texts. It replaced the Phase 0 plan for Qdrant native sparse vectors after Phase 4 required a standalone persisted BM25 index. `rank_bm25`, the other allowed option, has not released since February 2022 and has no built-in save/load. `bm25s` is maintained, uses pure Python and numpy, works on Windows without Java or a compiled extension, and provides `save()`/`load()`. Its published benchmarks also report faster performance. |
| Ollama | Local model runtime for embedding, generation, rerank, and (via its OpenAI-compatible endpoint) OCR recognition; keeps every heavy model on one runtime with one unload mechanism. |
| Streamlit | UI framework explicitly requested; fast to wire a provider/model dropdown + chat + citations view. |
| `ruff` + `ty` + `pytest` | Linting and formatting, type checking, and tests. Each concern has one fast tool, without a separate isort/flake8/black/mypy chain. |
| `pymupdf` (ingest) | One dependency for both PDF text extraction *and* rendering a page to an image; needed for the "scanned page → OCR" branch, without a second library or an external Poppler binary on Windows. |
| `python-docx` (ingest) | Standard, minimal-dependency way to read `.docx` paragraph text; avoids hand-parsing OOXML. |
| `langdetect` (ingest) | Pure-Python language detection, no external binary, good enough to decide whether a page needs translation. |
| `ollama` (Python client, ingest + index) | Official client; used for OCR/translation calls (ingest) and embedding calls (index). |
| `qdrant-client` (index) | Ships local mode built in; no separate server package needed. |

## VRAM budget and unload rules

- Target GPU: RTX 4060, 8GB VRAM. Peak resident budget: **< 7GB**, leaving headroom for the OS
  and other processes.
- **One heavy Ollama model resident at a time.** The pipeline never has the embedding model, a
  3B-class chat model, and the OCR model loaded simultaneously; see `SPEC.md`'s hardware budget
  section for why (8GB cannot hold all three).
- Unload mechanism (Ollama): call the model with `keep_alive=0`, or explicitly `ollama stop
  <model>`, immediately after a stage finishes its batch of work, before the next stage's model
  loads. **Implemented for ingest** (`rag_pipeline.ingest.ocr.unload_model`,
  `rag_pipeline.ingest.pipeline.run_ingest`): every OCR/translation model actually invoked during
  a run is tracked in a `used_models` set and unloaded (`generate(..., keep_alive=0)`) once the
  whole batch finishes; not after each file, since re-loading per file would thrash VRAM far
  more than finishing the batch with one model resident. **Implemented for index**
  (`rag_pipeline.index.pipeline.run_index`, reusing `ingest.ocr.unload_model` directly rather than
  duplicating it): the embed model is unloaded once after the whole embedding batch, and only if
  anything was actually embedded (a fully-skipped idempotent re-run does zero Ollama calls at
  all, so there's nothing to unload). **Implemented for retrieve/generate** (added in a later
  pass after this was flagged as a gap): `retrieve/pipeline.py` unloads the embed model
  immediately after embedding the query (before the rerank model loads) and unloads the rerank
  model after reranking; `generate/pipeline.py` unloads the chat model after the answer comes
  back, only for the `ollama` provider (the 3 cloud providers have nothing local to unload).
  Trade-off: every single query now pays a full reload cost for each Ollama model it touches
  (no warm-model reuse across consecutive queries in the Streamlit session); the honest cost of
  actually enforcing "one heavy model at a time" on the query path, not just ingest/index.
- `qwen3-embedding:4b` (the embed fallback) and `qwen3.5:2b` (the generate/rerank fallback) are
  only to be used when profiling shows VRAM headroom after the default model is unloaded; they
  are not a default upgrade path.

### Ingest-specific VRAM note

A single ingest batch can, in the worst case, use three different Ollama models:
`AuditAid/PaddleOCR-VL-1.6-0.9B` (primary OCR), `qwen3-vl:2b` (OCR fallback, only if the primary
call raises), and `translategemma:4b` (only with `--translate`). `run_ingest` unloads every model
it used once, after the whole batch finishes (per the batch-end unload requirement); it does
**not** unload between files. This means a batch that mixes scanned PDFs (triggering OCR) with
non-English pages (triggering translation) can leave more than one of these models resident in
Ollama at the same time mid-batch; Ollama's own default multi-model memory management (not this
app) decides whether that fits in VRAM or evicts something. If a real corpus run OOMs partway
through a mixed batch, the fix is either setting `OLLAMA_MAX_LOADED_MODELS=1` in the environment
(forces Ollama to evict before loading a second model) or unloading on every model switch instead
of at batch-end; not yet implemented, since the literal requirement was batch-end unload.

## Index on-disk layout

Implemented in `src/rag_pipeline/index/` (`vector_store.py`, `lexical_store.py`, `pipeline.py`).
Two separate stores live under `--index` (default `data/indexes/`), both gitignored:

```
data/indexes/
├── qdrant_db/        # Qdrant local mode: one collection, "chunks"
│   ├── .lock
│   ├── meta.json
│   └── collection/chunks/...
└── bm25/             # bm25s.save() output: corpus.jsonl, vocab/params index files, .npy arrays
```

Qdrant local mode takes an OS-level file lock while open (`.lock` above). See the "locked index"
failure mode in `docs/RUNBOOK.md`. Neither store is intended to be human-readable or portable
across library versions.

### Embedding dimension

Measured empirically (`ollama.Client().embed(...)`, not assumed) on 2026-09-11:

| `--embed-model` | Dimension |
|---|---|
| `qwen3-embedding:0.6b` (default) | **1024** |
| `qwen3-embedding:4b` | **2560** |

The two are not interchangeable on an existing collection; `vector_store.ensure_collection`
raises a clear error if the configured model's dimension doesn't match an already-created
collection's dimension, rather than silently corrupting it or picking one arbitrarily.

### Idempotent re-index by chunk hash

Each chunk's Qdrant point ID is deterministic (`uuid5` of `f"{doc_id}:{chunk_index}"`, in
`vector_store.point_id`); re-indexing a document always maps to the *same* points, so an updated
chunk's vector overwrites in place instead of leaving an orphaned duplicate under a fresh ID. The
chunk's content hash is stored in Qdrant's payload; before embedding, `run_index` batch-retrieves
the currently-stored hashes for every point ID in the run and only calls Ollama's embed API for
chunks whose hash actually changed (or that are new); verified on a real 3-run sequence (all-new
→ all-skip → one-changed) in `tests/test_index.py`. The `bm25s` lexical index, by contrast, is
always fully rebuilt from the current full chunk list every run; building it is cheap (pure
numpy, no model calls), and `bm25s` has no supported API for a single-document incremental
update, so a full rebuild is still idempotent (same input → same index) even though it isn't
incremental the way the vector store's embedding step is.

## Chunking defaults

Implemented in `src/rag_pipeline/chunk/` (`splitter.py`, `pipeline.py`).

- **Strategy: sentence-aware recursive split.** Each page's text is broken into "atomic units"
  by trying paragraph breaks first, then sentences (`(?<=[.!?])\s+`), then whitespace-separated
  words, recursively, stopping as soon as a piece fits the token budget; falling back to a hard
  character slice only for a single pathological "word" that alone still doesn't fit (e.g. OCR
  garbage with no whitespace). Units are then greedily packed into windows.
- **Target size: 512 tokens. Overlap: 64 tokens** (both overridable via `--target-tokens` /
  `--overlap-tokens`). Overlap is whole atomic units (usually whole sentences) repeated at the
  start of the next window, not an arbitrary character slice; so overlapping content is always
  intact sentences, never a sentence cut in half.
- **Chunks never cross a page boundary, and therefore never cross a file boundary either**: each
  page's text is chunked independently, starting fresh every time (`page` is a single int per
  chunk, not a range). `chunk_index` runs continuously across a document's pages (0, 1, 2, ... for
  the whole file), not reset per page.
- **Empty pages are dropped** (produce zero chunks) rather than emitting an empty chunk.
- **Sentence-boundary heuristic is intentionally naive** (`_SENTENCE_RE` in `splitter.py`):
  splits after `.`/`!`/`?` + whitespace, which misreads abbreviations ("Dr. Smith") and decimals
  ("3.14") as sentence ends. Acceptable for chunking (not display); an occasional early split
  just shifts a chunk boundary slightly, it doesn't corrupt content. Revisit with a real sentence
  tokenizer if a real corpus shows this matters.
- **"Almost no text" PDF-scan threshold** lives in ingest (`MIN_TEXT_CHARS_PER_PAGE` in
  `src/rag_pipeline/ingest/parsers.py`), not chunking; by the time a page reaches the chunker it
  already has real (possibly OCR'd) text or was already dropped.

### Token counting

`src/rag_pipeline/chunk/tokenizer.py` tries to load the real tokenizer for the dense-embed model
(`Qwen/Qwen3-Embedding-0.6B`, via the `tokenizers` package's `Tokenizer.from_pretrained`, cached
locally after the first download) so chunk sizes are measured in the same tokens the embed model
will actually see. If that load fails for any reason (no network on first use, package
unavailable, etc.), it falls back to a documented **approximation**: `len(text) // 4` (a commonly
cited rough chars-per-token average for English BPE tokenizers); this is explicitly not exact
and is logged as a fallback, not silently substituted.

## Retrieve (Phase 5)

Implemented in `src/rag_pipeline/retrieve/` (`dense.py`, `lexical.py`, `fusion.py`,
`reranker.py`, `pipeline.py`). No answer generation here; see `docs/ARCHITECTURE.md`'s request
path.

- **Query embedded with whatever model built the index**, read from
  `data/indexes/index_meta.json` (written by `index/pipeline.py`'s `run_index`, only on a run
  that actually wrote vectors; never on a fully-skipped idempotent re-run, so it can't be
  overwritten with a model that was never actually used to embed anything currently stored).
- **RRF fusion uses rank, not raw score.** Dense cosine similarity and BM25 weights are on
  incompatible scales; `fusion.rrf_fuse` sums `1/(k+rank)` (k=60) per list a chunk appears in,
  using only each list's 1-indexed position. A chunk in both lists gets both contributions summed
 ; this is also how dedup-by-chunk-id falls out for free (one dict entry per chunk id).
  `--no-hybrid` skips BM25 and this fusion step entirely, ranking by raw dense score alone.
- **Reranking is batched (5 candidates/prompt) with a per-item fallback.** `qwen3.5:0.8b` is
  asked for exactly N numeric lines (one per passage) in one call; if the response doesn't parse
  into exactly N valid floats, that batch falls back to N separate single-candidate calls instead
  of silently misattributing scores to the wrong candidate. A single-candidate call that still
  can't be parsed scores 0.0 (logged as a warning) rather than crashing the query.
- **Full chunk payload always comes from Qdrant**, never from the `bm25s` corpus, even for a hit
  BM25 found; `bm25s`'s saved corpus only carries `{"id", "text"}`; `source_path`/`page` live in
  Qdrant's payload only, fetched once via `vector_store.get_payloads` for the fused top 20.
- **Live-Ollama test caveat**: `tests/test_retrieve.py` makes real embedding and reranking calls
  (dense-vs-BM25 differentiation can't be verified against a mocked embedder; the whole point is
  real semantic vs. lexical matching) and skips gracefully if Ollama isn't reachable. It's one of
  two test files in the suite with that live dependency (`tests/test_generate.py` is the other).

## Generate (Phase 6)

Implemented in `src/rag_pipeline/generate/`. `prompt.py` tags each retrieved chunk `[S1]`,
`[S2]`, ... and builds a system prompt requiring context-only answers, per-sentence citations,
treating source text as data not instructions (added Phase 8; see `docs/THREAT_NOTES.md`), and
an explicit admission when context is empty. `citations.py` parses which `[Sn]` tags the answer
actually used, dropping any index outside `1..len(results)`.

**Provider abstraction**: `providers/base.py`'s `Provider` protocol (`complete(system, user,
model) -> str`) + a `ProviderSpec` registry (`providers/registry.py`) so the CLI and Streamlit
UI select providers uniformly. Agnes AI and the generic OpenAI-compatible provider share one
client class (`providers/openai_compat_client.py`, built on the official `openai` SDK) because
Agnes documents itself as genuinely OpenAI-compatible Chat Completions; confirmed live against
its docs. Only the generic OpenAI-compatible provider passes `reasoning_effort="medium"`; Agnes
uses a different mechanism for that and doesn't take this parameter. Gemini uses the current
`google-genai` SDK, not the older deprecated `google-generativeai`.

**Fail clearly, don't crash**: a missing provider key raises `ProviderConfigError`; the CLI (and
the UI, via a try/except around `run_generate`) catches it plus `ValueError`/`RuntimeError` for a
clean one-line message instead of a raw traceback; the latter two also cover errors raised
deeper in the pipeline (e.g. a missing index), found by an actual crash during manual testing.

## Eval (Phase 7)

Implemented in `src/rag_pipeline/eval/`. `metrics.py`'s `recall_at_k` and `citation_hit_rate` are
pure functions (no network), computed from already-fetched retrieve/generate results. `judge.py`
adds an optional LLM-judged faithfulness score (default `qwen3.5:2b`, only invoked when
`--judge-model`/the UI toggle is explicitly set; an extra Ollama call per case, so it's opt-in).
`pipeline.py`'s `run_eval` calls `run_retrieve` and `run_generate` **separately** per case (not
reusing `run_generate`'s internal retrieval) so `recall_at_k` gets full `RetrievalResult` objects
with `source_path`/`page` to match against; a deliberate small duplication of one retrieve call
per case, traded for not having to reshape `GenerateResult.retrieval_trace`'s dict shape.

## UI (Phase 7)

`src/rag_pipeline/ui/app.py`, a single-file Streamlit app calling the same `run_ingest`/
`run_chunk`/`run_index`/`run_retrieve`/`run_generate`/`run_eval` functions the CLIs use; no
subprocess calls, no duplicated logic. Ollama models in the sidebar are live-detected via
`ollama.Client().list()` and intersected with the allowlist, not just the static allowlist alone
(a model can be allowed but not actually pulled). Long operations use `st.status`/`st.spinner`
so the UI shows progress rather than appearing frozen, per the explicit "don't block without a
status area" requirement. No `AppTest`-based automated tests exist for this file; see
`README.md`'s Limitations.

## Launcher (`run.cmd`)

Deliberately plain `venv` + `pip`, not `uv`; a self-contained path for a user without `uv`
installed, separate from this repo's `uv`-managed dev environment (both work). `requirements.txt`
is autogenerated from `uv.lock` via `uv export --no-hashes --no-dev --format requirements-txt`
and pinned to the exact versions installed while building this project; regenerate it after any
`uv add`/`uv remove`, or `run.cmd`'s installs drift from what the dev environment actually uses.
`run.cmd` writes `.env.example` itself at runtime if it doesn't exist yet, because Claude Code's
Write tool cannot create `.env`-pattern files in this project because of a global permission deny rule.
The batch script that a user later executes is a different actor than the Write
tool, so it isn't subject to that restriction.
