# Runbook

Instructions for running this pipeline on Windows 11.

## Click-path (Windows 11): double-click `run.cmd`

1. Double-click `run.cmd` in File Explorer (or run it from a terminal: `run.cmd`).
2. First run: it creates `.venv` (plain `venv`, not `uv`; see note below), then
   `pip install -r requirements.txt` into it. This step downloads ~1-2 GB (Streamlit, torch-free
   ML deps) and takes a few minutes the first time; later runs skip it if `.venv` already exists.
3. If `.env.example` doesn't exist yet, `run.cmd` writes it itself (it can't be created any other
   way in this project; see `SPEC.md`'s `.env.example` note). If `.env` doesn't exist, it's
   copied from `.env.example`. **Edit `.env` now** to add whichever provider keys you plan to use
   (Ollama needs none); `run.cmd` doesn't pause for this, so add keys before or restart after.
4. It checks Ollama is reachable (`ollama list`) and prints a warning (not a hard failure) if
   not; the UI still opens, but the Ollama provider, embedding, OCR, and reranking won't work
   until Ollama is running and the models are pulled (see "Pulling the allowed Ollama models"
   below).
5. It starts Streamlit (`python -m streamlit run src\rag_pipeline\ui\app.py`), which opens your
   browser to `http://localhost:8501`. Closing the terminal window stops the app.
6. In the UI: set your provider/model in the sidebar, use the **Ingest** tab to point at a folder
   (e.g. `data/raw`, which already has a small sample corpus under `data/raw/sample/`) and run
   ingest → chunk → index, then use the **Query** tab to ask a question. **Index status** shows
   what's currently indexed; **Eval** runs `data/eval/qa.jsonl` against it.

`run.cmd` uses plain `pip` and `venv`; the other commands use `uv run` against the canonical
`uv`-managed development environment (`pyproject.toml` and `uv.lock`). It provides a separate
self-contained path for someone without `uv`, creating `.venv` with the standard-library `venv`
and installing from `requirements.txt`. That file is generated from `uv.lock` with
`uv export --no-hashes --no-dev --format requirements-txt`. Regenerate it after `uv add` or
`uv remove` so the launcher stays aligned with the development environment.

## Setup (Windows 11); the `uv`-based dev path

1. Install Ollama: https://ollama.com/download (Windows installer). Confirm it's running:
   ```
   ollama --version
   ```
2. Install `uv`: https://docs.astral.sh/uv/getting-started/installation/
3. From the project root, sync dependencies:
   ```
   uv sync --all-groups
   ```
4. Copy the env var list below into a `.env` file in the project root (Claude Code cannot create
   this file directly in this project; see `SPEC.md`'s `.env.example` note).

## Pulling the allowed Ollama models

```
ollama pull granite4.1:3b
ollama pull qwen3.5:2b
ollama pull qwen3.5:0.8b
ollama pull qwen3-vl:2b
ollama pull qwen3-embedding:0.6b
ollama pull qwen3-embedding:4b
ollama pull translategemma:4b
ollama pull AuditAid/PaddleOCR-VL-1.6-0.9B
```

Pull only the models you need. `granite4.1:3b`, `qwen3-embedding:0.6b`, and `qwen3.5:0.8b` cover
the default generate, embed, and rerank path. The others are fallbacks or support OCR and
translation when those stages run.

## Environment variables

| Variable | Required for | Notes |
|---|---|---|
| `OLLAMA_HOST` | Ollama provider | Optional; defaults to `http://127.0.0.1:11434` |
| `AGNES_API_KEY` | Agnes AI provider | Model (`agnes-2.5-flash`) and base URL are fixed in code |
| `OPENAI_API_KEY` | OpenAI-compatible provider |; |
| `OPENAI_BASE_URL` | OpenAI-compatible provider | Must point at an OpenAI-compatible endpoint |
| `GOOGLE_API_KEY` | Gemini provider |; |

`Settings.available_providers()` in `src/rag_pipeline/config.py` lists a provider only when all
of its required variables are set. Ollama needs no key and is always listed, but its service must
be running.

## Ingest

```
uv run python -m rag_pipeline.ingest --input data/raw --out data/processed
```

Walks `--input` for supported files (pdf, docx, txt, md, html, png, jpg, jpeg, tiff), writes one
JSONL record per file to `<out>/ingest.jsonl`. Re-running is incremental: a file whose content
hash hasn't changed is skipped (its previous record is kept as-is, not reparsed or re-OCR'd).

