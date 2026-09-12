# Self-Correcting RAG Agent — Spec

Agent loop around retrieval, not a new vector DB product. Native Windows 11, no WSL2, no Docker.

```
query rewrite -> retrieve -> critique -> retry or web fallback or abstain -> cited answer
```

Repairs retrieval misses instead of papering over them with uncited prose.

## Hardware budget

- RTX 4060 Laptop, 8 GB VRAM (confirmed via `nvidia-smi` on this machine).
- **One heavy Ollama model resident at a time** — unload embed before generate, generate
  before OCR (`self_correcting_rag.llm.vram.unload_all`).
- Qdrant index persists to disk (`data/indexes/qdrant`) so a restart never re-embeds.

## Allowed Ollama models

All 8 tags confirmed present via `ollama list` on this machine on 2026-09-12.

| Job | Model |
|---|---|
| Rewrite / critique JSON | `qwen3.5:0.8b` (default), `qwen3.5:2b` (fallback) |
| Final cited answer | `granite4.1:3b` |
| Embed query + chunks | `qwen3-embedding:0.6b` (default), `qwen3-embedding:4b` (fallback, VRAM headroom only) |
| OCR ingest (optional) | `AuditAid/PaddleOCR-VL-1.6-0.9B`, then unload; `qwen3-vl:2b` fallback for layout/captions |
| Web fallback query translation | `translategemma:4b`, only if non-English is added |

## LLM providers (all required, selectable)

| Provider | Model(s) | Config |
|---|---|---|
| Ollama (local) | detected installed models; default answer = `granite4.1:3b`, default critique = `qwen3.5:0.8b` | `OLLAMA_HOST` (default `http://127.0.0.1:11434`) |
| Agnes AI | `agnes-2.5-flash` (fixed) | `AGNESAI_API_KEY` (fixed base URL in code) |
| OpenAI-compatible | `gpt-5.6-luna`, `gpt-5.6-terra`, medium reasoning effort | `OPENAI_API_KEY`, `OPENAI_BASE_URL` |
| Google Gemini | `gemini-3.5-flash-lite`, `gemini-3.7-flash` | `GOOGLE_API_KEY` |

**Naming correction (verified live, not assumed):** the task brief said `AGNES_API_KEY`, but
the actual configured Windows user variable is `AGNESAI_API_KEY` (confirmed present via a
boolean-only env check; `AGNES_API_KEY` is unset). Code and `.env.example` use the real name.

`src/self_correcting_rag/config.py` is the single source of truth for the allowlists and env
var names — `Settings.available_providers()` reports which providers have their required env
vars set.

### `.env.example`

The Write tool (and a plain shell redirect) are blocked from creating `.env*` files by this
user's global Claude Code settings. `run.cmd` writes `.env.example` itself if missing, then
copies it to `.env` on first run. To create it by hand instead:

```
OLLAMA_HOST=http://127.0.0.1:11434
AGNESAI_API_KEY=
OPENAI_API_KEY=
OPENAI_BASE_URL=
GOOGLE_API_KEY=
SEARCH_API_KEY=
SEARCH_BASE_URL=
```

## Vector store: Qdrant embedded (local mode)

`QdrantClient(path="data/indexes/qdrant")` — no server, no Docker. Confirmed Windows-friendly
by a sibling project (`1-Production-RAG-Pipeline`) on this same machine. Dense vectors + full
payload in Qdrant; hybrid = dense (Qdrant) + lexical BM25 (a separate persisted index, e.g.
`bm25s`), fused client-side with Reciprocal Rank Fusion (RRF) over each list's rank, not raw
scores (cosine similarity and BM25 weight are on incompatible scales). This is the same
decision that sibling project's Phase 4 settled on after evaluating Qdrant sparse vectors in
one collection vs. a separate lexical store — reused here as a design pattern, not imported
code (self-contained implementation, built fresh in this repo).

## Web search fallback

