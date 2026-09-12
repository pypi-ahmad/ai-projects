# Agent memory system

Working, episodic, and semantic memory for an AI agent, implemented as a
local Python library plus a Streamlit inspector. The library is not an
agent runtime: nothing in it observes, decides, or acts on its own. A
caller writes turns into working memory and episodic memory, calls
`Orchestrator.tick()` to run eviction, compression, and distillation, and
calls `recall()` to get a token-budgeted view back. Persistence is local
files (a SQLite database, an embedded Qdrant directory, a JSON snapshot)
plus calls to a locally running Ollama server for embeddings and
summarization.

## Requirements

- Python >= 3.13 (`pyproject.toml`, `.python-version`)
- [uv](https://docs.astral.sh/uv/) for dependency management and running commands
- [Ollama](https://ollama.com) running locally (`ollama serve`), with the models listed under "Configuration" pulled
- Windows: the only provided launcher (`run.cmd`) is a Windows batch script; there is no `.sh` equivalent in the repo. The Python code itself uses cross-platform stdlib/library calls (`pathlib`, `sqlite3`), so it may run elsewhere, but that is unverified; nothing in this repo shows it having been run on another OS.

Runtime dependencies (`pyproject.toml`; exact versions pinned in `uv.lock` and `requirements.txt`):

| Package | Version |
|---|---|
| streamlit | 1.63.0 |
| pydantic | 2.13.5 |
| qdrant-client | 1.19.0 |
| ollama | 0.6.2 |
| tiktoken | 0.14.0 |
| pyyaml | 6.0.3 |

Dev-only dependency: `pytest` 9.1.1.

## Setup and run

```
uv sync
```

Installs the pinned dependencies into `.venv`.

Start the Streamlit inspector:

```
run.cmd
```

`run.cmd` runs `uv sync` then `uv run streamlit run src\memory\ui.py`. The
app listens per `.streamlit/config.toml`: port 7013, dark theme.

Other entry points that exist in the repo and were run to confirm they work:

```
uv run python -m memory.working --demo
uv run python -m memory.semantic put "some fact text" --namespace global
uv run python -m memory.semantic search "some query" --namespace global
uv run python scripts/seed_demo.py
uv run python scripts/seed_demo.py --recall-only
```

Only `working.py` and `semantic.py` under `src/memory/` define a
`__main__` entry point (checked with `grep -l '__main__' src/memory/*.py`).
`episodic.py`, `compress.py`, `orchestrator.py`, `recall.py`, and
`providers.py` have no CLI of their own; they are used through
`orchestrator.py`, `ui.py`, or `scripts/seed_demo.py`.

`scripts/seed_demo.py` seeds session `"demo"` with a 12-turn scripted
conversation, forces working-memory overflow, distills facts, and runs
`recall()`. `--recall-only` skips seeding and recalls against whatever is
already on disk; this is how persistence across a process restart was
checked (both commands above were run as two separate processes; the
second found the same planted fact the first wrote).

## Configuration

There is no `.env` or `.env.example` file in this repository.
Configuration is Python constants plus one YAML file:

- `src/memory/config.py`; paths under `data/memory/`, the allowed Ollama
  model names, and non-Ollama provider settings.
- `config/memory.yaml`; loaded by
  `src/memory/orchestrator.py:load_memory_config()`. A missing file, or
  missing keys within it, fall back to the defaults on the `MemoryConfig`
  class in `orchestrator.py`.

Environment variables actually read by the code
(`src/memory/config.py:available_providers()`): `AGNESAI_API_KEY`,
`OPENAI_API_KEY`, `GOOGLE_API_KEY`. These are only checked for presence
(booleans); nothing in the current code calls Agnes AI, an
OpenAI-compatible endpoint, or Gemini. `src/memory/providers.py`, the
module that would do that, is a docstring-only stub with no
implementation.

Ollama models listed in `config.py` (`ALLOWED_OLLAMA_MODELS`):
`granite4.1:3b`, `qwen3.5:2b`, `qwen3.5:0.8b`, `qwen3-vl:2b`,
`qwen3-embedding:0.6b`, `qwen3-embedding:4b`, `translategemma:4b`,
`AuditAid/PaddleOCR-VL-1.6-0.9B`. Of these, the code actually calls two:
`qwen3-embedding:0.6b` for embeddings (`semantic.py`) and `qwen3.5:0.8b`
for compression/distillation, including JSON repair (`compress.py`,
`config.COMPRESS_MODEL_DEFAULT`). `qwen3.5:2b`
(`config.COMPRESS_MODEL_FALLBACK`) and `granite4.1:3b`
(`config.DEBUG_CHAT_MODEL`) are defined as constants but not referenced by
any other code in `src/` (verified by grep).

`.streamlit/config.toml` sets `server.port = 7013` and
`theme.base = "dark"`.

## Repo map

```
src/memory/
  working.py        token-budgeted turn buffer (Pydantic WorkingItem, CompressJob)
  episodic.py       SQLite event log + FTS5 keyword search (Episode, EvictionPolicy)
  semantic.py        Qdrant-backed fact store + Ollama embeddings (Fact, FactMatch)
  compress.py         LLM summarization/distillation, with a non-LLM fallback
  orchestrator.py     MemoryConfig (reads config/memory.yaml), Orchestrator.tick()
  recall.py           packs working + episodic + semantic into one token budget
  ui.py               Streamlit app
  providers.py        stub -- no implementation
  config.py           paths, model name constants, env var presence checks
config/memory.yaml    tunable eviction/dedup thresholds
.streamlit/config.toml  Streamlit port + theme
scripts/seed_demo.py    scripted conversation + persistence check
tests/                  one pytest file per src module, plus test_recall.py, test_orchestrator.py
docs/                   ARCHITECTURE.md, TECHNICAL.md, RUNBOOK.md (this pass), plus
                        pre-existing SCHEMAS.md, POLICIES.md, EVAL.md, ENVIRONMENT.md (untouched)
data/memory/            runtime state: memory.db, qdrant/, working.json, index_meta.json
                        (gitignored except .gitkeep)
```

## Running tests

```
uv run pytest tests/
```

Confirmed: `30 passed` across 6 files. `test_semantic.py` and
`test_orchestrator.py` make real network calls to a local Ollama server
for embeddings; if Ollama is not running, those fail with a connection
error rather than an assertion failure. The LLM chat calls inside
`test_orchestrator.py` and `test_compress.py` are supplied via an
injectable `chat_fn` argument rather than a mocking library, so those
specific assertions do not depend on Ollama being up.

## Known limitations

Each of these is visible directly in the code or its comments, not
inferred:

- **No provider fallback, no GPU unload coordination.**
  `src/memory/providers.py` is an empty stub. `compress.py` and
  `semantic.py` both call Ollama directly with no `keep_alive`
  coordination between them.
- **`WorkingMemory` has no session concept.** It is one shared
  in-process buffer regardless of `session_id`; only episodic and
  semantic memory are scoped per session (`working.py`, `ui.py`).
- **`recall()` and `SemanticMemory.search()` do not filter invalidated
  facts.** `Fact.invalidated_at` is set by `invalidate()` but nothing
  reads it back out.
- **Semantic memory has no eviction**, only `invalidate()`; there is no
  cap on stored fact count.
- **Changing `config.EMBED_MODEL` requires a manual rebuild.**
  `SemanticMemory` raises `RebuildRequiredError` if
  `data/memory/index_meta.json`'s recorded model does not match the
  configured one; there is no automatic re-embedding path.
  `data/memory/qdrant/` and `index_meta.json` must be deleted and every
  fact re-upserted by hand.
- **No scheduler.** Something outside this repo has to call
  `Orchestrator.tick()`; nothing here calls it on a timer.

No CI configuration exists in this repository (no `.github/` directory).
`docs/CONTRIBUTING.md` was not written: no branch policy, review process,
or CI check is documented or configured anywhere in the tree to describe.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
