# Local RAG Pipeline specification

Hybrid-retrieval RAG pipeline, local-first, running on an RTX 4060 (8GB VRAM). Streamlit UI,
four selectable LLM providers, single double-clickable launcher.

## Hardware budget

- Peak resident VRAM target: **< 7 GB**.
- Keep one heavy Ollama model resident at a time. Unload it before loading the next stage's model.
- Indexes persist to disk so a restart never re-embeds the corpus.

## Allowed Ollama models

All 8 tags below were verified live against `ollama.com/library` (and `ollama.com/AuditAid` for
the community one) on 2026-09-11. Do not add or substitute tags without re-verifying; a wrong
tag fails `ollama pull` loudly, but a wrong org/name can silently resolve to an unrelated model
(see the `AuditAid/PaddleOCR-VL-1.6-0.9B` note below).

| Stage | Default | Fallback |
|---|---|---|
| Generate answers | `granite4.1:3b` | `qwen3.5:2b`, then `qwen3.5:0.8b` |
| Dense embed | `qwen3-embedding:0.6b` | `qwen3-embedding:4b` (only with VRAM headroom) |
| Pointwise rerank | `qwen3.5:0.8b` | `qwen3.5:2b` if quality is poor |
| Scanned PDF / image OCR | `AuditAid/PaddleOCR-VL-1.6-0.9B` | `qwen3-vl:2b` for layout / figure captions |
| Non-English ingest | `translategemma:4b` | skip if corpus is English-only |

The allowlist has no dedicated reranker. Prompt `qwen3.5:0.8b` with a tight scoring prompt in
batches to narrow the top 20 candidates to the top 5.

### OCR integration note (important, non-obvious)

`AuditAid/PaddleOCR-VL-1.6-0.9B` is a pullable Ollama model in the **community namespace**
(publisher `AuditAid`), not the official library. It is **not** on Hugging Face under that org.
The official model is `PaddlePaddle/PaddleOCR-VL-1.6`; `AuditAid` republished a GGUF to Ollama's
registry. It provides the VLM-recognition half of PaddleOCR-VL. Full document parsing, including
layout analysis and recognition, needs the `paddleocr` Python package. That package orchestrates
layout detection and calls this model **through
Ollama's own OpenAI-compatible endpoint**:

```
paddleocr doc_parser --input <file> \
    --vl_rec_backend llama-cpp-server \
    --vl_rec_server_url http://localhost:11434/v1 \
    --vl_rec_api_model_name "AuditAid/PaddleOCR-VL-1.6-0.9B"
```

The heavy model stays in Ollama, which respects the one-model-at-a-time rule. `paddleocr`, plus
its `paddlepaddle` dependency for layout detection, coordinates the work and is not a second
GPU-resident model. Verify `paddlepaddle` wheel availability for Python 3.13 on Windows when
building the OCR phase. It and FastEmbed's `onnxruntime` dependency may lag a new Python release.

## LLM providers (all required, selectable in the UI)

| Provider | Model(s) | Config |
|---|---|---|
| Ollama (local) | detected installed models; default generate = `granite4.1:3b` | `OLLAMA_HOST` (default `http://127.0.0.1:11434`) |
| Agnes AI | `agnes-2.5-flash` (fixed) | `AGNES_API_KEY`; base URL `https://apihub.agnes-ai.com/v1` (fixed in code) |
| OpenAI-compatible | dropdown: `gpt-5.6-luna`, `gpt-5.6-terra` (medium effort) | `OPENAI_API_KEY`, `OPENAI_BASE_URL` |
| Google Gemini | dropdown: `gemini-3.5-flash-lite`, `gemini-3.7-flash` | `GOOGLE_API_KEY` |

`src/rag_pipeline/config.py` is the single source of truth for the allowlist and env var names.
`Settings.available_providers()` reports which providers have their required env vars set.

### `.env.example`

