# Local RAG Pipeline

A local-first, hybrid-retrieval RAG pipeline for a single machine with an RTX 4060 (8GB VRAM).
Ingests mixed documents (pdf, docx, txt, md, html, scanned png/jpg), retrieves with dense +
lexical (BM25) search fused by RRF, reranks, and generates a cited answer through one of four
selectable LLM providers, served through a Streamlit UI.

All seven phases are implemented: ingest, chunk, index, retrieve, generate, the Streamlit UI,
evaluation, and a double-clickable launcher. See "Limitations" and `SPEC.md` for known gaps.

## Quick start

1. Install [Ollama](https://ollama.com/download) and make sure it's running (`ollama list`
   should work in a terminal).
2. Double-click `run.cmd` in this folder. First run creates a `.venv` and installs dependencies
   (a few minutes); it then opens `http://localhost:8501` in your browser.
3. In the sidebar, leave the defaults (provider `ollama`, model `granite4.1:3b`). Set
   **Input folder** to `data/raw`; it already contains a small sample corpus under
   `data/raw/sample/` (three short original texts on photosynthesis, ocean tides, and the water
   cycle).
4. Go to the **Ingest** tab and click **Run ingest -> chunk -> index**. The first run also pulls
   `qwen3-embedding:0.6b` if it isn't already pulled; see `docs/RUNBOOK.md` if that step fails.
5. Go to the **Query** tab, ask: *"What gas do plants release as a byproduct of
   photosynthesis?"*, and click **Ask**. The answer should end with a citation like `[S1]`, and
   the **Citations** list below it will show `[S1] sample/photosynthesis.txt, page 1`.

The same workflow is available from the CLI:

```
uv run python -m rag_pipeline.ingest --input data/raw --out data/processed
uv run python -m rag_pipeline.chunk --in data/processed --out data/processed/chunks.jsonl
uv run python -m rag_pipeline.index --chunks data/processed/chunks.jsonl --index data/indexes
uv run python -m rag_pipeline.generate --index data/indexes --provider ollama --query "What gas do plants release as a byproduct of photosynthesis?"
```

## Hardware notes

- Target GPU: NVIDIA RTX 4060, 8GB VRAM.
- Peak resident VRAM budget: **< 7GB**.
- **One heavy Ollama model resident at a time**; enforced for ingest and index (batch-end
  unload) and for a single query (retrieve unloads the embed model before the rerank model
  loads, and the rerank model after use; generate unloads the chat model after the answer comes
  back). Cost: every query pays a full reload for each model it touches, no warm-model reuse
  across consecutive queries; see `docs/TECHNICAL.md` for the trade-off.

## Allowed models and their job

Fixed allowlist; see `src/rag_pipeline/config.py` (source of truth) and `SPEC.md` for how each
tag was verified.

