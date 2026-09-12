# ADE — Agentic Document Extraction

A LangGraph pipeline that reads a document with a vision LLM and produces a
layout-aware Markdown + HTML reading of it (`data/parse/`) plus an annotated
PDF, and one PNG per page, showing where each parsed block was found
(`data/annotated/`) — reference artifacts for a human to read alongside the
source.

It was originally built around an invoice-extraction contract instead: the
model *proposes* an `Invoice`, Python *validates* the arithmetic, and only a
passing (or human-overridden) result gets committed. That contract doesn't
fit real prior-auth documents, which have no subtotal/grand-total for Python
to check, so the extract → validate → crop → commit/review half of the graph
is currently **unwired** — implemented and tested, but not reachable from the
active graph or UI. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for
exactly what's active versus dormant.

## What this is not

- **Not LandingAI ADE.** No relation to LandingAI's product of the same
  name, and no dependency on it.
- **Not Reducto.** No Reducto API, no hosted document-parsing service.
- Not a multi-LLM-brand tool — one model, one OpenAI-compatible client.
- Not RAG, not a training pipeline, not a Docker deployment, not an
  open-ended multi-agent chat system.

## Requirements

- **Windows.** `run.cmd` is a batch file; the PDF renderer (`pypdfium2`) was
  picked specifically because it installs as a native Windows wheel with no
  Poppler/Docker dependency (see comment in `requirements.txt`). This project
  has not been run on macOS/Linux.