Plug-in, not a hardcoded scraper. `WebSearch` (`search(query, n) -> list[WebResult]`) and
`WebFetch` (`fetch(url) -> str`) are separate interfaces -- searching and fetching have
different trust and safety concerns, so one being fake/absent doesn't force the other to be.
`NullSearch` (always empty) is the safe default when `SEARCH_API_KEY` is unset;
`FileStubSearch` reads canned results from a JSON fixture for tests; `HttpSearch` is a real
implementation against Firecrawl's documented `POST /v2/search` (verified via Firecrawl's own
docs, not guessed) -- set `SEARCH_API_KEY` to a Firecrawl key and optionally `SEARCH_BASE_URL`
to use it. `HttpWebFetch` is the one safe fetcher every path shares: http(s)-only, blocks
private/loopback/link-local/reserved/multicast addresses and `localhost` (`web/safety.py`,
resolve-then-check -- see its own `ponytail:` note on the DNS-rebinding gap that leaves open),
timeout, byte cap, and a one-off request with no cookie jar. `config.Settings
.resolve_web_enabled()` force-disables web at startup (with a log line) whenever
`SEARCH_API_KEY` is missing, regardless of what was requested -- `agent/loop.py`'s `run()`
independently re-checks `policy.web_enabled` too, so a misbehaving critique or a caller
skipping the settings gate still can't force a live web call.

## Non-goals

Training, Docker Qdrant, unrestricted/undocumented web scraping, a new vector DB product.

## Phase plan

- **Phase 1 (done) — Scaffold, config, LLM providers, docs.** `uv`-managed project (Python
  3.13.15, `src/` layout, ruff+ty+pytest), `config.py` (provider/model allowlists + env-driven
  settings, runnable self-check), shared `Provider` protocol + `ProviderSpec` registry, 4
  concrete providers (Ollama native client; Agnes AI + generic OpenAI-compatible via the shared
  `openai` SDK client; Gemini via `google-genai`), VRAM discipline helper (`llm/vram.py`:
  `unload_all` via Ollama's `keep_alive=0` unload trick, confirmed against the `ollama-python`
  docs). This spec, README, `docs/{ARCHITECTURE,LOOP,CITATIONS,THREAT_NOTES}.md`, `.gitignore`,
  `requirements.txt` (generated via `uv export`, regenerate after `uv add`/`uv remove`), empty
  package dirs for every later stage (`ingest/`, `index/`, `retrieve/`, `agent/`, `web/`,
  `ui/` -- `llm/` already is the providers package, no separate `providers/` dir), `run.cmd`
  stub (config self-check only; full ingest/agent/UI wiring lands in later phases).
  Definition-of-Done check: `uv run python -m self_correcting_rag.config` and
  `uv run pytest -q`.
