# Contributing

This checkout has no `.git` directory and no CI configuration (`.github/` is
absent); there is no branch, PR, or automated-check policy in the tree to
document. The notes below are what's actually observable from the code and
test suite, not an invented workflow.

## Dev environment

```
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
uv pip install --python .venv\Scripts\python.exe pytest
```

`requirements.txt` alone is not enough to run the test suite: `pytest` is
imported throughout `tests/` but isn't listed in `requirements.txt`.
`openai` is also imported directly (`src/extract.py`,
`scripts/evaluate_prompts.py`) but only arrives transitively via
`langchain-openai`; it has no pin of its own. See
[docs/TECHNICAL.md](TECHNICAL.md) for the full stack list.

`run.cmd` manages its own `.venv` independently (see
[docs/RUNBOOK.md](RUNBOOK.md)); the manual venv above is only needed if
you want to run tests or tools outside of `run.cmd`.

## Running tests

```
.venv\Scripts\python.exe -m pytest
```

90 tests, no live API key needed; anything touching `_build_llm` mocks or
monkeypatches around it (see e.g. `tests/fake_llm.py`,
`tests/test_extract.py`). A change should not be considered done if it
makes previously-passing tests fail. There's no coverage threshold or lint
gate configured anywhere in the repo to also satisfy.

## Conventions this codebase already follows

- **Unwire, don't delete, code that no longer fits.** The invoice
  extraction/validation graph was disconnected from `build_graph()` rather
  than removed, specifically so its tests keep running and its plumbing
  stays available for reuse; see
  [docs/ADR-0001-UNWIRE-INVOICE-PIPELINE.md](ADR-0001-UNWIRE-INVOICE-PIPELINE.md).
  If you're changing what's active vs. dormant, write or update an ADR the
  same way.
- **Docs say what's active vs. dormant, explicitly, every time.** Every doc
  in this set calls out when it's describing code that isn't reachable from
  the active graph today (grep for "dormant" and "not wired" across
  `docs/`). Keep that distinction when you edit these files; a doc that
  reads as a guarantee for code that isn't actually running is treated as a
  compliance-relevant bug here, not a style nit (see
  [docs/COMPLIANCE.md](COMPLIANCE.md)).
- **Best-effort, not fail-fast, in the graph.** Node functions in
  `src/graph.py` and `parse_document`/`parse_payload` in `src/parse.py`
  catch broadly and turn failure into a state field (`parse_error`,
  `status`, `PageDiagnostic.outcome`) rather than letting an exception
  propagate. Match that pattern for new failure modes in the same call
  path instead of introducing a new error-handling style.
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
