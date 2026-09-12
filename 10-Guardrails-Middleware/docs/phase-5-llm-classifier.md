# Phase 5 — optional LLM classifier

## Scope

Two independent, optional detectors for cases Phases 3–4's rules can't phrase-match — both off
by default, both no-ops unless explicitly enabled in `config/classifier.yaml`:

- `LlmClassifierDetector` — asks a small local model to score `{injection, exfil, benign}` and
  blocks above a threshold.
- `EmbeddingSimilarityDetector` — cosine similarity against 10 fixed generic injection phrases.

Not in scope: wiring either into a default `Guard()`, Agnes AI/OpenAI-compatible/Gemini provider
implementations (the brief only asked to check "a provider is up" generically — only Ollama is
implemented; `Classifier`/`Embedder` are `Protocol`s so another provider slots in later without
touching the detectors).

## What's in

- `src/guardrails/providers.py`:
  - `ClassifierResult` (pydantic) — `injection`/`exfil`/`benign`, each constrained to `[0, 1]`.
  - `Classifier`/`Embedder` (`Protocol`s) — what the two detectors need from a provider.
  - `OllamaClassifier` — calls `/api/generate` with `think: false` (qwen3.5 is a hybrid-reasoning
    model; without this it can wrap JSON in `<think>` tags first, and it's slower). Verified
    live against the local Ollama instance before writing tests (both a benign and an
    injection-like prompt classified correctly, no repair needed).
  - `OllamaEmbedder` — calls `/api/embeddings`. Also verified live: a paraphrase of an injection
    phrase scored 0.80 cosine against the reference set, a benign question scored 0.33.
  - `_extract_json_obj`/`_parse_classifier_result` — pull the first `{...}` out of a raw model
    response and validate it against `ClassifierResult`; return `None` (not raise) on failure, so
    the repair flow above them can retry once.
  - `LlmClassifierDetector`, `EmbeddingSimilarityDetector` — `Detector`-conforming wrappers.
  - `INJECTION_REFERENCE_PHRASES` — exactly 10 generic phrases, thematically matching Phase 4's
    blocklists, written once, not extended.
  - `load_classifier_config()` — same resolution pattern as `pii.py`/`rules.py`.
- `config/classifier.yaml` — `use_llm_classifier`, `require_classifier`, `threshold`, provider
  settings, nested `embedding_lane` block. Everything off by default.
- `tests/test_providers.py` — `_FakeClassifier`/`_FakeEmbedder` test doubles (no network in the
  suite), one test per behavior: disabled-by-default, threshold block/allow, provider-down
  soft-skip vs. required-and-down raise, the repair-then-raise flow (via a monkeypatched
  `_generate`), JSON-extraction edge cases, cosine-similarity math, and two end-to-end tests
  proving `fail_mode` governs the required-and-down case through the real `Guard`/`Pipeline`.

## Design decisions made here

- **Failure handling reuses `Pipeline`'s `fail_mode`, doesn't reimplement it.** Both "provider
  down and `require_classifier`" and "malformed JSON survives one repair attempt" simply `raise`
  from the detector. `Pipeline` (Phase 2) already turns a detector exception into a block
  (`fail_mode="closed"`) or a recorded `warn` (`fail_mode="open"`) — see
  `tests/test_providers.py::test_required_and_down_blocks_via_guard_fail_closed` /
  `..._allows_via_guard_fail_open`. Provider-down-and-*not*-required is different: that's an
  expected, benign condition (the feature just isn't available right now), not a failure, so it
  returns a plain `classifier_unavailable` finding instead of raising — `require_classifier` is
  what decides whether "down" counts as a failure at all.
- **Parse-with-repair is a pure function pair, decoupled from the network call.**
  `_extract_json_obj`/`_parse_classifier_result` take a string, return a result or `None` — no
  I/O. `OllamaClassifier.classify()` composes them with `_generate()` (the actual HTTP call).
  This is what makes the repair logic testable via a monkeypatched `_generate` instead of a live
  model.
- **No numpy, no vector DB.** Cosine similarity over 10 short vectors is a five-line pure-Python
  function. Qdrant (even embedded, `path=`) or numpy would be dependencies for a problem too
  small to need either — the brief's own framing ("numpy cosine is enough... Qdrant not
  required") already points this way; this goes one step further and skips numpy too.
- **`think: false` on every classify/repair call.** Found by testing against the live model, not
  guessed — the raw prompt without it risks slow responses and `<think>` reasoning text leaking
  into the field `_extract_json_obj` has to parse around.
- **Exactly 10 reference phrases, no more.** Matches the brief's explicit instruction. They
  parallel `config/blocklists/injection.txt`/`role_play.txt`'s themes so the two lanes agree on
  what "injection-like" means, without literally duplicating the same strings.

## What's deliberately out

- Not registered in any default `Guard` construction — both detectors require the caller to opt
  in explicitly, matching "off by default."
- No Agnes AI / OpenAI-compatible / Gemini client — `Classifier`/`Embedder` are ready for one,
  none is built.
- `policies.py`'s `strict`/`standard`/`observe` names still don't select *which*
  `config/classifier.yaml` loads or override its thresholds — same open item Phase 4 flagged for
  `rules.yaml` (`docs/POLICIES.md`).
- No `<think>` content is parsed, inspected, or exposed anywhere — irrelevant to classification
  and disabled at the source.

## Run it

```powershell
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src/
```

All four pass as of this phase — 74 tests: 25 new in `test_providers.py`, 49 unchanged from
Phases 2–4. The live-Ollama checks above were manual smoke tests, not part of this suite (the
suite runs on fakes so it stays fast and doesn't require Ollama to be running).
