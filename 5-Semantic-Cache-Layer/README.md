# Semantic Cache Layer

This is an embedding-similarity cache for LLM query and answer pairs. It runs
natively on Windows 11, with no WSL2 or Docker. Embeddings run locally through Ollama on an
RTX 4060 (8 GB), while Qdrant runs in process rather than as a server.

> Phase 6 is implemented and verified against live Ollama and embedded Qdrant,
> including the Streamlit UI and the generate-on-miss demo providers.

## Requirements

- Python 3.14 (`.venv/pyvenv.cfg` records `3.14.7`); not pinned by any
  `pyproject.toml`/`.python-version` in this repo; `uv venv` built it
  against whatever `Python314` install was on `PATH`.
- Ollama running locally with `qwen3-embedding:0.6b` pulled; required for
  every lookup (`docs/RUNBOOK.md`).
- Python deps pinned in [`requirements.txt`](requirements.txt): pydantic,
  pytest, qdrant-client, pyyaml, streamlit, pandas, python-dotenv.
- Native Windows 11. No WSL2, no Docker; `run.cmd` is the only launcher.

## Repo map

| Path | Contains |
|---|---|
| `src/cache/` | `SemanticCache` service (`service.py`), Pydantic records (`models.py`), `normalize.py`, dev CLI (`__main__.py`) |
| `src/store/` | Qdrant wrapper (`qdrant_store.py`), index-metadata guard (`index_meta.py`) |
| `src/embed/` | Ollama embedding client (`ollama_client.py`) |
| `src/policy/` | Policy config loader (`config.py`) and enforcement (`enforcement.py`) for `config/cache.yaml` |
| `src/metrics/` | Event logger (`logger.py`), hit-rate aggregator (`aggregator.py`), CLI (`__main__.py`) |
| `src/providers/` | Optional generate-on-miss demo providers (`generate.py`) |
| `src/ui/` | Streamlit app (`app.py`) |
| `config/cache.yaml` | Policy config (threshold, TTL, eviction, rejection rules) |
| `data/` | Qdrant embedded storage + `metrics.jsonl` (created at runtime, not checked in) |
| `scripts/seed_demo.py` | Seeds the `demo` namespace for the 30-second demo |
| `docs/` | `ARCHITECTURE.md`, `TECHNICAL.md`, `RUNBOOK.md`, `CACHE_POLICY.md`, `METRICS.md` |
| `tests/` | One test module per `src` component |

## Hits vs. misses

This is a *semantic* cache rather than an exact-key cache:

1. Normalize the incoming query text.
2. Embed it with the configured Ollama embedding model.
3. Nearest-neighbor search the embedding against previously cached queries
   stored in Qdrant.
4. If the best match's similarity score is **≥ threshold** → **hit**: return
   the stored answer, bump `hit_count`.
5. Otherwise → **miss**: return a miss. The caller generates an
   answer and is responsible for storing the new
   query/answer pair back into the cache.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the diagram and
[`docs/TECHNICAL.md`](docs/TECHNICAL.md) for dimensions, distance metric,
and threshold units.

## Embed model

| Job | Model |
|---|---|
| Default query + cached-key embeddings | `qwen3-embedding:0.6b` |
| Higher-quality embed (cache rebuild) | `qwen3-embedding:4b` |

Both are pulled via Ollama (`ollama pull qwen3-embedding:0.6b`). Only one
embedding model's vectors live in the Qdrant collection at a time; see
**Changing the embed model** below.

## Qdrant path

Embedded (no server, no Docker):

```python
from qdrant_client import QdrantClient
client = QdrantClient(path="data/cache/qdrant")
```

## 30-second demo

```
uv run python scripts/seed_demo.py
run.cmd
```

`run.cmd` checks that Ollama is reachable, creates
`.venv`/installs dependencies if needed, copies `.env.example` to `.env`
on first run, and launches the Streamlit UI in your browser.

In the UI (namespace defaults to `demo`, matching the seed):

