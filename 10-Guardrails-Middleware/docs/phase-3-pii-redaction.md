# Phase 3; PII redaction on the typed core

## Scope

Rebuild `pii.py`'s detection and redaction on Phase 2's pydantic model (`Span`/`Finding` from
`models.py`) instead of Phase 1's dataclasses, add config-driven per-type toggling, stable
per-request placeholders, and the requested type list. `detectors.py` (injection) is untouched.
Not in scope: wiring `pii.py` into `Guard` as a real `Detector`; that's Phase 4, alongside
`detectors.py`.

## What's in

- `src/guardrails/models.py`; `apply_spans()` moved here from `pipeline.py` (it's a pure
  function over the `Span` data type, not pipeline-orchestration logic; `pii.py` needed it
  without creating a detector→pipeline-runner dependency, so `pipeline.py` now imports it from
  here too; no behavior change, just the correct dependency direction).
- `src/guardrails/pii.py`; full rewrite:
  - `detect(text, config=None) -> Finding`; one `Finding` (`detector_id="pii"`) carrying every
    matched `Span` across all enabled types, each with a `replacement` already assigned.
  - `redact(text, finding=None, config=None) -> str`; applies those replacements
    (`models.apply_spans`).
  - `load_pii_config(path=None) -> dict[str, bool]`; resolves an explicit path, then
    `$GUARDRAILS_PII_CONFIG`, then `config/pii.yaml`, then `DEFAULT_PII_CONFIG`.
  - Detectors: `email`, `phone` (generic + Indian mobile), `credit_card` (Luhn), `ip_address`,
    `api_key` (AWS-shaped, prefixed-secret-shaped, and a generic high-entropy-token heuristic),
    `aadhaar_possible`/`pan_possible` (off by default). See `docs/PII.md` for the full table and
    false-positive notes.
- `config/pii.yaml`; the default config file, `aadhaar`/`pan` off, everything else on.
- `tests/test_pii.py`; rewritten: per-type detection, the Luhn-negative regression test,
  same-value-twice vs. distinct-values placeholder behavior, config toggling (including
  `load_pii_config` reading a real file via `tmp_path`), and "no raw value anywhere in a span
  replacement or the redacted output" for every enabled type in one string.

## Design decisions made here

- **Stable placeholders, scoped to one call.** A raw value that recurs gets the same placeholder
  every time within one `detect()`/`redact()` call. When a type has 2+ *distinct* values, each
  gets a numeric suffix in first-seen order (`[EMAIL_1]`, `[EMAIL_2]`); a single distinct value
  stays bare (`[EMAIL]`); which is why `detect()` collects every span before assigning any tags,
  rather than tagging as it goes. This stability does not extend across separate `detect()`/
  `redact()` calls (e.g. different turns of a conversation); that's out of scope here.
- **No raw text in `Span`, ever.** Matches Phase 1's own rule. This is what makes "logs store
  redacted text only" true by construction for anything that logs a `Finding`/`Span`; see
  `docs/PII.md`.
- **High-entropy API-key heuristic.** In addition to the known-prefix patterns (AWS, `sk-`/
  `api_key-`/`secret-`), a generic detector flags any 20+ char alnum/`-`/`_` run (no spaces) with
  mixed letters+digits and Shannon entropy ≥ 3.0 bits/char. This catches tokens with no
  recognizable prefix at the cost of some false positives (hashes, UUIDs, long identifiers) ;
  documented, not hidden, in `docs/PII.md`.
- **Aadhaar/PAN labeled "possible."** Shape-only regex, no checksum, no legal validation; the
  *type name itself* carries the caveat (`aadhaar_possible`/`pan_possible`, not `aadhaar`/`pan`)
  so it's self-documenting even out of context (e.g. in a log line). Off by default.
- **Detection-order tie-breaking.** When two enabled types could match overlapping text (e.g. a
  bare 12-digit run can satisfy both `aadhaar_possible` and the generic phone pattern), the
  first-registered type in `pii.py`'s internal detector order wins the overlap; see the ordering
  comment above `_DETECTORS` in the source.
- **Package import path, again.** The brief's config path (`config/pii.yaml`) is resolved
  relative to the current working directory, matching how this repo is actually run
  (`uv run pytest` / `uv run streamlit` from the project root); not relative to the installed
  package location, which would break once distributed as a wheel elsewhere. If that ever
  matters, `load_pii_config` already takes an explicit `path` override.

## What's deliberately out

- `pii.py` still isn't wired into `Guard`/`Pipeline`; no `Detector`-conforming wrapper class
  exists yet. Phase 4.
- `detectors.py` (injection) wasn't touched; still Phase 1's dataclass-based implementation,
  still not on the typed core. Also Phase 4.
- No Aadhaar/PAN checksum validation, and none is planned; see `docs/PII.md`'s "possible" caveat.
- No logging call anywhere in the codebase yet; "logs store redacted text only" is upheld by
  `Span` never carrying raw text, not by any actual log statement (there isn't one to check yet).

## Run it

```powershell
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src/
```

All four pass as of this phase; 33 tests: 20 in `test_pii.py` (rewritten this phase), 7 in
`test_detectors.py` and 6 in `test_pipeline.py` (both unchanged since Phase 2).
