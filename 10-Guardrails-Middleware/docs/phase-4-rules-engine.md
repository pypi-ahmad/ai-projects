# Phase 4; rules-only input/output filtering, wired into Guard

## Scope

Rules only, no LLM anywhere. A new detector family (`rules.py`) covering input-side length,
blocklist, control-char, and encoding-evasion checks, plus output-side leak-phrase and
denied-topics blocklists; all config-driven, severity included. Unlike Phases 2 to 3, this phase
also registers detectors with `Guard`: `PiiDetector` (from `pii.py`), `InputRulesDetector`,
`OutputRulesDetector` (from `rules.py`) are real `Detector`-conforming classes, proven end-to-end
in `tests/test_rules.py::test_standard_policy_via_guard`.

## What's in

- `src/guardrails/models.py`; `drop_overlapping_spans()` moved here from `pii.py` (same reason
  `apply_spans` moved here in Phase 3: `rules.py` needed the identical overlap-dedup logic, so
  it's now a shared function over `Span` rather than a third private copy).
- `src/guardrails/rules.py`; new module:
  - `detect_input(text, config=None) -> Finding`; `max_chars` (length overflow → one span, no
    replacement; length can't be sensibly redacted), `control_char` (non-whitespace control
    chars), `blocklist` (phrases from `config/blocklists/injection.txt` +
    `role_play.txt`), `encoding_evasion` (NFKC-normalize + a small homoglyph swap, re-run the
    same blocklist match, report only the matches that appear *after* normalizing and not
    before).
  - `detect_output(text, config=None) -> Finding`; `leak_pattern`
    (`config/blocklists/leak_phrases.txt`) and `denied_topics`
    (`config/blocklists/denied_topics.txt`, ships empty).
  - `load_rules_config(path=None)`; same resolution order as `pii.py`'s config loader
    (explicit path → `$GUARDRAILS_RULES_CONFIG` → `config/rules.yaml` → code defaults).
  - `InputRulesDetector`, `OutputRulesDetector`; thin `Detector`-conforming wrappers.
- `src/guardrails/pii.py`; added `PiiDetector`, the `Detector`-conforming wrapper Phase 3's
  docs said was the natural next step. `detect()`/`redact()` themselves are unchanged.
- `config/rules.yaml`; per-category `enabled`/`severity` (`input.max_chars` also has `limit`).
- `config/blocklists/{injection,role_play,leak_phrases,denied_topics}.txt`; short, generic
  phrase lists (5 to 8 lines each; `denied_topics.txt` ships empty). One phrase per line
  (case-insensitive substring), or `regex: <pattern>` for a regex line.
- `tests/test_rules.py`; one test per detector category with small fixtures, config-loading
  tests, and the one end-to-end `Guard` test proving the "standard" policy.

## Design decisions made here

- **One blocklist mechanism, four phrase files.** "Blocked substrings/regex" and "role-play
  override patterns" turned out to be the same mechanism (load phrases, case-insensitive
  substring-or-regex match) applied to different files; so does "leak patterns" and "denied
  topics" on the output side. Building four separate detector implementations for what's
  structurally one mechanism would have been pure duplication.
- **Severity drives the "standard" policy, not hardcoded branching.** Every category's severity
  comes from `config/rules.yaml`; `DEFAULT_RULES_CONFIG` ships input categories at `block` and
  output categories at `warn`, which *is* the "standard" policy described in the brief. Changing
  the policy is a config edit, not a code change.
- **Finding-level severity aggregation, decoupled from span deduplication.** A `Finding`
  carries one `severity` for potentially many spans across categories with different configured
  severities. Rather than tracking which surviving (post-overlap-dedup) span belongs to which
  category, `detect_input`/`detect_output` record a category's severity the moment it fires at
  least once, then take the worst (`block` > `warn` > `info`) across all categories that fired ;
  independent of which individual spans later get dropped as overlapping. Span dedup is purely
  about not double-processing the same text range; severity is about which categories matched at
  all.
- **`max_chars` never "transforms."** Every other category either blocks or produces a
  `replacement`-bearing span. Length overflow can't be sensibly redacted (there's no substring to
  swap for a placeholder that fixes an over-length request), so it's report/block only; its
  span carries no `replacement` and `apply_spans()` leaves it untouched in the text.
- **Encoding-evasion limits, documented not hidden.** Normalization is NFKC (handles common
  fullwidth/compatibility Unicode forms) plus a small, explicit Cyrillic/Greek→Latin homoglyph
  table. This is not exhaustive; it catches the "obvious" cases the brief asked for, not every
  possible lookalike-character or zero-width-character trick. See `docs/DETECTORS.md`.
- **`detectors.py` left alone, its future genuinely undecided.** Phase 1's injection regex module
  now substantially overlaps with `rules.py`'s `blocklist` category (both catch
  "ignore previous instructions"-style phrasing). It wasn't touched, isn't wired into `Guard`,
  and this phase doesn't resolve whether it should be retired, merged into a blocklist file, or
  kept as an independent second check; that's a real open decision, not an oversight.
- **No large jailbreak dataset.** Each blocklist file is 4 to 7 generic phrases, matching the
  brief's explicit instruction. This is a starting point for operators to extend, not a
  comprehensive attack corpus.

## What's deliberately out

- `detectors.py` (Phase 1 injection regex); untouched, unwired, overlap with `rules.py` noted
  above but not resolved.
- HTTP/ASGI middleware (`api.py`); still a stub. `Guard` is usable directly as a library today.
- LLM classifier providers, Streamlit UI; unchanged stubs.

## Run it

```powershell
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src/
```

All four pass as of this phase; 49 tests: 16 new in `test_rules.py`, 33 unchanged from
Phases 2 to 3 (`test_pii.py`, `test_detectors.py`, `test_pipeline.py`).