1. Type **"How can I reset my password?"** and click **Lookup** →
   **Hit** (semantic match against the seeded "How do I reset my
   password?" FAQ, score ≈0.94).
2. Type something unrelated, e.g. **"What's the airspeed velocity of an
   unladen swallow?"** → **Miss**. Optionally pick a provider and click
   **Generate and store** to fill the cache live (demo only;
   `docs/ARCHITECTURE.md`).
3. Scroll down for the last 50 metric events and hit rate for the
   namespace (`data/cache/metrics.jsonl`), and buttons to clear the
   namespace or export the metrics log.

Not every paraphrase clears the default 0.89 threshold with
`qwen3-embedding:0.6b`; see the threshold section in
[`docs/TECHNICAL.md`](docs/TECHNICAL.md) for real measured scores across
several paraphrasings of the seeded FAQs.

## Run

```
run.cmd
```

Or the CLI:

```
python -m src.cache put --query "What is the capital of France?" --answer "Paris" --namespace demo
python -m src.cache get --query "What's the capital city of France?" --namespace demo
```

`get` prints `{"hit": true, "type": "exact"|"semantic", "answer", "score", "matched_query"}`
on a hit, or `{"hit": false, "top1_score": <score or null>}` on a miss.
`put` prints `{"rejected": true, "reason": "..."}` (exit code 1) if
`config/cache.yaml` policy refuses the answer; see
[`docs/CACHE_POLICY.md`](docs/CACHE_POLICY.md). Requires Ollama running
(`docs/RUNBOOK.md`).

Hit rate and per-call latency: every `put()`/`get()` is logged to
`data/cache/metrics.jsonl`.

```
python -m src.metrics --hours 24
```

See [`docs/METRICS.md`](docs/METRICS.md).

## 4060 note (8 GB VRAM)

- **8 GB is enough for `qwen3-embedding:0.6b` + embedded Qdrant, with
  headroom.** The embed model is ~640 MB on disk (Q8_0 quant, per `ollama
  list`); the only real VRAM cost on this repo's hot path. Qdrant itself
  doesn't touch VRAM at all: embedded mode is CPU/disk-backed
  (`data/cache/qdrant/collection/semantic_cache/storage.sqlite`).
- Unload the embedding model when idle if anything else needs to load
  (Ollama `keep_alive: 0` on the `/api/embed` call, or right after a batch
  embed run).
- Never load `granite4.1:3b` unless a debug path is explicitly invoked.
  it's a generate-on-miss demo model, not part of the cache's hot path.
- **Do not colocate `AuditAid/PaddleOCR-VL-1.6-0.9B`.** It's a
  vision-language OCR model (~1.8 GB on disk) for a different workload.
  image encoding needs buffers a text embedding call never does, so
  running OCR sessions alongside this cache risks VRAM pressure that
  doesn't show up from disk size alone. Keep OCR work in a separate
  session, not layered onto this repo's Ollama usage.
- One model loaded at a time is the working assumption on 8 GB; don't plan
  around running the embed model and a generation model concurrently.

## Changing the embed model requires a wipe and rebuild

`qwen3-embedding:0.6b` (1024-dim) and `qwen3-embedding:4b` (2560-dim)
produce vectors of different sizes and are not comparable. A Qdrant
collection is fixed to one vector size and one distance metric for its
lifetime. Switching the embed model means:

1. Delete or recreate the collection at `data/cache/qdrant` (see
   [`docs/RUNBOOK.md`](docs/RUNBOOK.md)).
2. Re-embed and re-populate every cached query with the new model before
   the cache is useful again; there is no online migration.

## Generate-on-miss demo providers (`src/providers`)

Optional providers are wired into the UI's "Generate and store" button on a miss.
They are outside this repo's core job (`NOTES.md`). Each provider uses one stdlib
`urllib` call (verified against each provider's own docs):

| Provider | Models | Needs |
|---|---|---|
| Ollama | `qwen3.5:0.8b`, `qwen3.5:2b` | Ollama running locally, nothing else |
| Agnes AI | `agnes-2.5-flash` | `AGNESAI_API_KEY` env var |
| OpenAI-compatible | `gpt-5.6-luna`, `gpt-5.6-terra` | `OPENAI_API_KEY` + `OPENAI_BASE_URL` env vars |
| Gemini | `gemini-3.5-flash-lite`, `gemini-3.7-flash` | `GOOGLE_API_KEY` env var |

A missing key appears as a clear in-UI error instead of a crash.
`granite4.1:3b` is deliberately not offered here; see the 4060 note
above.

## Known limitations

- `data/cache/metrics.jsonl` grows without bound; append-only, no
  rotation/retention (`docs/RUNBOOK.md`).
- Switching the embed model requires a full manual wipe and re-embed;
  there is no online migration (`docs/RUNBOOK.md`, `docs/TECHNICAL.md`).
- Only one embed model's vectors can live in the Qdrant collection at a
  time.
- The Streamlit UI reads `config/cache.yaml` once at process start
  (`@st.cache_resource`); only the threshold and embed model are
  adjustable live from the sidebar; a `ttl_seconds`/`max_entries`/
  `never_cache_regexes` change needs a process restart (`docs/RUNBOOK.md`).
- `keep_alive` idle-unload is part of the documented Ollama contract but
  is not yet implemented in `src/embed/ollama_client.py` (`docs/TECHNICAL.md`).
- No `docs/CONTRIBUTING.md`: this is a solo, local project (not a git
  repository, no CI) with no external-contributor workflow to document.

## Non-goals

Full RAG, an LLM-judge harness, Docker.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
