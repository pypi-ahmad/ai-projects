# Evaluation

Implemented in `src/rag_pipeline/eval/` (`metrics.py`, `judge.py`, `pipeline.py`, `cli.py`) and
the Streamlit UI's Eval tab. The current implementation uses `qa.jsonl` and metrics beyond the
earlier recall@5-only draft.

## Labeled set: `data/eval/qa.jsonl`

One JSON object per line:

```json
{"id": "q1", "question": "What gas do plants release as a byproduct of photosynthesis?", "relevant_sources": [{"source_path": "sample/photosynthesis.txt", "page": 1}], "gold_answer": "Oxygen."}
```

Fields (`eval/records.py`'s `EvalCase`):

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Any string, just an identifier for the report. |
| `question` | yes | The query to run through `run_retrieve`/`run_generate`. |
| `relevant_chunk_ids` | no | Exact Qdrant point IDs (`vector_store.point_id(doc_id, chunk_index)`). Precise but not hand-writable without already knowing the index. |
| `relevant_sources` | no | `[{"source_path": ..., "page": ...}]`; matched against a retrieved result's `source_path`/`page`. Human-writable without knowing chunk IDs in advance; use this for most hand-authored cases. |
| `gold_answer` | no | Not used by any metric today; kept for future citation-precision/answer-quality work, and for a human reading the report. |

A case needs at least one of `relevant_chunk_ids` / `relevant_sources` for recall@k to be
computable; without either, `recall_at_k` returns `None` for that case (excluded from the mean,
not counted as zero). `data/eval/qa.jsonl` ships with 4 real cases against the sample corpus.

## Metrics actually computed (`eval/metrics.py`, `eval/judge.py`)

| Metric | What it measures | Computed from |
|---|---|---|
| `recall_at_k` | Does *any* labeled-relevant chunk appear in the top-k `run_retrieve` returns? Boolean per case (1.0/0.0), not fractional-of-several-relevant-chunks. `None` if the case has no labeled relevant set. | `retrieve.pipeline.run_retrieve` |
| `citation_hit_rate` | Of the distinct `[Sn]` indices the model actually cited, what fraction are in-range (not hallucinated out-of-range)? `None` if the answer cited nothing. | The raw `answer_markdown`, regex-matched; see `docs/THREAT_NOTES.md`'s citation hallucination section for why this is a real signal, not a trivial always-1.0 metric. |
| `latency_ms` | Wall-clock time for one `run_generate` call (embed + retrieve + rerank + generation). | `generate.pipeline.run_generate`'s `latency_ms` |
| `faithfulness` | Optional: an LLM judge (default `qwen3.5:2b`, **off unless `--judge-model` is passed**) scores 0.0-1.0 whether the answer is supported by the retrieved context. | `eval/judge.py`'s `score_faithfulness` |

`nDCG@10` and a separate "citation precision" (fraction of citations that support their claim,
as originally sketched in an earlier draft of this doc) are **not implemented**; the closest
thing to the latter is the optional faithfulness judge, which scores the whole answer, not each
citation individually.

## Running it

CLI:

```
uv run python -m rag_pipeline.eval --index data/indexes --qa data/eval/qa.jsonl --k 5 [--judge-model qwen3.5:2b]
```

Or the **Eval** tab in the Streamlit UI (same `run_eval` function; the judge-model toggle there
maps to the same `--judge-model` flag, off by default).

**Real run against the sample corpus** (`--k 3`, no judge model): `recall@3 = 1.0`,
`citation hit rate = 1.0`, mean latency ≈ 2.1s/query (4 cases, `granite4.1:3b`, this machine).
These values come from a real run, not a target. The sample corpus is small and each question maps
to one clearly relevant document. A perfect score shows that the pipeline works end to end; it does
not validate retrieval quality at a realistic scale.

## What's not built

- No fixed target/threshold for any metric; that's a product decision once a real corpus and
  real query distribution exist, not something to invent against 3 sample documents.
- No breakdown by query type (exact-token vs. paraphrase) in the report itself, though
  `tests/test_retrieve.py` covers that distinction at the unit level.
- `nDCG@10` and per-citation faithfulness (as opposed to whole-answer faithfulness) are not
  implemented.
