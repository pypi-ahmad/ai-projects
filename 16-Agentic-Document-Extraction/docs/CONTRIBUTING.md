# Contributing

This project is the `16-Agentic-Document-Extraction` subdirectory of the
`ai-projects` Git repository. Run these commands from this project folder. The
parent repository's `llm-eval.yml` workflow targets `4-LLM-Evaluation-Harness`;
this application has no dedicated CI workflow. This document does not define a
branch or publication policy.

## Dev environment

```
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
uv pip install --python .venv\Scripts\python.exe pytest
```

`requirements.txt` alone cannot run the test suite: `pytest` is imported
throughout `tests/` but is not listed in `requirements.txt`.
`openai` is also imported directly (`src/extract.py`,
`scripts/evaluate_prompts.py`) but only arrives transitively via
`langchain-openai`; it has no pin of its own. See
[docs/TECHNICAL.md](TECHNICAL.md) for the full stack list.

`run.cmd` uses the same project-local `.venv` (see [docs/RUNBOOK.md](RUNBOOK.md)).
Use manual setup when developing without launching Streamlit, and install the
test runner separately when needed.

## Running tests

```powershell
uv run --no-project --python .venv\Scripts\python.exe python -X utf8 -m pytest -q
```

112 tests are collected in this checkout as of September 23, 2026. No live API
key is needed; anything touching `_build_llm` mocks or
monkeypatches around it (see e.g. `tests/fake_llm.py`,
`tests/test_extract.py`). A change should not be considered done if it
makes previously-passing tests fail. There's no coverage threshold or lint
gate configured in this project to also satisfy. Tests include Streamlit
AppTest, mocked HTTP transport, run isolation, and evaluation-budget guards.
Live evaluations are separate paid operations; see
[the bounded Sol comparison](SOL-RESOLUTION-EVALUATION.md).

## Conventions this codebase already follows

- **Unwire rather than delete code that no longer fits.** The invoice
  extraction/validation graph was disconnected from `build_graph()` so its
  tests continue to run and its plumbing remains available for reuse. See
  [docs/ADR-0001-UNWIRE-INVOICE-PIPELINE.md](ADR-0001-UNWIRE-INVOICE-PIPELINE.md).
  If you're changing what's active vs. dormant, write or update an ADR the
  same way.
- **State whether code is active or dormant.** The docs mark code that the
  active graph cannot reach (search `docs/` for "dormant" and "not wired").
  Keep that distinction. A document that promises behavior the application
  does not run is a compliance problem. See
  [docs/COMPLIANCE.md](COMPLIANCE.md)).
- **Per-page failures preserve other pages.** `parse_payload` records failed
  pages as diagnostics; `node_parse` maps parse-step exceptions to
  `parse_error`/`status`. Preprocessing failures can still propagate from
  `run_graph`, and direct `parse_document` calls can raise for configuration,
  preprocessing, or persistence errors. Do not turn one rejected page into
  failure of the remaining pages.
- **Diagnostics never carry secrets or raw response text.**
  `src/diagnostics.py`'s `safe_identifier()` is the one gate for anything
  provider-supplied going into a `PageDiagnostic`. New diagnostic fields
  should go through it (or an equivalent check), not be added as raw
  strings.

## Where to look before changing something

Start from [docs/ARCHITECTURE.md](ARCHITECTURE.md) for the active/dormant
graph shape, then [docs/TECHNICAL.md](TECHNICAL.md) for invariants and
persistence paths. `docs/MODEL.md` has the strict-`json_schema` shaping
rules that constrain how any `src/schema.py` model sent to the LLM can be
written; read it before adding or changing a field on `Invoice`,
`ParseBlock`, `ParsePage`, or `Region`.