- **Phase 2 (done) — Ingest + hybrid index.** Minimum viable, not the full production
  pipeline: `ingest/` parses txt/md/pdf-text only (`--ocr` on the index CLI just notes scanned
  pages explicitly — OCR itself isn't wired in this phase) and chunks sentence-aware at
  512/64 tokens (chars/4 approximation, not the real embed tokenizer -- `ponytail:` marked in
  `ingest/chunker.py`, upgrade to the `tokenizers` package if chunk-boundary quality ever
  matters more than it does for this MVP). `index/` embeds with `qwen3-embedding:0.6b`
  (`ollama.Client.embed`, dimension read from the first vector rather than hardcoded), stores
  dense vectors in Qdrant local mode (`data/indexes/qdrant`) and a `bm25s` lexical sidecar
  (`data/indexes/bm25`) — same split-store decision as `1-Production-RAG-Pipeline`'s Phase 4,
  reused as a pattern, implemented fresh here. `retrieve/` fuses dense + BM25 top-50 each with
  RRF (`k=60`) into `retrieve(index_dir, query, k)` returning chunks with score/source/page.
  No rewrite, no rerank, no web — out of scope until the agent loop phase. `python -m
  self_correcting_rag.index` / `.retrieve` CLIs. 9 fake-wiki fixtures under
  `tests/fixtures/wiki/` (one holds the distinctive proper noun "Quillfeather" for a keyword
  test); a paraphrase test on the PTO policy file exercises dense-only recall with no lexical
  overlap. Both pass against live Ollama (skipped module-wide if unreachable). Found a real
  RRF-tie edge case in a 9-doc corpus (BM25's only nonzero hit tied in fused score with a
  dense-only false positive) -- fixed by asserting top-3 membership instead of a fragile exact
  rank-1, not by tuning the fusion weights. Definition-of-Done check: `uv run pytest -q`,
  `uv run ruff check .`, `uv run ty check src/`, and a live CLI run (`index` then `retrieve`)
  against a copy of the fixtures.
- **Phase 3 (done) — Rewrite + critique building blocks.** Not yet the wired iterating loop
  (that's the next phase) -- the typed contracts and single-call functions it will orchestrate.
  `agent/schemas.py`: `RewriteResult` (1-3 queries + rationale), `CritiqueResult` (grounded/
  coverage in [0,1], missing[], decision, rationale), `LoopPolicy` (mirrors `docs/LOOP.md`'s
  defaults), `AgentTrace`/`AgentStep` (a step list for later UI/debugging). `agent/json_llm.py`:
  `call_json()` validates a provider's response against a schema with exactly one repair call
  on bad JSON, no unbounded retry. `agent/rewrite.py` and `agent/critique.py` call it with
  `docs/THREAT_NOTES.md`-aligned prompts (`agent/prompts.py` explicitly tells the model every
  `[S#]` block is data, never instructions). Critique's `decision` is the model's
  recommendation only -- `agent/critique.py`'s `enforce_decision()` recomputes the legal
  decision in code from `docs/LOOP.md`'s table (grounded score, chunk presence, iterations
  left, `policy.web_enabled`) and overrides the model when it disagrees, appending why to the
  rationale. `python -m self_correcting_rag.agent --query "..."` runs rewrite against a live
  provider (default `ollama`/`qwen3.5:0.8b`); tests mock the provider entirely (a `FakeProvider`
  returning canned JSON), so the suite needs no live LLM. Definition-of-Done check:
  `uv run pytest -q` (20 tests, all mocked/pure), `uv run ruff check .`, `uv run ty check src/`,
  and one live CLI run confirming the schema holds against a real model's output.
- **Phase 4 (done) — Wired loop + web fallback + citation enforcement.** `agent/loop.py`'s
  `run()` orchestrates rewrite -> retrieve (original question + all rewrites,
  `retrieve.pipeline.retrieve_multi` RRF-merges the per-query hybrid results) -> critique ->
  branch, looping on `retry` with the critique's `missing[]` fed back into `rewrite()` as hints,
  bounded by `enforce_decision`'s own `iteration < max_iters` (Phase 3) -- `run()` adds a
  `RuntimeError` tripwire in case that invariant ever breaks. Every stage (`rewrite_fn`,
  `retrieve_fn`, `critique_fn`, `generate_fn`) is dependency-injected so tests fake them
  directly, no live provider or index needed. `web/`: `WebSearch` protocol + `WebHit`,
  `StaticWebStub` (in-memory, no network), `fetch_web_chunks()` (dedups by URL, timeout/size
  cap enforced by the adapter, one bad fetch doesn't fail the run) -- **no concrete live search
  provider yet** (still deferred per the original Phase 4 note below); `run()` independently
  re-checks `policy.web_enabled` before ever calling the adapter, so a misbehaving critique
  can't force a web call. `agent/generate.py` produces free-text `[S#]`/`[W#]`-cited answers
  (not JSON); `agent/citations.py`'s `check_citations()` strips any tag referencing a chunk
  that was never supplied and reports it, and `LoopPolicy.citation_fail_closed` (default
  `False`) chooses between stripping-with-confidence-penalty and abstaining outright. Abstain
  returns the fixed `AgentResult{answer: null, reason, trace, ...}` shape in every abstain path
  (critique abstain, web disabled/unconfigured, web returned nothing, fail-closed citation).
  CLI corrected from the brief's `python -m src.agent` (not an importable path with this
  `src/`-layout project) to `python -m self_correcting_rag.agent --q "..."`, consistent with
  the `index`/`retrieve` CLIs. Definition-of-Done check: `uv run pytest -q` (29 tests: retry
  path taken with hints flowing through, web skipped when disabled with zero adapter calls,
  web fallback fetching and citing when enabled, illegal citation stripped with confidence
  lowered, abstain's fixed schema, plus focused `check_citations` unit tests), `uv run ruff
  check .`, `uv run ty check src/`, and one live end-to-end CLI run against the fixture corpus
  (correct `[S#]`-cited answer; the code-level decision override fired and is visible in the
  trace).
- **Phase 5 (done) — Concrete web search provider + fetch safety.** Split the combined Phase 4
  `WebSearch` (search+fetch in one) into `WebSearch`/`WebFetch` (see "Web search fallback"
  above for the full design) -- `NullSearch`, `FileStubSearch` (`tests/fixtures/web.json`), and
  `HttpSearch` (real, Firecrawl-backed, verified via Context7 against Firecrawl's docs, request
  construction unit-tested with `urlopen` mocked -- no live network call in the suite).
  `web/safety.py` + `HttpWebFetch` enforce the scheme allowlist, private/loopback/link-local
  block, timeout, byte cap, and no-cookie-jar rules. `Settings.resolve_web_enabled()` added to
  `config.py` for the startup force-disable-with-log-line behavior; `agent/loop.py` and
  `agent/__main__.py` (`--web` flag) updated for the split interfaces. Definition-of-Done
  check: `uv run pytest -q` (37 tests: localhost/loopback/link-local/disallowed-scheme blocked,
  a mocked public IP allowed, `FileStubSearch` driving the loop's web branch end to end,
  `NullSearch` degrading to a clean abstain, `HttpSearch`'s request/response shape, plus all
  prior-phase tests still green), `uv run ruff check .`, `uv run ty check src/`, and a live CLI
  run confirming the force-disable log line fires with no `.env` present.

  **Found live, not fixed (out of this phase's scope):** `qwen3.5:0.8b` occasionally emits
  malformed/truncated JSON on both `call_json`'s original *and* repair attempt (confirmed by
  reproducing with a direct `ollama.Client().chat()` call -- `done_reason: stop` on a retry of
  the identical prompt, so it's model sampling flakiness, not a deterministic length-limit bug
  in this code). `rewrite()`/`critique()` re-raise in that case and nothing in `run()` catches
  it, so the CLI crashes with a raw traceback instead of returning a clean abstain. Worth a
  small fix in whichever phase next touches `agent/loop.py`: catch the JSON/validation error
  around each stage call and abstain with a reason, rather than propagating it.
- **Phase 6 (done) — Streamlit UI, eval, seeded demo, launcher.** `ui/app.py`: sidebar (ingest
  folder path + re-index button, provider/model pickers, max-iters/confidence-threshold
  sliders, web-fallback toggle gated through `resolve_web_enabled` with an inline warning when
  forced off), a form-batched question box, the answer with citations, confidence + branch
  metrics, an expander with per-iteration rewrite queries / retrieved-chunk score table /
  full critique JSON, and a separate flat trace-timeline table. `agent/loop.py` gained
  `run_safe()` (catches any exception -- including Phase 5's noted `qwen3.5:0.8b` JSON
  flakiness -- into a clean abstain instead of a crash) and the retrieve trace step now
  carries per-chunk score/source/page, not just IDs, for the UI table. `eval/`: `qa.jsonl`
  loader, `run_eval()` (built on `run_safe`, so one bad live response can't abort the batch),
  and 3 pure metric functions (`citation_legality_rate`, `abstain_on_unknown_rate`,
  `no_web_when_disabled_rate`) unit-tested with synthetic data. `data/eval/qa.jsonl`: 6 cases
  against the fake wiki (3 `in_corpus`, 2 `out_of_corpus`, 1 `needs_rewrite`). `data/raw/wiki/`
  seeded with the same 9 fixture pages (`tests/fixtures/wiki/`) so a fresh clone has a working
  demo corpus without writing any first. `run.cmd` rewritten to the full plain-`venv`+`pip`
  launcher (matches `1-Production-RAG-Pipeline`'s pattern): creates `.venv`, installs from
  `requirements.txt` (regenerated via `uv export` -- was stale since Phase 1, missing
  `bm25s`/`pymupdf`/`qdrant-client`/`streamlit`), writes `.env.example`/`.env`, checks Ollama
  (required for the demo), auto-indexes the seeded wiki on first run if no index exists yet,
  then launches Streamlit. Definition-of-Done check: `uv run pytest -q` (45 tests), `uv run
  ruff check .`, `uv run ty check src/`, a live index + eval CLI run, and a live browser pass
  (Playwright) through the actual UI -- which caught and fixed a real bug: the "Rewrite /
  critique model" selector defaulted to index 0 (`granite4.1:3b`, the answer model) instead of
  the real rewrite/critique default (`qwen3.5:0.8b`); confirmed fixed by reloading and
  resubmitting live, watching a `[S1]`-cited answer render with confidence, branch, the
  expander's rewrite queries/retrieved-scores table/critique JSON, and the trace timeline all
  correct.

  **Live eval run against the seeded wiki (all 6 `qa.jsonl` cases):**
  `citation_legality_rate = 1.0`, `abstain_on_unknown_rate = 1.0`, `no_web_when_disabled_rate
  = 1.0` -- all 3 headline metrics perfect. But per-case: only 1 of 3 `in_corpus`/
  `needs_rewrite` questions that should have answered actually did (q1 answered; q2 "how many
  vacation days" and q6 the PTO paraphrase both abstained). A real retrieval/critique
  precision gap, not caught by any of the 3 requested metrics (they check legality/abstention/
  web-disabled, not recall on answerable questions) -- flagged, not fixed, since tuning
  retrieval or critique thresholds is a behavior change outside a docs/config phase's scope.
- **Phase 7 (done) — Docs/code parity, requirements pinning, launcher config.** `docs/LOOP.md`
  had drifted since Phase 1: it described a `{"confidence", "reason"}` critique schema that
  was never implemented (the real one is `{"grounded", "coverage", "missing", "decision",
  "rationale"}` -- Phase 3's `CritiqueResult`) and a decision table missing the
  chunks-retrieved condition `enforce_decision` actually checks; rewritten to match the code
  exactly, including the real (non-fixed-string) abstain reasons. `docs/CITATIONS.md` gained a
  section stating precisely what `check_citations` does and doesn't verify (tag legality only,
  never semantic support). `README.md` had the same schema drift plus a demo section (in-corpus
  answer vs. out-of-corpus abstain) and explicit "web fallback is best-effort and untrusted"
  language, also added to `docs/LOOP.md`. `requirements.txt` regenerated via `uv export`
  (already `==`-pinned by construction; confirmed current, no drift since Phase 6).
  `.streamlit/config.toml` added: `server.port = 7019`, `theme.base = "dark"` -- native config,
  no CSS. No application code changed (tests were green going in; "no new features unless
  tests fail" per this phase's instruction). Definition-of-Done check: `uv run pytest -q` (45
  tests, unchanged), a live server confirming port 7019 responds without any `--server.port`
  flag and a screenshot confirming the dark theme actually renders.

  **Found, not fixed (explicitly out of scope this phase):** the Phase 6 eval finding above,
  and Phase 5's `json_llm` robustness gap (`run_safe` catches it at the boundary; the root
  cause inside `run()` itself is still unpatched).

Each phase writes/updates only the files it owns and stops once its Definition-of-Done check
passes.
