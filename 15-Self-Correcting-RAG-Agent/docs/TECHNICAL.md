# Technical notes

## Stack

- **Python 3.13** (`pyproject.toml: requires-python = ">=3.13"`), managed with `uv`
  (`uv.lock`; `[build-system]` uses `uv_build`).
- **Qdrant**, via `qdrant-client`, in **local/embedded mode**
  (`QdrantClient(path=...)` in `index/vector_store.py`) -- its own module docstring states
  the reason: "no server, no Docker."
- **`bm25s`** for the lexical (BM25) index. `index/lexical_store.py`'s module docstring gives
  the reason in the code itself: chosen over `rank_bm25` because that package hasn't been
  updated since Feb 2022 and has no built-in persistence, while `bm25s` is actively
  maintained, pure Python + numpy, and ships `save()`/`load()`.
- **`pydantic` / `pydantic-settings`** for typed records (`agent/schemas.py`,
  `ingest/records.py`, `retrieve/records.py`) and environment-backed config (`config.py`).
- **`pymupdf`** for PDF text extraction (`ingest/parsers.py`).
- **`ollama`, `openai`, `google-genai`** -- one client library per LLM provider family
  (`llm/*_provider.py`). `llm/openai_compat_client.py`'s module docstring explains why the
  `openai` package is reused for two of the four providers: Agnes AI documents itself as an
  OpenAI-compatible Chat Completions endpoint, so one client serves both it and the generic
  "openai_compatible" provider.
- **`streamlit`** for the UI (`ui/app.py`), configured via `.streamlit/config.toml`.
- **Standard library only** for the web-fetch safety path: `web/safety.py` and
  `web/http_fetch.py` use `urllib.request`, `socket`, and `ipaddress`, not `requests` or
  `httpx` -- confirmed absent from `pyproject.toml`'s `dependencies`, even though both are
  present transitively (pulled in by `openai`/`google-genai`/`qdrant-client`).

## Invariants

- **The retrieval loop is bounded.** `agent/loop.py:run()` never iterates past
  `LoopPolicy.max_iters`; `agent/critique.py:enforce_decision()` only returns `"retry"` while
  `iteration < max_iters`. `run()` raises `RuntimeError("agent loop exceeded max_iters...")`
  if that invariant is ever violated -- a defensive check, not an expected code path.
- **The critique model's `decision` is advisory, not authoritative.**
  `enforce_decision()` recomputes the real decision from `grounded`, `confidence_threshold`,
  whether any chunk was retrieved, iterations remaining, and `web_enabled`, and overrides the
  model's proposed decision whenever they disagree (appending why to `rationale`).
- **A citation is legal only if its index number was actually supplied.**
  `agent/citations.py:check_citations()` checks every `[S#]`/`[W#]` tag against `n_source`/
  `n_web`; anything else is stripped by default, or the whole answer is replaced with an
  abstain if `LoopPolicy.citation_fail_closed = True`. This checks the tag's *number* only --
  it cannot and does not verify that a claim is semantically supported by the chunk its tag
  points to (see `docs/CITATIONS.md`).
- **Web fallback needs both a configured key and both adapters wired in.**
  `config.py:Settings.resolve_web_enabled()` forces `web_enabled = False` at startup if
  `SEARCH_API_KEY` is unset, regardless of what was requested. `agent/loop.py:run()`
  separately re-checks `policy.web_enabled and web_search is not None and web_fetch is not
  None` before calling out, so a faked or misbehaving critique step cannot force a live web
  call by itself.
- **At most one Ollama model is assumed resident.** `llm/vram.py:unload_all()` evicts every
  currently loaded Ollama model (via the documented `keep_alive=0` unload trick) and is called
  after embedding, in both `index/pipeline.py` and `retrieve/pipeline.py`.

## Error handling

- A provider that can't be constructed (missing API key) raises
  `llm/base.py:ProviderConfigError`. `agent`'s and `eval`'s `__main__.py` both catch this
  specifically at the top level and exit via `SystemExit(f"error: {e}")` instead of a raw
  traceback. `index`'s CLI has no such handling -- it calls `ollama.Client()` directly
  (`index/pipeline.py`), not through the `llm/` provider abstraction, so this exception type
  does not apply there.
- `agent/json_llm.py:call_json()` makes exactly one repair attempt when a provider's JSON
  response fails to parse/validate, then lets a second failure raise
  (`pydantic.ValidationError`). `agent/loop.py:run()` does **not** catch this; only
  `run_safe()` does, turning it into `AgentResult(answer=None, reason="internal error: ...")`.
  This is a known, documented gap (see `SPEC.md`), not an oversight this doc is unaware of.
- `web/fetch.py:fetch_web_chunks()` catches any exception per search query and per fetch URL
  individually and logs a `warning` -- one bad web result does not abort the others or the run.
- `web/safety.py:assert_safe_url()` raises `UnsafeUrlError` for a disallowed scheme, an
  unresolvable hostname, or a hostname/resolved IP that is `localhost`, private, loopback,
  link-local, reserved, or multicast. `web/http_fetch.py:HttpWebFetch.fetch()` calls this
  before every request; `web/fetch.py` catches the resulting exception as above rather than
  letting it propagate.
- `ingest/parsers.py:parse_file()` raises `ValueError("unsupported extension: ...")` for a
  file extension it doesn't handle. `ingest/pipeline.py` only ever calls it with paths already
  filtered by `discover_files()` to `.txt`/`.md`/`.pdf`, so this should not trigger through the
  `index` CLI in normal use.

## Persistence paths

- `data/indexes/qdrant/` -- Qdrant's local-mode storage, one collection, `chunks`
  (`index/vector_store.py:COLLECTION_NAME`).
- `data/indexes/bm25/` -- `bm25s`'s saved index files (`index/lexical_store.py:BM25_DIRNAME`).
  Rebuilt from scratch on every `index` run, not incrementally (the module docstring notes
  this is a deliberate simplification, cheap because building is pure numpy with no model
  calls).
- `data/raw/wiki/` -- the seeded demo corpus (9 Markdown files); the default `--input` for
  `self_correcting_rag.index` is `data/raw` (not `data/raw/wiki` specifically -- the README's
  quick-start command passes `--input data/raw/wiki` explicitly).
- `data/eval/qa.jsonl` -- the eval case set, one JSON object per line
  (`eval/pipeline.py:load_cases()`).
- Nothing else is written to disk by this code. `.env`/`.env.example` are process-level
  config, not application state, and are not present in this working tree (see README).
