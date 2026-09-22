# ADE; Agentic Document Extraction

A LangGraph pipeline that reads documents with a vision LLM and produces
layout-aware Markdown and HTML, an annotated PDF, and page PNGs. Each run writes
its artifacts to `data/parse/runs/<run_id>/`. **GPT-6 Sol is the only model.**
Python produces the output formats. Uploads are identified by content, and the
UI reports progress for each page.

The project began with an invoice-extraction contract: the model *proposes* an
`Invoice`, Python *validates* the arithmetic, and a passing or human-overridden
result can be committed. Prior-authorization documents have no subtotal or
grand total for Python to check, so the extract → validate → crop →
commit/review portion is **unwired**. It remains implemented and tested, but
the active graph and UI cannot reach it. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the active and dormant paths.

## What this is not

- **Not LandingAI ADE.** No relation to LandingAI's product of the same
  name, and no dependency on it.
- **Not Reducto.** No Reducto API, no hosted document-parsing service.
- One model and one OpenAI-compatible client.
- No RAG, training pipeline, Docker deployment, or open-ended multi-agent chat.

## Requirements

- **Windows.** `run.cmd` is a batch file. The PDF renderer (`pypdfium2`) installs
  as a native Windows wheel without Poppler or Docker. This project has not run
  on macOS or Linux.
- **[`uv`](https://docs.astral.sh/uv/)** on `PATH`. `run.cmd` refuses to run
  without it.
- **Python.** Not pinned anywhere in the repo (no `.python-version`, no
  `requires-python`); `uv venv` will pick whatever `uv` resolves to on the
  machine. The `.venv` in this checkout currently runs Python 3.14.7.
- Package versions are pinned in `requirements.txt`: `langchain-openai`,
  `langchain-core`, `langgraph`, `pydantic`, `python-dotenv`, `pillow`,
  `streamlit`, `pypdfium2`. Two packages the code and test suite import are
  **not** in `requirements.txt`; `openai` (a transitive dependency of
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

The app reads the process environment and optionally loads a project-local
`.env`. The launcher does not create `.env`, and this project has no
`.env.example`. Existing environment variables are sufficient; creating a
`.env` is optional.

### Configuration

| Variable | Required | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | yes | Key for the OpenAI-compatible endpoint. |
| `OPENAI_BASE_URL` | no | Set only when using an OpenAI-compatible gateway instead of api.openai.com. |
| `REASONING_EFFORT` | no | Passed to the model as `reasoning_effort`; default `medium`, empty omits it. See [docs/MODEL.md](docs/MODEL.md). |

### 30-second path

1. Make `OPENAI_API_KEY` available in the process environment or a local `.env`.
   Set `OPENAI_BASE_URL` only when using a gateway instead of api.openai.com.
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
  models.py      GPT-6 Sol identifier and USD/1M-token rates
  usage.py       explicit per-run token ledger and Sol cost calculations
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
  evaluate_prompts.py  legacy prompt-comparison evaluator
  evaluate_resolution.py  --live-gated five-page Sol comparison; ten requests and $2 estimated budget
data/            runtime inputs/outputs; known artifact directories are gitignored
docs/            this documentation set
run.cmd          Windows launcher (see Setup above)
requirements.txt pinned package versions
```

## Running tests

The offline suite runs without a real API key; HTTP calls are mocked. It covers
Sol-only routing, pricing, overlapping run isolation, page progress, upload
replacement, Streamlit reruns, and evaluation budget guards. Run it with:

```powershell
uv run --no-project --python .venv\Scripts\python.exe python -X utf8 -m pytest -q
```

See [the OCR comparison](docs/SOL-RESOLUTION-EVALUATION.md) for live evidence
and the default-resolution decision. Historical evaluations are not Sol evidence.

## Known limitations

- `parse` is best-effort layout transcription for a human reader. It has no
  arithmetic or ground-truth correctness check. See [docs/COMPLIANCE.md](docs/COMPLIANCE.md).
- `src/audit.py` exists, but no active node calls it. Any `data/audit/*.jsonl`
  files predate the unwired pipeline.
- The active graph ends at `parse`. It does not write to `data/committed/` or
  `data/review/`.
- This is a local desktop tool. Run-level usage and artifacts are isolated, but
  the project makes no multi-user security or renderer-concurrency claim.
- Any model other than `gpt-6-sol` is rejected before an API call.
- Every arithmetic check in the dormant validator uses a fixed tolerance:
  `abs(a - b) <= 0.05` (currency units).

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); active graph, main state/types, external systems, plus the dormant invoice pipeline
- [docs/TECHNICAL.md](docs/TECHNICAL.md); stack choices, invariants, error handling, persistence paths
- [docs/RUNBOOK.md](docs/RUNBOOK.md); start/stop, where logs go, failures you can infer from error strings
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md); dev setup and conventions for working in this repo
- [docs/ADR-0001-UNWIRE-INVOICE-PIPELINE.md](docs/ADR-0001-UNWIRE-INVOICE-PIPELINE.md); why the invoice pipeline was unwired
- [docs/VALIDATE.md](docs/VALIDATE.md); dormant validation rules (invoice arithmetic)
- [docs/REGIONS.md](docs/REGIONS.md); dormant region schema and crop trigger
- [docs/COMPLIANCE.md](docs/COMPLIANCE.md); what's actually gated/logged today, and what isn't
- [docs/MODEL.md](docs/MODEL.md); model configuration and its limits
- [docs/PROMPTS.md](docs/PROMPTS.md); the runtime prompt templates and their contract
- [docs/SOL-RESOLUTION-EVALUATION.md](docs/SOL-RESOLUTION-EVALUATION.md); current Sol comparison, spending limits, and retained 1,600-pixel default
- [docs/PROMPT-EVALUATION.md](docs/PROMPT-EVALUATION.md), [docs/CONTENT-FILTER-DIAGNOSTICS.md](docs/CONTENT-FILTER-DIAGNOSTICS.md), [docs/LUNA-VALIDATION.md](docs/LUNA-VALIDATION.md); dated logs of specific live evaluation runs

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
