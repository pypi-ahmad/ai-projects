# Self-Correcting RAG Agent

Retrieval-augmented question answering over a local document corpus, built as an agent loop
rather than a single retrieval call. Given a question, the system rewrites it, retrieves with
a hybrid dense+lexical search, critiques its own retrieval, and then either answers with
citations, retries with a rewritten query, falls back to a web search, or abstains; instead
of answering when the corpus doesn't support an answer. For example, against the seeded demo
corpus it answers "What VPN client is required for remote access?" (citing the source file)
but abstains on "What is the CEO's favorite color?" (not in the corpus).

## Requirements

- Python `>=3.13` (`pyproject.toml`). The project's own `.venv` in this working tree is
  `3.13.15` (`.venv/pyvenv.cfg`).
- [`uv`](https://docs.astral.sh/uv/) to use the `uv run`/`uv sync` commands below. `run.cmd`
  is an alternative that only needs a plain `python` on `PATH` (see below).
- [Ollama](https://ollama.com) reachable at `OLLAMA_HOST` (default `http://127.0.0.1:11434`)
  for the default (and only offline) provider. The exact model tags this project expects are
  listed in `config.py`'s `ALLOWED_OLLAMA_MODELS`: `granite4.1:3b`, `qwen3.5:2b`,
  `qwen3.5:0.8b`, `qwen3-vl:2b`, `qwen3-embedding:0.6b`, `qwen3-embedding:4b`,
  `translategemma:4b`, `AuditAid/PaddleOCR-VL-1.6-0.9B`. Whether each of these is actually
  used by code that runs today is noted in `docs/TECHNICAL.md`.
- `run.cmd` is a Windows batch file and has only been run on Windows in this repository; there
  is no `.sh` equivalent. The Python code itself does not call any Windows-only API that is
  visible in the source, but it is unverified on any other OS.

## Setup and run

Two ways to run this, both present in the repository:

**With `uv`:**
```
uv sync --all-groups
uv run python -m self_correcting_rag.index --input data/raw/wiki --index data/indexes
uv run streamlit run src/self_correcting_rag/ui/app.py
```

**With `run.cmd` (Windows, plain `venv` + `pip`):**
```
run.cmd
```
`run.cmd` creates `.venv`, installs `requirements.txt`, writes `.env.example` and copies it to
`.env` if neither exists yet, checks `ollama list`, builds the index from `data/raw/wiki` if
`data/indexes/qdrant` doesn't exist yet, then starts Streamlit. The app listens on
`http://localhost:7019` with a dark theme (`.streamlit/config.toml`).

Other verified entry points, all `python -m <module>` under `src/self_correcting_rag/`:

| Command | What it does |
|---|---|
| `self_correcting_rag.config` | Prints the resolved provider list and model allowlist (self-check, no arguments). |
| `self_correcting_rag.index --input <dir> --index <dir> [--ocr]` | Ingest, chunk, embed, and index a corpus. Defaults: `--input data/raw`, `--index data/indexes`. |
| `self_correcting_rag.retrieve --index <dir> --query "..." [--k N]` | Hybrid search only, no generation. `--query` is required; `--k` defaults to `5`. |
| `self_correcting_rag.agent --q "..." [--index <dir>] [--provider ollama\|agnes\|openai_compatible\|gemini] [--max-iters N] [--confidence-threshold F] [--web]` | Runs the full loop and prints an `AgentResult` as JSON. `--q` is required. |
| `self_correcting_rag.eval [--qa data/eval/qa.jsonl] [--index data/indexes] [--provider ollama\|...]` | Runs every case in the eval JSONL and prints per-case results plus 3 metrics. |

All of the above are run with `uv run python -m ...` if using `uv`, or
`.venv\Scripts\python.exe -m ...` if using `run.cmd`'s plain venv.

## Configuration

Settings are read from process environment variables through `pydantic-settings`
(`config.py: Settings`, `env_file=".env"`). No `.env` or `.env.example` file exists in this
working tree; `run.cmd` writes `.env.example` on first run (Write access to `.env*` files is
blocked for the assistant that built this repo, per a comment in `SPEC.md`; that restriction
does not apply to a normal shell). Variables the code reads:

| Variable | Used for | Default if unset |
|---|---|---|
| `OLLAMA_HOST` | Ollama provider base URL | `http://127.0.0.1:11434` |
| `AGNESAI_API_KEY` | Agnes AI provider | provider unavailable |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | Generic OpenAI-compatible provider (both required together) | provider unavailable |
| `GOOGLE_API_KEY` | Gemini provider | provider unavailable |
| `SEARCH_API_KEY`, `SEARCH_BASE_URL` | Web fallback (`HttpSearch`, targets Firecrawl's `/v2/search` shape) | web fallback force-disabled at startup, with a logged warning |

`.streamlit/config.toml` is the only other config file: it sets `server.port = 7019` and
`theme.base = "dark"` for the Streamlit app.

## Repo map

```
src/self_correcting_rag/
  config.py    settings (env vars) + the Ollama model / provider allowlists
  llm/         provider clients: ollama, agnes, openai-compatible, gemini + VRAM unload helper
  ingest/      file parsing (.txt/.md/.pdf-text only) and chunking
  index/       Qdrant (local mode) dense index + bm25s lexical index
  retrieve/    hybrid dense+lexical search and RRF fusion
  agent/       rewrite, critique, generate, citation check, and the orchestrating loop
  web/         web search/fetch interfaces, a Firecrawl-backed search client, safety checks
  eval/        eval-case loader, runner, and 3 metric functions
  ui/          the Streamlit app (single file, app.py)
data/
  raw/wiki/    seeded demo corpus, 9 Markdown files
  eval/qa.jsonl  6 eval questions
  indexes/     built Qdrant + bm25s index (gitignored, not present until you run index)
tests/         pytest suite; fixtures under tests/fixtures/
docs/          this documentation set
SPEC.md        design rationale and a phase-by-phase build history
```

## How to run tests

```
uv run pytest -q
uv run ruff check .
uv run ty check src/
```

`tests/test_retrieve.py` makes live calls to Ollama (embedding) and skips itself at module
level if Ollama isn't reachable. Every other test file uses fakes or mocks and makes no live
network or model calls.

## Known limitations

Everything below is drawn from code comments or a documented live observation, not inferred:

- Chunk sizing approximates token count as `len(text) // 4`; it does not use the real
  embedding model's tokenizer (`ingest/chunker.py`, commented `ponytail:`).
- Sentence splitting during chunking is a regex heuristic that misreads abbreviations and
  decimals as sentence boundaries (`ingest/chunker.py`).
- Scanned-PDF detection is a character-count heuristic with no layout analysis. Pages it
  flags as scans are skipped, not OCR'd; `AuditAid/PaddleOCR-VL-1.6-0.9B` is listed as an
  allowed model in `config.py` but is not called from anywhere in `ingest/` (verified: no
  reference to that model string outside `config.py`).
- The web-fetch safety check validates a URL's resolved IP and then connects separately; the
  code comments this as a known gap against DNS-rebinding (`web/safety.py`).
- `qwen3.5:0.8b` has been observed, during this project's development, to occasionally emit
  malformed JSON on both an LLM call and its one automatic repair attempt. `agent/loop.py`'s
  `run()` does not catch this; only its `run_safe()` wrapper does (used by the UI and the
  eval runner). Documented in `SPEC.md`.
- A recorded eval run (`SPEC.md`) found 2 of 3 in-corpus/needs-rewrite eval questions
  abstained rather than answered; a retrieval/critique precision issue the 3 implemented
  eval metrics do not measure.
- Confidence reported after a web-fallback answer reuses the critique score computed before
  the web fetch; there is no re-critique of the web-augmented context (`agent/loop.py`).
- `HttpSearch` targets Firecrawl's documented `/v2/search` request/response shape. Its request
  construction is unit-tested with the HTTP call mocked; it has not been exercised against a
  live key in this repository.

## Not included in this repository

- **`docs/CONTRIBUTING.md`**: omitted. This working tree has no `.git` directory and no CI
  configuration (checked: no `.github/`, no other CI file), so there is no branch policy or
  CI-driven test gate to document. The test/lint/type-check commands that do exist are listed
  above.

See `SPEC.md` for the full phase-by-phase build history and the reasoning behind each design
decision.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