The Write tool is blocked from creating `.env*` files (a deny rule in this user's global Claude
Code settings, consistent with the `user-env-variable` skill's "never create `.env` files" rule).
Save this yourself as `.env.example` in the project root:

```
# Ollama runs locally; no key needed. Override only if it's not on the default host/port.
OLLAMA_HOST=http://127.0.0.1:11434

# Agnes AI (model + base URL are fixed in code, per spec) -- key only.
AGNES_API_KEY=

# OpenAI-compatible endpoint. Dropdown models (gpt-5.6-luna, gpt-5.6-terra) are fixed in code.
OPENAI_API_KEY=
OPENAI_BASE_URL=

# Google Gemini.
GOOGLE_API_KEY=
```

## Vector store: Qdrant embedded (local mode) + a separate bm25s lexical index

**Revised in Phase 4** from the original Phase 0 plan below; kept here for the record, then
corrected.

~~Decision: Qdrant's local mode using one collection with a dense vector and a sparse vector (real
BM25 weights via FastEmbed's `Qdrant/bm25` model), fused with Qdrant's native
`FusionQuery(fusion=Fusion.RRF)`.~~ Phase 4's implementation instructions explicitly asked for a
**separate, persisted BM25 index** ("`rank_bm25` or equivalent") alongside the vector store, not
Qdrant sparse vectors in the same collection; a real architecture change, not a detail. Current
decision:

- **Vector store: Qdrant local mode** (`QdrantClient(path=".../qdrant_db")`), dense vectors +
  full payload only. Empirically confirmed Windows-friendly, no Docker (see `docs/ARCHITECTURE.md`
  and `docs/TECHNICAL.md`).
- **Lexical store: `bm25s`**, not `rank_bm25`; `rank_bm25` hasn't released since Feb 2022 and has
  no built-in persistence; `bm25s` is actively maintained, pure Python + numpy, ships
  `save()`/`load()`, and is dramatically faster per its own published benchmarks. Saved separately
  under `data/indexes/bm25/`.
- Consequence: the retrieve phase (not yet built) fuses the two stores' result lists with RRF
  itself in Python, rather than issuing one Qdrant `FusionQuery`; see `docs/ARCHITECTURE.md`'s
  request-path diagram.

Chroma was not reconsidered in Phase 4; Qdrant's local mode was already empirically verified
working on Windows (see `docs/ARCHITECTURE.md`), and the original reason to prefer Qdrant over
Chroma (avoiding a two-store sync problem) no longer fully applies now that BM25 is a second store
regardless; this wasn't revisited since Qdrant's Windows-friendliness was independently confirmed
either way and switching now would be pure churn.

## Pipeline

```
ingest → parse/OCR → chunk → embed + lexical index → hybrid retrieve → rerank → cited answer
```

Corpus target: 1000+ mixed docs (pdf, docx, txt, md, html, png/jpg scans).

## Non-goals

Cloud-only vector DBs, models outside the allowlist for the local path, training, multi-GPU.

## Phase plan

- **Phase 0 (done); Foundations.** `uv`-managed project scaffold (Python 3.13.15, `src/` layout,
  ruff+ty+pytest), `config.py` (provider/model allowlists + env-driven settings, with a runnable
  self-check), this spec, vector store decision. Definition-of-Done check:
  `uv run python -m rag_pipeline.config`.
- **Phase 1 (done); Docs & scaffolding.** README, `docs/ARCHITECTURE.md`, `docs/TECHNICAL.md`,
  `docs/RUNBOOK.md`, `docs/EVAL.md` (stub), `.env.example` content (see note below),
  `requirements.txt` stub, `.gitignore`, empty package dirs under `src/rag_pipeline/` (`ingest`,
  `chunk`, `index`, `retrieve`, `generate`, `eval`, `ui`), `data/{raw,processed,indexes,eval}`
  placeholders, `run.cmd` stub. No retrieval logic; pure docs and structure.
- **Phase 2 (done); Ingest + parse/OCR.** File-type routing (pdf/docx/txt/md/html/png/jpg/jpeg/
  tiff), PaddleOCR-VL integration (with `qwen3-vl:2b` fallback) per the note above,
  `translategemma:4b` for non-English pages behind `--translate`. Incremental via content hash.
  Definition-of-Done check: `uv run pytest -q` and
  `uv run python -m rag_pipeline.ingest --input tests/fixtures --out <tmp>`.
- **Phase 3 (done); Chunk.** Sentence-aware recursive split, 512 target tokens / 64 overlap,
  never crosses a page (or file) boundary, empty pages dropped, token counts from the
  `qwen3-embedding:0.6b` tokenizer (approximated if that can't be loaded; see
  `docs/TECHNICAL.md`). Writes `data/processed/chunks.jsonl`. No embedding or indexing yet.
  Definition-of-Done check: `uv run pytest -q` and
  `uv run python -m rag_pipeline.chunk --in <ingest output dir> --out <tmp>/chunks.jsonl`.
- **Phase 4 (done); Embed + index.** Qdrant collection (`chunks`, dense vectors + payload only;
  see the revised vector-store decision above) + a separate `bm25s` lexical index, both under
  `data/indexes/`. Embed via `qwen3-embedding:0.6b` (config flag for `qwen3-embedding:4b`, 1024
  vs. 2560 dims, measured empirically). Idempotent re-index by chunk hash (deterministic point
  IDs; only new/changed chunks are re-embedded). Embed model unloaded once per run, only if
  anything was embedded. No query path. Definition-of-Done check: `uv run pytest -q` and
  `uv run python -m rag_pipeline.index --chunks <chunks.jsonl> --index <tmp>`.
- **Phase 5 (done); Hybrid retrieve + rerank.** Embed query with the same model the index was
  built with (recorded in `data/indexes/index_meta.json`, written by Phase 4's `run_index`).
  Dense top 50 + BM25 top 50, RRF fusion (k=60, client-side across the two separate stores; see
  the revised vector-store decision above), dedup by chunk id, fused top 20. Pointwise rerank
  with `qwen3.5:0.8b` (numeric 0-1 score, batched with a per-item fallback on unparseable output),
  top 5 returned. `hybrid`/`rerank`/`n`/`k` all configurable; no answer generation. Definition-of-
  Done check: `uv run pytest -q` (includes live-Ollama tests, skipped gracefully if unreachable)
  and `uv run python -m rag_pipeline.retrieve --index <built index> --query "..."`.
- **Phase 6 (done); LLM providers.** Shared `Provider` contract (`complete(system, user, model)`)
  + a `ProviderSpec` registry so the CLI (and later Streamlit) enumerate/select providers
  uniformly. 4 concrete implementations: Ollama (native client), Agnes AI + the generic
  OpenAI-compatible provider (both via the official `openai` SDK; Agnes documents itself as
  OpenAI-compatible Chat Completions, confirmed live against its docs), Gemini (`google-genai`).
  Context block tags chunks `[S1]`, `[S2]`, ...; system prompt enforces context-only answers,
  per-sentence citations, and an insufficient-context admission. A missing provider key raises
  `ProviderConfigError`, caught at the CLI boundary for a clean message + exit 1, never a raw
  traceback (extended to also catch `ValueError`/`RuntimeError` from deeper in the pipeline, e.g.
  a missing index, for the same reason). **Only Ollama has been run end-to-end against a real
  API in this project**; Agnes/OpenAI-compatible/Gemini are implemented against their documented
  request/response shape but untested live (no API keys available in this environment).
  Definition-of-Done check: `uv run pytest -q` and
  `uv run python -m rag_pipeline.generate --index <built index> --query "..." --provider ollama`.
- **Phase 7 (done); UI, eval, launcher.** Streamlit app (`src/rag_pipeline/ui/app.py`): sidebar
  (live-detected Ollama models, embed-model toggle, hybrid/rerank toggles, top-k, input folder)
  + Ingest/Query/Index status/Eval tabs. `src/rag_pipeline/eval/`: recall@k and citation-hit-rate
  metrics (pure, offline), optional judge-model faithfulness (`qwen3.5:2b`, off by default), CLI
  + Eval tab share `run_eval`. `run.cmd`: plain `venv`+`pip` (not `uv`; a separate self-contained
  path for a user without `uv`; `requirements.txt` is autogenerated from `uv.lock` via
  `uv export`, regenerate after `uv add`/`uv remove`), writes `.env.example` itself if missing
  (works around the same Write-tool restriction noted below), checks Ollama, starts Streamlit.
  Sample corpus (`data/raw/sample/`, 3 original short factual texts) + `data/eval/qa.jsonl` (4
  cases) let Query and Eval work after one real ingest; actually run against the project's real
  `data/` directories for the first time this phase, not just `/tmp`. Found and fixed a real
  cross-platform bug while doing that: ingest stored `source_path` with Windows backslashes,
  which silently failed to match a hand-written (forward-slash) `qa.jsonl`; fixed via
  `.as_posix()`. No UI/eval automated tests were added this phase (scope/time); verified via
  direct CLI runs and static syntax/type checks instead; this is a real gap, not a claim of full
  coverage.

Each phase changes only its own files and runs the checks it can without the full 1000-document
corpus before handoff.