- **[`uv`](https://docs.astral.sh/uv/)** on `PATH`. `run.cmd` refuses to run
  without it.
- **Python.** Not pinned anywhere in the repo (no `.python-version`, no
  `requires-python`) — `uv venv` will pick whatever `uv` resolves to on the
  machine. The `.venv` in this checkout currently runs Python 3.14.7.
- Package versions are pinned in `requirements.txt`: `langchain-openai`,
  `langchain-core`, `langgraph`, `pydantic`, `python-dotenv`, `pillow`,
  `streamlit`, `pypdfium2`. Two packages the code and test suite import are
  **not** in `requirements.txt` — `openai` (a transitive dependency of
  `langchain-openai`, imported directly in several modules) and `pytest`
  (the test runner). Both are present in this checkout's `.venv`; a fresh
  `uv pip install -r requirements.txt` would install `openai` transitively
  but would **not** install `pytest`.

## Setup and running it

Double-click `run.cmd` (or run it from a shell). It:

1. Creates `.venv` via `uv venv` if missing.
2. Installs `requirements.txt` via `uv pip install` (only reinstalling when
   the file has changed since the last run, tracked in
   `.venv/requirements-installed.txt`).
3. Kills anything already listening on port 5805.
4. Launches the Streamlit UI at **http://localhost:5805**
   (`uv run --no-project ... -m streamlit run src/ui/app.py --server.port=5805 --logger.level=info`).

It does **not** create your `.env` file. There is no `.env.example` in this
repo to copy — create `.env` yourself in the repo root with the variables
below.

### Configuration

| Variable | Required | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | yes | Key for the OpenAI-compatible endpoint. |
| `OPENAI_BASE_URL` | no | Set only when using an OpenAI-compatible gateway instead of api.openai.com. |
| `REASONING_EFFORT` | no | Passed to the model as `reasoning_effort`; default `medium`, empty omits it. Only applies to the Terra model — Luna is hardcoded to `"high"` (`src/extract.py`). See [docs/MODEL.md](docs/MODEL.md). |

### 30-second path

1. Put your key in `.env` (`OPENAI_API_KEY=...`, and `OPENAI_BASE_URL=` only
   if you're pointing at a gateway instead of api.openai.com).
2. Run `run.cmd`.
3. In the UI, upload a document and click **Parse**.

## Repo map

```
src/
  graph.py       entrypoint: build_graph()/run_graph(), also runnable via `python -m src.graph --path ...`
  preprocess.py  load + rasterize + resize a PDF/image, per-page or whole-document
  parse.py       active layout parser: one concurrent LLM call per page -> ParseBlocks
  markdown.py    ParseResult -> Markdown and self-contained HTML
  annotate.py    draws parsed block boxes onto rasterized pages, saves a PDF + per-page PNGs
  extract.py     shared LLM-call plumbing (_build_llm/_invoke_structured), used by parse.py;
                 also the dormant invoice extractor/cropper (extract_invoice/extract_regions/crop_and_extract)
  validate.py    dormant: invoice arithmetic checks
  regions.py     dormant: crop-trigger rule and bbox cropping
  schema.py      all Pydantic models (active: ParseBlock/ParsePage/ParseResult; dormant: Invoice/Region/ValidationReport)
  models.py      DEFAULT_MODEL + per-model USD/1M-token rates
  usage.py       process-wide token/cost accumulator, reset per document run
  diagnostics.py PageDiagnostic model + helpers that scrub secrets/response text before they're recorded
  audit.py       dormant: write_audit_line, nothing calls it today
  prompts.py     loads prompts/runtime/*.md and does str.format substitution
  ui/app.py      the Streamlit app (entrypoint run.cmd launches)
  ui/clipboard.py "copy rendered/raw" custom component (st.components.v2)
prompts/
  runtime/       the 7 templates actually read by src/prompts.py at runtime
  *.md           (root-level) dated development/phase notes, not runtime templates
tests/           pytest suite, one test file roughly per src/ module; fixtures/ has sample invoice images/JSON
scripts/
  evaluate_prompts.py  opt-in, --live-gated evaluation script against 4 allowlisted sample documents
data/            runtime output — inbox/parse/annotated/crops/committed/review/audit; contents are gitignored
docs/            this documentation set
run.cmd          Windows launcher (see Setup above)
requirements.txt pinned package versions
```

## Running tests

```
.venv\Scripts\python.exe -m pytest
```

(or `uv run --no-project --python .venv\Scripts\python.exe -m pytest`, matching how `run.cmd` invokes Python).

The suite is 90 tests and runs offline — no `OPENAI_API_KEY` is needed;
tests that touch `_build_llm` set a fake key via `monkeypatch.setenv` and
mock or intercept the HTTP layer. In this environment, 89 passed and 1
(`tests/test_launcher.py::test_launcher_installs_only_when_requirements_change`)
failed with `'run.cmd' is not recognized as an internal or external
command` when pytest spawned `cmd.exe` from inside the Bash tool used to
write this documentation — that looks like a shell/sandboxing artifact
rather than a code defect, but it was not independently re-verified from a
native `cmd.exe` session; treat it as unconfirmed either way.

## Known limitations (visible in code/docs)

- **No arithmetic or correctness validation runs today.** `parse` is
  best-effort layout transcription for a human to read; nothing checks it
  against a ground truth. See [docs/COMPLIANCE.md](docs/COMPLIANCE.md).
- **No audit trail is written.** `src/audit.py` exists but no active node
  calls it. `data/audit/*.jsonl` files already in this checkout predate the
  pipeline being unwired.
- **No commit/review split.** `parse` → `END` regardless of outcome; nothing
  is written to `data/committed/` or `data/review/` by the active graph
  (files already there predate the unwiring too).
- **Single-user, single-process assumption.** `src/usage.py`'s token
  accumulator is a plain module-level list, explicitly documented in-source
  (`# ponytail: ...`) as safe only for one document's concurrent pages, not
  multiple documents' graphs running at once in the same process.
- **No automatic model fallback.** An unsupported model id raises before any
  API call; switching models mid-session never re-prices earlier calls.
- Every arithmetic check in the dormant validator uses a fixed tolerance:
  `abs(a - b) <= 0.05` (currency units).

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — active graph, main state/types, external systems, plus the dormant invoice pipeline
- [docs/TECHNICAL.md](docs/TECHNICAL.md) — stack choices, invariants, error handling, persistence paths
- [docs/RUNBOOK.md](docs/RUNBOOK.md) — start/stop, where logs go, failures you can infer from error strings
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) — dev setup and conventions for working in this repo
- [docs/ADR-0001-UNWIRE-INVOICE-PIPELINE.md](docs/ADR-0001-UNWIRE-INVOICE-PIPELINE.md) — why the invoice pipeline was unwired
- [docs/VALIDATE.md](docs/VALIDATE.md) — dormant validation rules (invoice arithmetic)
- [docs/REGIONS.md](docs/REGIONS.md) — dormant region schema and crop trigger
- [docs/COMPLIANCE.md](docs/COMPLIANCE.md) — what's actually gated/logged today, and what isn't
- [docs/MODEL.md](docs/MODEL.md) — model configuration and its limits
- [docs/PROMPTS.md](docs/PROMPTS.md) — the runtime prompt templates and their contract
- [docs/PROMPT-EVALUATION.md](docs/PROMPT-EVALUATION.md), [docs/CONTENT-FILTER-DIAGNOSTICS.md](docs/CONTENT-FILTER-DIAGNOSTICS.md), [docs/LUNA-VALIDATION.md](docs/LUNA-VALIDATION.md) — dated logs of specific live evaluation runs

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
