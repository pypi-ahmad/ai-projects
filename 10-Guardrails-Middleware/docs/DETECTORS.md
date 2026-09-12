# Detectors

Category names only; this is a defensive pattern list, not an attack how-to.

## The `Detector` protocol (Phase 2)

`src/guardrails/pipeline.py` defines what a detector is: a `detector_id: str` plus
`run(text, context) -> Finding`. `Pipeline`/`Guard` run a caller-supplied ordered list of these ;
`Guard()` with no arguments still always allows; you register detectors explicitly (see
`docs/ARCHITECTURE.md` for the recommended composition).

## Registered detectors (Phase 3 to 5)

- **`src/guardrails/pii.py`'s `PiiDetector`**; PII categories, see `docs/PII.md`. Always
  `severity="warn"` (transform, never block).
- **`src/guardrails/rules.py`'s `InputRulesDetector`/`OutputRulesDetector`**; see below.
  Severity per category from `config/rules.yaml`.
- **`src/guardrails/providers.py`'s `LlmClassifierDetector`/`EmbeddingSimilarityDetector`**; off
  by default, see "Optional LLM classifier" below.

## Input categories (`rules.py`, `detect_input`)

- `max_chars_exceeded`; request longer than the configured limit. No `replacement`; length
  can't be sensibly redacted, this is report/block only.
- `control_char`; non-whitespace control characters (`\x00` to `\x08`, `\x0B` to `\x1F`, `\x7F`;
  `\t`/`\n`/`\r` excluded).
- `blocklist_injection`, `blocklist_role_play`; phrases from `config/blocklists/injection.txt`
  and `role_play.txt` (substring or `regex:`-prefixed line, case-insensitive).
- `encoding_evasion`; the same blocklist phrases, re-checked against NFKC-normalized text plus a
  small homoglyph swap; reported only when a match appears *after* normalizing and not before.
  Not exhaustive; see the limits note under "Encoding evasion" below.

## Output categories (`rules.py`, `detect_output`)

- `blocklist_leak_phrases`; phrases from `config/blocklists/leak_phrases.txt` (e.g. "here is
  your system prompt"). Key-shaped-string leaks are already covered by the reused PII `api_key`
  detector on output (`docs/PII.md`); not duplicated here.
- `blocklist_denied_topics`; phrases from `config/blocklists/denied_topics.txt`, empty by
  default; opt in per operator.

## Encoding evasion; limits

Normalization is Unicode NFKC (folds common fullwidth/compatibility forms to ASCII) plus a small,
explicit Cyrillic/Greek→Latin homoglyph table (`_HOMOGLYPH_MAP` in `rules.py`). This catches the
"obvious" cases; fullwidth Latin letters, a handful of common lookalike letters; not every
possible evasion: zero-width characters, less-common homoglyphs, RTL override tricks, and other
scripts aren't covered.

## Optional LLM classifier (`providers.py`, Phase 5); off by default

- `llm_classifier`; asks a small local model (Ollama `qwen3.5:0.8b` by default) for
  `{injection, exfil, benign}` scores (pydantic-validated, each in `[0, 1]`); blocks when
  `injection >= threshold`. A malformed response gets one repair attempt (same model, asked to
  fix its own JSON); if that also fails, or the provider is required
  (`config/classifier.yaml`'s `require_classifier`) but unreachable, the detector raises and
  `Pipeline`'s `fail_mode` decides block-vs-continue. If the provider is merely down and *not*
  required, this returns an info-severity `classifier_unavailable` finding instead of raising.
- `embedding_similarity`; cosine similarity of the input against 10 fixed reference phrases
  (`INJECTION_REFERENCE_PHRASES` in `providers.py`), embedded via Ollama
  (`qwen3-embedding:0.6b` by default); blocks when the max cosine score reaches a threshold.

See `docs/phase-5-llm-classifier.md` for the full design and `docs/POLICIES.md` for how
`require_classifier` interacts with `fail_mode`.

## Injection categories implemented in `detectors.py` (Phase 1, untouched, not wired in)

Still uses Phase 1's dataclass `Finding` from `guardrails.types`, predates the `Detector`
protocol, and substantially overlaps with `rules.py`'s `blocklist_injection`/`blocklist_role_play`
categories above. Whether to retire it, fold it into a blocklist file, or keep it as an
independent second check is an open decision (`docs/PHASES.md`), not resolved yet:

- `override_instructions` (high); attempts to override or discard prior instructions.
- `role_confusion` (high); fake role markers embedded in user-supplied text.
- `exfiltration_request` (medium); attempts to get the system prompt or rules repeated back.
- `restriction_bypass` (medium); phrasing aimed at lifting stated restrictions.
- `encoded_payload` (low); suspiciously long encoded-looking blobs.

## Planned (later phases)

- Resolve `detectors.py`'s overlap with `rules.py`'s blocklists.
- An Agnes AI / OpenAI-compatible / Gemini `Classifier`/`Embedder` implementation, alongside
  the existing Ollama one.

Non-goal: this file (and this repo) does not enumerate working attack payloads or step-by-step
bypass techniques. Blocklist files ship short and generic by design (`docs/phase-4-rules-engine.md`);
the embedding-lane reference set is exactly 10 fixed phrases, not a growing corpus
(`docs/phase-5-llm-classifier.md`).