| Model | Job |
|---|---|
| `granite4.1:3b` | Answer generation (default) |
| `qwen3.5:2b` | Answer generation (fallback) |
| `qwen3.5:0.8b` | Answer generation (fallback) / pointwise rerank |
| `qwen3-vl:2b` | OCR layout & figure captions (fallback) |
| `qwen3-embedding:0.6b` | Dense embedding (default, 1024-dim) |
| `qwen3-embedding:4b` | Dense embedding (fallback, 2560-dim; not interchangeable with 0.6b on an existing index, see Troubleshooting) |
| `translategemma:4b` | Non-English ingest translation |
| `AuditAid/PaddleOCR-VL-1.6-0.9B` | OCR VLM recognition (paired with the `paddleocr` package's layout analysis) |

The allowlist has no dedicated reranker. Reranking prompts `qwen3.5:0.8b` with a scoring prompt,
processes candidates in batches, and narrows the top 20 to the top 5.

## Providers

Four LLM providers are supported, selectable in the sidebar.

| Provider | Model(s) | Requires |
|---|---|---|
| Ollama (local) | live-detected installed models; default `granite4.1:3b` | Ollama running locally, no API key |
| Agnes AI | `agnes-2.5-flash` (fixed) | `AGNES_API_KEY` |
| OpenAI-compatible | `gpt-5.6-luna`, `gpt-5.6-terra` | `OPENAI_API_KEY`, `OPENAI_BASE_URL` |
| Google Gemini | `gemini-3.5-flash-lite`, `gemini-3.7-flash` | `GOOGLE_API_KEY` |

Only Ollama has been run end to end against a real API in this project. See Limitations.

## Answer generation and citations

`rag_pipeline.generate` retrieves (`retrieve`), tags each retrieved chunk `[S1]`, `[S2]`, ...
with its source path and page, and instructs the model to answer only from those tagged sources,
cite every factual sentence, treat source text as data rather than instructions (see
`docs/THREAT_NOTES.md`), and say so if the sources are insufficient. Real example, from this
project's own sample corpus:

```markdown
Plants release oxygen as a byproduct of photosynthesis [S1].

Sources:
[S1] sample/photosynthesis.txt, page 1
```

The same call also returns this structured, so a UI doesn't have to re-parse the markdown:

```json
{
  "answer_markdown": "...",
  "citations": [
    {"index": 1, "chunk_id": "...", "source_path": "sample/photosynthesis.txt", "page": 1}
  ],
  "model": "granite4.1:3b",
  "latency_ms": 842.1,
  "retrieval_trace": [
    {"chunk_id": "...", "score": 0.033, "fusion_rank": 1, "rerank_score": 0.9,
     "source_path": "sample/photosynthesis.txt", "page": 1}
  ]
}
```

`citations` lists only the `[Sn]` tags the model actually used (deduplicated, in order); not
every chunk that was retrieved. `retrieval_trace` is the full retrieved set with its scores, for
observability, regardless of whether each one ended up cited.

## Running

Double-click `run.cmd`. Its click-path in `docs/RUNBOOK.md` explains each step. It creates its
own plain `venv` and runs `pip install`, separately from this repository's `uv`-managed
development environment. Both paths work; `run.cmd` does not require `uv`. For development, use
`uv run <command>` directly as described in `docs/RUNBOOK.md`.

## Troubleshooting

See `docs/RUNBOOK.md`'s "Common failures" for the full list; the three most likely to hit first:

- **8GB VRAM out-of-memory / everything falls back to CPU and is very slow.** Check no other
  heavy Ollama model is loaded (`ollama ps`), stop it (`ollama stop <model>`), retry. Don't
  switch to the `qwen3-embedding:4b` or `qwen3.5:2b` fallbacks unless you've confirmed headroom.
  They are opt-in, not a default upgrade.
- **Switched the embed model (`qwen3-embedding:0.6b` <-> `4b`) and now indexing/querying fails
  with a vector-size error.** The two models produce different-sized vectors (1024 vs. 2560) and
  are not interchangeable on an existing index. Delete `data/indexes/qdrant_db/` and re-run
  `index` with the new model; there is no in-place migration.
- **Ollama not running / not reachable.** `ollama.Client` raises a connection error, or `run.cmd`
  prints a warning and the app still opens but nothing that needs Ollama works. Start Ollama
  (`ollama serve`, or the desktop app), confirm with `ollama list`.

## Directory map

```
.
├── README.md
├── SPEC.md                 # full spec: hardware budget, verified model table, phase plan
├── run.cmd                 # launcher: plain venv + pip, writes .env.example, starts Streamlit
├── requirements.txt        # autogenerated from uv.lock (`uv export`) for run.cmd's pip install
├── pyproject.toml
├── docs/
│   ├── ARCHITECTURE.md     # ingest + request path (mermaid), design constraints
│   ├── TECHNICAL.md        # stack rationale, VRAM budget, index layout, chunking defaults
│   ├── RUNBOOK.md          # setup, click-path, Ollama pulls, env vars, common failures
│   ├── EVAL.md             # qa.jsonl schema, metrics actually computed
│   └── THREAT_NOTES.md     # prompt injection, OCR garbage, citation hallucination
├── data/
│   ├── raw/sample/         # 3 original short factual texts (the sample corpus)
│   ├── processed/          # parsed/OCR'd + chunked output (populated by one real ingest run)
│   ├── indexes/            # Qdrant local-mode store + separate bm25s index (gitignored)
│   └── eval/qa.jsonl       # 4 labeled eval cases against the sample corpus
└── src/rag_pipeline/
    ├── config.py           # env-driven settings + model/provider allowlists
    ├── ingest/             # parse/OCR/translate, JSONL output
    ├── chunk/              # sentence-aware recursive split, JSONL output
    ├── index/              # embed + Qdrant + bm25s, idempotent by hash
    ├── retrieve/           # dense+BM25, RRF fuse, pointwise rerank
    ├── generate/           # cited answers, 4 providers
    ├── eval/               # recall@k, citation hit rate, optional faithfulness
    └── ui/                 # Streamlit app.py
```

## Known gaps / limitations

- The **1000+ mixed-document corpus target is untested at scale**; everything has only been
  run against the 3-file sample corpus and small fixtures.
- `src/rag_pipeline/eval/metrics.py` now has offline unit tests (`tests/test_eval_metrics.py`).
  The Streamlit UI still has **no automated tests** (no `AppTest`-based smoke test was added).
  It was verified only by direct CLI runs and static syntax/type checks.
- Citation enforcement is prompt-based, not programmatically guaranteed; see
  `docs/THREAT_NOTES.md` for exactly what is and isn't covered (out-of-range citations are
  dropped in code; a valid-looking-but-unsupported citation is not caught at query time).
- Only Ollama has been run end-to-end against a real API. Agnes AI, the OpenAI-compatible
  provider, and Gemini are implemented against their documented request/response shapes but
  have zero live test coverage (no API keys available while building this).
- Citations in the Query tab are "clickable" in the sense of highlighting the matching chunk in
  the retrieved-chunks expander below (Streamlit has no true in-page anchor scroll); not a jump
  to an external file/page viewer. The Ingest tab's "logs" are step markers, not a live streamed
  log of every file.
- Chunk is now incremental by source-file hash too (like ingest and index). The `bm25s` lexical
  index is still always fully rebuilt every run (cheap, no model calls, and `bm25s` has no
  supported single-document incremental API); only the Qdrant embedding step and chunk splitting
  are incremental by hash.
- Ingest's OCR-fallback and translation models are only unloaded once per batch, not on every
  model switch (see `docs/TECHNICAL.md`'s "Ingest-specific VRAM note"). Retrieve/generate don't
  unload models between steps at all (see "Hardware notes" above).
- Single-GPU, local-only Ollama; no multi-GPU or cloud-vector-DB path (see `SPEC.md` non-goals).
- `AuditAid/PaddleOCR-VL-1.6-0.9B` is an unofficial community GGUF republish, not an official
  PaddlePaddle release; see `SPEC.md` for provenance and the integration mechanics.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
