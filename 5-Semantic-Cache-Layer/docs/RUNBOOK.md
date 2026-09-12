# Runbook

Operational notes for this repo. Phase 1: written ahead of the code that
would make these steps automatic — follow manually until then.

## Wipe the index after an embed-model change

`qwen3-embedding:0.6b` (1024-dim) and `qwen3-embedding:4b` (2560-dim)
vectors are not interchangeable — a Qdrant collection is fixed to one
vector size and distance metric for its lifetime (`docs/TECHNICAL.md`).
Switching which model produces the cache's vectors means:

1. Stop anything using the cache.
2. Delete the collection, or simplest on embedded Qdrant: delete the whole
   `data/cache/qdrant` directory (it will be recreated empty on next
   `QdrantClient(path=...)` startup).
3. There is no automatic re-embed/migration in this repo. Every previously
   cached query needs to be re-embedded with the new model and re-inserted
   before the cache is useful again — the cache starts cold. Re-populate
   with `python -m src.cache put --query ... --answer ... --namespace ...`
   per entry, or, for the demo namespace specifically, re-run
   `uv run python scripts/seed_demo.py` (`README.md`'s 30-second demo).
4. Confirm the new collection's `vectors_config.size` matches the new
   model's output dimension before writing anything back in — this
   happens automatically the first time `put()` runs against the wiped
   index (`IndexMeta` is recreated from the new model's actual output
   size, not hardcoded — `docs/TECHNICAL.md`).

This is enforced in code as of Phase 4: `SemanticCache.put`/`.get`
(`src/cache/service.py`) both call `ensure_embed_model_matches()` before
touching the vector index, raising `RebuildRequiredError`
(`.code == "REBUILD_REQUIRED"`) if the active embed model/dimension
doesn't match `data/cache/index_meta.json` — so a stale index refuses to
search or write instead of silently mixing incompatible vectors. (The
exact-match short-circuit is untouched by this — it's a payload lookup,
not a vector comparison, so it doesn't need the guard.) It does not run
the rebuild for you; steps 1–4 above are still manual.

## Ollama must be up for lookup

Every lookup embeds the incoming query first, so Ollama has to be running
and the target model pulled — there's no fallback path.

1. Check Ollama is running: `ollama list` (fails immediately if the daemon
   is down).
2. Confirm the embed model is present: it should appear in that list as
   `qwen3-embedding:0.6b` (or `:4b`). If not: `ollama pull qwen3-embedding:0.6b`.
3. Endpoint used: `http://localhost:11434/api/embed` (default Ollama host —
   `docs/TECHNICAL.md`).
4. A lookup with Ollama down fails fast: `src/embed/ollama_client.py`
   raises `OllamaEmbedError` on an unreachable host or a non-200 response,
   rather than hanging or silently returning a miss.

## Hardware discipline reminders

- **8 GB is enough for `qwen3-embedding:0.6b` + embedded Qdrant.** The
  embed model is ~640 MB on disk (Q8_0 quant); Qdrant embedded doesn't use
  VRAM at all (CPU/disk-backed — `data/cache/qdrant/`). Full reasoning:
  `README.md`'s 4060 note.
- Set `keep_alive: 0` on the embed call (or right after a batch) to unload
  the embedding model when nothing else needs the VRAM — see the 4060 note
  in `README.md`.
- Don't load `granite4.1:3b` unless a debug path is explicitly invoked.
- **Do not colocate `AuditAid/PaddleOCR-VL-1.6-0.9B`.** Run OCR workloads
  in a separate session from this repo's Ollama usage — see the 4060 note
  in `README.md` for why (vision-encoding VRAM cost isn't predictable from
  disk size the way a text-only embed model's is).

## Changing policy (`config/cache.yaml`)

Policy (`docs/CACHE_POLICY.md`) is read fresh by each `SemanticCache()`
construction — a CLI invocation always picks up the current
`config/cache.yaml`, no restart-a-server step needed. Two things to know:

- Tightening `never_cache_regexes` or `min_answer_chars` only affects
  future `put()`s — it does not retroactively scan or evict what's
  already stored.
- `threshold` changes take effect on the next `get()` immediately; no
  index rebuild is needed (unlike an embed-model change above) since it's
  a comparison cutoff, not a property of the stored vectors.

**The Streamlit UI is the exception.** `src/ui/app.py` builds one
`SemanticCache` via `@st.cache_resource` and keeps it for the life of the
server process, so `config/cache.yaml` is only read once, at first load.
The sidebar's threshold slider and embed-model selector work around this
for those two settings specifically (they call the `score_threshold`/
`embed_model` property setters on the cached instance every rerun — see
`docs/TECHNICAL.md`), but a `ttl_seconds`/`max_entries`/`never_cache_regexes`
edit needs the Streamlit process restarted to take effect.

## Ollama check in `run.cmd`

`run.cmd` probes `http://localhost:11434/api/version` before doing
anything else and exits with a clear error (not a stack trace) if Ollama
isn't reachable — embeddings are required for everything this repo does,
so failing at the first step is cheaper than failing partway through venv
setup or mid-`put()`. Launching `src/ui/app.py` directly with `streamlit
run` (bypassing `run.cmd`) skips this check; a down Ollama then surfaces
as an in-UI `st.error` on the first lookup instead (`src/ui/app.py`
catches `OllamaEmbedError`).

## metrics.jsonl grows without bound

`data/cache/metrics.jsonl` is append-only — nothing rotates or trims it.
To reset metrics, stop anything using the cache and delete the file; it's
recreated on the next logged event. There's no retention/rotation policy
built yet.
