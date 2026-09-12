# Phase 2 — typed core: Guard, Pipeline, Detector

## Scope

Replace Phase 1's fixed two-detector `GuardrailsPipeline` (dataclasses, hardcoded PII + injection
calls) with the target architecture: pydantic models, an ordered list of `Detector`s a caller
supplies, and a `Guard` facade. No production detectors are wired in this phase — "no regex
pack." Phase 1's `pii.py`/`detectors.py` are untouched and still tested; they just aren't
plugged into `Guard` yet.

## What's in

- `src/guardrails/models.py` — pydantic `Span`, `Finding`, `GuardContext`, `GuardDecision` (see
  `docs/ARCHITECTURE.md` for fields).
- `src/guardrails/pipeline.py`:
  - `Detector` — a `Protocol`: `detector_id: str` + `run(text, context) -> Finding`.
  - `Pipeline` — runs an ordered detector list once: applies each finding's span replacements to
    the working text before the next detector runs (so ordering controls what later detectors
    see); the first `block`-severity finding stops the pipeline unless `policy == "observe"`;
    a detector exception blocks under `fail_mode="closed"` or is recorded as a `warn` finding
    and skipped under `fail_mode="open"`.
  - `Guard` — one `Pipeline` for `input_detectors`, one for `output_detectors`;
    `check_input()`/`check_output()` build the `GuardContext` and run the matching pipeline.
- `src/guardrails/__init__.py` — now exports `Guard`, `Pipeline`, `Detector`, and the pydantic
  model types. `GuardrailsPipeline` and the old dataclass `Finding`/`Verdict` are no longer
  re-exported at package level (still importable directly from `guardrails.types` if needed —
  `pii.py`/`detectors.py` still use them internally).
- `tests/test_pipeline.py` — rewritten against `Guard`, using throwaway stub detectors defined
  in the test file itself: empty-pipeline allow, a block-severity stub blocking, a redact stub's
  transform being visible to the next detector, fail-closed/fail-open on a raising stub, and
  `policy="observe"` not blocking a block-severity finding.

## Design decisions made here

- **Redact-first-on-input.** For the input direction, PII-redaction detectors go first in
  `input_detectors` so injection/classifier detectors see redacted text. The pipeline doesn't
  special-case this — it's a caller-side ordering convention, enforced by list order, not a
  built-in distinction between detector "kinds."
- **`fail_mode` and `policy` are orthogonal.** A detector crash blocks under
  `fail_mode="closed"` regardless of `policy` — even `"observe"`. `policy` only gates whether a
  normal (non-crash) `block`-severity finding actually blocks.
- **Package import path.** The brief specified `from src.guardrails import Guard`. The installed
  package resolves as `guardrails` (src-layout, `module-name = "guardrails"` in
  `pyproject.toml`), not a `src.*` namespace — so the real import is `from guardrails import
  Guard`. Not changing the packaging to force the literal `src.guardrails` path; flagging it
  here instead.

## What's deliberately out

- No detectors register with `Guard` by default — `Guard()` with no arguments always allows.
- `policies.py` still just defines the `Policy` name type; `strict` doesn't yet differ from
  `standard` in pipeline behavior (that distinction is detector-level, and there are no real
  detectors yet — see `docs/POLICIES.md`).
- No HTTP surface, no LLM classifier, no UI — unchanged from Phase 1's stubs.

## Run it

```powershell
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src/
```

All four pass as of this phase (23 tests: 17 from Phase 1's `pii.py`/`detectors.py`, 6 new for
`Guard`/`Pipeline`).
