# Phase 1; core detectors, docs, and scaffold

## Scope

The default path: pattern-based PII redaction and prompt-injection detection, wired into a
pipeline with `check_input()` / `check_output()` and a fail-closed/fail-open safety valve. Zero
third-party runtime dependencies, no network calls, no GPU. Plus the docs and structural stubs
that the rest of the roadmap (`docs/PHASES.md`) fills in.

## What's in

- `src/guardrails/types.py`; `Finding` (detector, category, severity, span) and `Verdict`
  (allowed, text, findings, blocked_reasons).
- `src/guardrails/pii.py`; regex detectors for email, phone, SSN, IPv4, AWS access keys,
  generic API-key-shaped secrets, and credit cards (candidate regex + Luhn check). `redact()`
  replaces every match with `[REDACTED:<category>]`. Matched PII text is never copied into a
  `Finding`; findings are safe to log even when the underlying text isn't. Details:
  `docs/PII.md`.
- `src/guardrails/detectors.py`; pattern-based prompt-injection detection (instruction
  override, fake role markers, exfiltration requests, restriction-bypass phrasing, encoded
  blobs). `risk_score()` sums severity weights; `HIGH_RISK_THRESHOLD = 6` is the block line.
  Details: `docs/DETECTORS.md`.
- `src/guardrails/pipeline.py`; `GuardrailsPipeline`:
  - `check_input(text)`: redacts PII, blocks when injection risk reaches
    `HIGH_RISK_THRESHOLD`, otherwise allows (lower-severity findings still reported).
  - `check_output(text)`: redacts PII in the model's response. Never blocks.
  - `fail_mode` (`"closed"` default, or `"open"`, also settable via `GUARDRAILS_FAIL_MODE`):
    what happens if a detector raises unexpectedly. See `docs/ARCHITECTURE.md`.
- `src/guardrails/policies.py`; stub. Defines the `Policy` name type
  (`strict`/`standard`/`observe`, see `docs/POLICIES.md`); not yet wired into the pipeline.
- `src/guardrails/providers.py`, `api.py`, `ui.py`; stubs for Phases 3, 2, and 4 respectively.
  No logic yet; see each file's docstring and `docs/PHASES.md`.
- `tests/`; pytest cases covering true positives, the one deliberate false-positive
  regression test (a 16-digit non-card number that fails Luhn), the "no raw PII in findings"
  invariant, and fail-closed/fail-open behavior via a monkeypatched detector failure.
  `tests/fixtures/` exists but is empty until shared fixtures are actually needed.
- `docs/ARCHITECTURE.md`, `POLICIES.md`, `DETECTORS.md`, `PII.md`, `THREAT_NOTES.md`, `API.md` ;
  see each for its own scope.
- `.env.example`, `.gitignore`, `requirements.txt` (stub, uv/pyproject.toml is the real source
  of dependency truth), `run.cmd` (stub, runs the test suite).

## What's deliberately out (later phases)

- No working HTTP/ASGI surface (Phase 2 fills in `api.py`).
- No LLM classifier for ambiguous injection scores (Phase 3 fills in `providers.py` and wires
  `policies.py` into the pipeline).
- No Streamlit playground (Phase 4 fills in `ui.py`).
- `run.cmd` only runs tests; it grows once there's an API/UI to start.

## Known limitations of the rules-only path

See `docs/THREAT_NOTES.md` for the full list (paraphrased injection, multi-turn attacks,
freeform-PII/NER gap, obfuscation beyond simple base64 detection).

## Run it

```powershell
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src/
```

All four pass as of this phase.