Flags:
- `--translate`; translate pages whose detected language differs from `--target-lang` (default
  `en`) via `translategemma:4b`. Off by default; costs an extra model load per differently-lang'd
  file.
- `--target-lang <code>`; target language code for `--translate` (default `en`).
- `-v` / `--verbose`; log each file as it's ingested or skipped.

Digital PDFs get per-page text via PyMuPDF; a page with under ~20 characters of extracted text is
treated as a scan and OCR'd instead (see `docs/TECHNICAL.md`'s "almost no text" heuristic).
Scanned pages and standalone images are OCR'd with `AuditAid/PaddleOCR-VL-1.6-0.9B`, falling back
automatically to `qwen3-vl:2b` if that call raises. **OCR runs through Ollama, not locally in this
process**; the ingest CLI itself needs no GPU, but Ollama needs the relevant model pulled (see
above) and enough VRAM headroom when a scan is actually encountered. See `docs/TECHNICAL.md`'s
"Ingest-specific VRAM note" for what happens when a batch mixes OCR and translation.

## Chunk

```
uv run python -m rag_pipeline.chunk --in data/processed --out data/processed/chunks.jsonl
```

Reads `<in>/ingest.jsonl` (the ingest step's output directory, not the file itself), writes one
JSONL record per chunk to `--out`. No GPU or Ollama call involved; chunking is pure Python, plus
one local tokenizer load (cached after first use; see `docs/TECHNICAL.md`'s "Token counting").
Incremental by source-file hash, mirroring ingest/index: a file whose content hash is unchanged
since the last chunk run reuses its existing chunks as-is rather than re-splitting.

Flags:
- `--target-tokens` (default 512) / `--overlap-tokens` (default 64); see `docs/TECHNICAL.md`'s
  "Chunking defaults" for what these mean and how overlap is built.

## Index

```
uv run python -m rag_pipeline.index --chunks data/processed/chunks.jsonl --index data/indexes
```

Embeds every chunk in `--chunks` via Ollama (default `qwen3-embedding:0.6b`) into a Qdrant
local-mode collection under `--index`, and rebuilds a separate `bm25s` lexical index over the
same chunk texts under `--index`. **Idempotent by chunk hash**: re-running with unchanged chunks
makes zero Ollama calls and reports `0 embedded`; only new or content-changed chunks are
re-embedded. The embed model is unloaded (once) only if anything was actually embedded.

Flags:
- `--embed-model` (`qwen3-embedding:0.6b` default, or `qwen3-embedding:4b`); switches the dense
  embedding model. **Not interchangeable on an existing index**: the two models produce different
  vector dimensions (1024 vs. 2560; see `docs/TECHNICAL.md`), so switching this flag on an
  already-populated `data/indexes/qdrant_db/` raises an error rather than corrupting it. To
  actually switch, delete `data/indexes/qdrant_db/` first and re-run.
- `-v` / `--verbose`; log embedding progress.

## Retrieve

```
uv run python -m rag_pipeline.retrieve --index data/indexes --query "your question" --k 5
```

Embeds the query with whatever model built the index (read from
`data/indexes/index_meta.json`; written by `index`; if it's missing, run `index` first), does
dense top-N and BM25 top-N search, fuses with RRF, reranks the fused top 20 with
`qwen3.5:0.8b`, and prints the top `--k` results as JSON (`text`, `score`, `source_path`, `page`,
`chunk_id`, `fusion_rank`, `rerank_score`). No answer generation; this is retrieval only.

Flags:
- `--k` (default 5); how many results to return.
- `--n` (default 50); how many candidates each of dense and BM25 retrieve before fusion.
- `--hybrid` / `--no-hybrid` (hybrid on by default); `--no-hybrid` skips BM25 and RRF entirely,
  ranking by dense similarity alone. Useful for comparing against the hybrid result.
- `--rerank` / `--no-rerank` (rerank on by default); `--no-rerank` skips the `qwen3.5:0.8b` call
  and returns the fused top-`k` directly (`rerank_score` will be `null`).

## Generate

```
uv run python -m rag_pipeline.generate --index data/indexes --query "your question" --provider ollama --model granite4.1:3b
```

Retrieves, builds a `[S1]`/`[S2]`-tagged context block, calls the selected provider, and prints
the answer followed by the full JSON result (`answer_markdown`, `citations`, `model`,
`latency_ms`, `retrieval_trace`; see README's "Answer generation and citations" for the shape).

Flags:
- `--provider` (`ollama` default, or `agnes` / `openai_compatible` / `gemini`).
- `--model`; defaults to the provider's default model; must be one of that provider's allowed
  models (`granite4.1:3b`/`qwen3.5:2b`/`qwen3.5:0.8b` for ollama; fixed `agnes-2.5-flash` for
  agnes; `gpt-5.6-luna`/`gpt-5.6-terra` for openai_compatible; `gemini-3.5-flash-lite`/
  `gemini-3.7-flash` for gemini).
- `--k` (default 5); chunks retrieved and passed as context.

A missing provider key (e.g. running `--provider agnes` without `AGNES_API_KEY` set) prints
`Provider configuration error: ...` to stderr and exits 1; no traceback. Only `ollama` needs no
key; the other three need their respective env vars from `docs/RUNBOOK.md`'s "Environment
variables" table.

## Eval

```
uv run python -m rag_pipeline.eval --index data/indexes --qa data/eval/qa.jsonl --k 5
```

Runs every case in `--qa` through retrieve + generate and reports recall@k, citation hit rate,
and mean latency (see `docs/EVAL.md` for exact definitions and the `qa.jsonl` schema). Add
`--judge-model qwen3.5:2b` to also score faithfulness (extra Ollama calls per case; off by
default). Same underlying `run_eval` function backs the Eval tab in the Streamlit UI.

## Common failures

### Out of memory (OOM) / VRAM exhausted

Symptom: Ollama errors on model load, or generation is extremely slow (falling back to CPU).
Cause: more than one heavy model resident at once, or a model too large for the 8GB budget.
Fix: confirm no other heavy Ollama model is loaded (`ollama ps`), stop it (`ollama stop
<model>`), and retry. Do not use the `qwen3-embedding:4b` or `qwen3.5:2b` fallbacks unless you've
confirmed VRAM headroom after the default model unloads (see `docs/TECHNICAL.md`).

### Ollama not running / not reachable

Symptom: `ConnectionError` from `ollama.Client`, or `run.cmd` prints "could not reach Ollama."
Fix: start the Ollama app/service (`ollama serve` if it's not already running as a service), and
confirm with `ollama list`. If it's running on a non-default host/port, set `OLLAMA_HOST` in
`.env` to match (default `http://127.0.0.1:11434`).

### Wrong embed dimension after switching `qwen3-embedding:0.6b` ↔ `4b`

Symptom: `RuntimeError` from `index`/`retrieve` naming a vector-size mismatch (e.g. "existing
collection 'chunks' has vector size 1024, but the configured embed model produces 2560-dim
vectors").
Cause: the two embed models produce different-sized vectors (1024 vs. 2560; see
`docs/TECHNICAL.md`'s "Embedding dimension"), and a Qdrant collection is created with one fixed
size. Switching `--embed-model` (CLI) or the sidebar's embed-model toggle (UI) without rebuilding
does not corrupt the collection; it raises this error instead.
Fix: delete `data/indexes/qdrant_db/` (the `bm25s` index under `data/indexes/bm25/` doesn't
depend on embed model and can stay) and re-run `index` with the new `--embed-model`. There is no
in-place migration.

### Model not pulled

Symptom: `model '<tag>' not found` (or similar) when the pipeline tries to call a model.
Fix: `ollama pull <tag>` using the exact tag from the list above; tags are case-sensitive and
some are only pullable from Ollama's community namespace (`AuditAid/...`), not the official
library.

### Locked index

Symptom: an error opening the Qdrant local-mode store at `data/indexes/qdrant_db/`, mentioning a
lock file or "already in use".
Cause: Qdrant's embedded mode holds an OS-level file lock while a process has the store open.
Two processes (e.g., a Streamlit session left running, plus a script) cannot open it at once.
Fix: close the other process holding the store open (check for a lingering `streamlit` or
`python` process), then retry.
