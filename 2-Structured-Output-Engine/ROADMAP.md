# Roadmap

Each phase implements only its own scope, updates the docs it owns, and
stops.

**Layout note (Phase 4):** `src/` was flattened from a single
`src/structured_output_engine/{engine,schemas,providers}` package into
independent top-level packages; `src/engine/`, `src/schemas/`,
`src/providers/`, `src/eval/`, `src/ui/` (`src/repair/` was an unused
Phase 1 stub, deleted in Phase 8); so that
`python -m src.engine` (the CLI, run from the project root) and
`import engine` / `import schemas` / `import providers` (everywhere else,
via `uv sync`'s editable install) both resolve correctly.
`[tool.uv.build-backend] module-name = [...]` in `pyproject.toml` makes
`uv_build` install all six as separate packages from one `src/`. File paths
in the Phase 1-3 entries below say `src/structured_output_engine/...`
because that's genuinely where the code lived at the time; read
`structured_output_engine.<x>` as `<x>` (e.g.
`structured_output_engine.providers.base` is now just `providers.base`).

## Phase 1; Core engine + Ollama provider; DONE (superseded, see Phases 2 & 3)

- `src/structured_output_engine/providers/base.py`; original `Provider` protocol (`generate()`); replaced in Phase 3 with a richer `complete()` interface; kept alive only as a local type in `engine/core.py` since the engine hasn't been rewired yet.
- `src/structured_output_engine/providers/ollama_provider.py`; original local provider via the `ollama` Python package; reimplemented over raw HTTP in Phase 3 (same `unload`/`installed_models` behavior, different transport).
- `src/structured_output_engine/engine.py`; `StructuredOutputEngine.run(text, schema)`: generate → validate → on failure, repair with `repair_model` (up to `max_repair_attempts`, default 2) → typed result. Provider exceptions (e.g. Ollama not running) are caught, never raised. (Became `engine/core.py` in Phase 2.)
- `tests/test_engine.py`; success / repair / exhausted-repair / provider-error paths against a fake provider, plus a live smoke test run manually against a real Ollama server (`granite4.1:3b`, extract-and-unload round trip confirmed working).

**Verified:** `uv run python tests/test_engine.py -v` → 4/4 pass. Live call against local Ollama (`granite4.1:3b`) extracted a `Person` on the first attempt; `unload()` confirmed via `GET /api/ps` returning no loaded models.

**Scope notes / assumptions carried into later phases:**
- "Graceful fallback" in the goal statement is read as: never crash, never leak raw text as if it were validated; satisfied within a single provider in this phase. Falling back *across* providers (e.g. Ollama → Agnes AI) is Phase 2 scope, not yet implemented.
- No env vars are needed yet; `OllamaProvider` talks to the default `http://localhost:11434`. `.env.example` is deferred to Phase 2, where API keys actually exist (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `AGNES_API_KEY`, `GOOGLE_API_KEY`).
- `ALLOWED_MODELS` (the full local allowlist from NOTES.md) lives in `ollama_provider.py` even though only two of its entries are wired up yet; `qwen3-vl:2b` / `AuditAid/PaddleOCR-VL-1.6-0.9B` (Phase 4, OCR) and the embedding/translate entries (not on the core path per NOTES.md) are unused until then.
- No pytest dependency added; tests use stdlib `unittest` per project convention of minimal dependencies.
- `[project.scripts]` entry point from `uv init --package` was removed; there's no CLI yet (Streamlit UI arrives in Phase 3).

## Phase 2; Schemas, registry, result envelope; DONE (no LLM calls)

- `src/structured_output_engine/engine/`; `engine.py` became a package: `core.py` (`StructuredOutputEngine`, unchanged behavior) + `result.py` (new `StructuredResult`/`ValidationIssue`, replacing the old `Success`/`Failure`).
- `src/structured_output_engine/schemas/`; `registry.py` (`SchemaRegistry`: `register`/`names`/`get`/`json_schema`/`example`) plus four built-ins, each `ConfigDict(extra="forbid")` with `Field(description=...)` on every field: `ContactRecord`, `InvoiceDraft` (+ `Currency` enum, `LineItem`), `MeetingNotes` (+ `ActionItem`), `ClassificationResult` (+ placeholder `Label` enum).
- `tests/test_schemas.py`; registry API, good-JSON-for-all-four, extra field rejected, enum mismatch, missing required field, nested-list error location and success.
- `tests/test_engine.py`; updated for the `StructuredResult` shape.
- `pyproject.toml`; added `pydantic[email]` for `ContactRecord.email: EmailStr`.
- docs updated: `ARCHITECTURE.md`, `TECHNICAL.md`, `RUNBOOK.md`, `EVAL.md`, `SCHEMAS.md` (all had stale `Success`/`Failure` references from Phase 1).

**Verified:** `uv run python tests/test_engine.py -v` → 4/4; `uv run python tests/test_schemas.py -v` → 10/10; live Ollama round-trip re-confirmed against the new `engine/` package and `ContactRecord`.

## Phase 3; Provider layer (all four, HTTP-only, no Pydantic parsing); DONE

`src/structured_output_engine/providers/` was rebuilt around a richer shared
interface; `complete(messages, json_schema, temperature, max_tokens) ->
ProviderResponse(text, model, raw)`; replacing Phase 1's minimal
`generate()`. All four adapters call their backend directly over `httpx`
(no vendor SDKs), verified against current docs rather than assumed; see
`docs/TECHNICAL.md` "Provider adapters" for the verified shape of each and
`docs/TECHNICAL.md` "Error handling" for the `ProviderError` code table and
retry policy.

- `base.py`; `Provider` protocol, `ProviderResponse`, `ProviderError`, shared `request_with_retry` (2 attempts, 5xx only) and `raise_for_status` (401/403→`unauthorized`, 404→`not_found`, other 4xx/5xx→`http_error`), `embed_schema_in_system_prompt` (the no-structured-output fallback, shared by Ollama's old-server path and Agnes).
- `ollama_provider.py`; `/api/chat`; detects `format`/JSON-schema support via `/api/version` (≥0.5.0) instead of assuming it; `installed_models()` and `unload()` preserved from Phase 1, reimplemented over raw HTTP instead of the `ollama` package.
- `openai_compatible.py`; `{OPENAI_BASE_URL}/chat/completions`; `response_format: json_schema`; `reasoning_effort="medium"` default (NOTES.md, for `gpt-5.6-luna`/`gpt-5.6-terra`).
- `agnes_provider.py`; subclasses the above, fixed to `https://apihub.agnes-ai.com/v1`; always prompt-embeds the schema because Agnes's documented parameters (checked directly) don't include `response_format`.
- `gemini_provider.py`; raw REST against `generativelanguage.googleapis.com/v1beta`; `generationConfig.responseJsonSchema` (accepts standard JSON Schema directly, verified against the `google-genai` SDK docs).
- `tests/test_providers.py`; all four adapters against mocked HTTP (`httpx.MockTransport`): structured-output path, prompt-fallback path (Ollama old-version + Agnes), missing API key, 401, 404, 5xx-then-success retry, 5xx-twice-exhausted, timeout not retried.
- `pyproject.toml`; added `httpx` as a direct dependency (was transitive via `ollama`); removed the `ollama` package (no longer used; Ollama access is now raw HTTP, same as the other three).
- `engine/core.py`; its `Provider` type hint now a local `Protocol` (the old `generate()` shape) instead of importing the now-repurposed `providers.base.Provider`, since nothing implements the old shape anymore. No behavior change.
- Docs updated for accuracy: `README.md`, `docs/ARCHITECTURE.md`, `docs/TECHNICAL.md`, `docs/RUNBOOK.md`, `docs/SCHEMAS.md` (all had examples/claims describing the old `generate()`-based `OllamaProvider`, which no longer exists).

**Verified:** `uv run python -m unittest discover -s tests -v` → all pass. Live Ollama capability-detection and a real `complete()` call (`granite4.1:3b`, `format=<ContactRecord schema>`) confirmed against the actual local server (version `0.34.0`, ≥0.5.0 path taken).

**Deliberately not done this phase (per the brief: "do not parse into Pydantic yet"):**
- **The engine and the provider layer are not connected.** `StructuredOutputEngine.run()` still calls `.generate()`, which none of these four adapters implement; see the callout in `docs/TECHNICAL.md`. Today, getting "text in, validated JSON out" is two manual steps (a provider's `complete()`, then `StructuredResult.from_raw_text()`); see README's Example.
- `.env` is still not auto-loaded (no `python-dotenv`); every provider reads its env var directly as a fallback when the constructor argument is omitted, which works without a loader as long as the process environment has it set.
- No provider registry/selection UI (Phase 4).
- OpenAI strict-mode schema compatibility (`additionalProperties: false`, `anyOf` restrictions) not verified against the four built-in schemas.

## Phase 4; Pipeline: engine ↔ providers, finally connected; DONE

`src/engine/pipeline.py`; `Pipeline.run(text, schema) -> StructuredResult`,
the first component that actually goes text-in to validated-JSON-out
against a real provider. Closes the gap flagged at the end of Phase 3.

- **Messages:** system prompt with the full JSON Schema (field descriptions included, since they're already in `model_json_schema()`) + "return only one JSON object."
- **Extraction (`extract_json`):** whole reply, else a fenced code block, else the first balanced `{...}` span (brace-counting that respects string literals, not a naive regex); `ParseError` only when none of the three find anything JSON-shaped at all.
- **Attempt ladder (default `max_attempts=3`):** 1) initial (primary provider/model) → 2) retry (same provider/model, lower temperature, validator errors fed back) → 3) repair (switches to `repair_model`, default local Ollama `qwen3.5:0.8b`, **even if the initial pass used a different provider**; `pin_provider=True` keeps it on the original provider/model instead). A provider exception (network/auth/timeout) consumes an attempt like a validation failure does, rather than short-circuiting immediately (a deliberate difference from Phase 1's engine); this is what lets repair recover from a primary-provider outage.
- **Graceful fallback** once attempts are exhausted: `fallback="partial"` (default); `build_partial()` keeps whichever fields independently validate (via `TypeAdapter` per field), fills only *non-required* missing/invalid fields from the schema's own default, and leaves a truly-required missing field in `errors` rather than fabricating it; `"empty"`; `data=None`, errors kept; `"raise"`; raises `PipelineFailure`, caught at the CLI's top level (`--strict`), never left as an uncaught traceback.
- **Logging:** one `logging.info(...)` per attempt; stage, provider, model, ok, latency_ms, error types, a 200-char raw-reply snippet.
- **CLI (`src/engine/__main__.py`):** `python -m src.engine --schema invoice --text-file tests/fixtures/invoice.txt --provider ollama --model granite4.1:3b` (verified working live, exactly as written, against the real local Ollama server). `--schema` accepts an unambiguous prefix of a registry name (`invoice` → `invoice_draft`). Also: `--text` (inline alternative to `--text-file`), `--repair-provider`/`--repair-model`, `--pin-provider`, `--max-attempts`, `--fallback`/`--strict`, `--temperature`, `--max-tokens`.
- `tests/test_pipeline.py`; 16 tests against a fake `complete()`-based provider: valid first pass, broken JSON repaired on retry (same provider), enum typo repaired via the repair-model switch *and* left in errors when never fixed, max attempts exhausted with no exception, extra keys rejected (`fallback="empty"`) and stripped (`fallback="partial"`), `extract_json`'s three strategies + `ParseError`, `build_partial`'s field-by-field logic directly, `pin_provider`, `fallback="raise"` caught by the caller.
- `tests/fixtures/invoice.txt`; the fixture the CLI example reads.

**Verified:** `uv run python -m unittest discover -s tests -v` → 48/48. Live: the exact CLI command above, run against real Ollama, extracted a full `InvoiceDraft` correctly on the first attempt (exit code 0); an unknown `--schema` name fails cleanly with exit code 1 and no traceback.

**Not done this phase:**
- No cross-*provider* fallback beyond the fixed repair-model switch; if both the primary and repair provider are down, the result is `ok=False`, not a further fallback to a third provider.
- The pipeline never calls `OllamaProvider.unload()`; a CLI session leaves the last-used Ollama model resident.
- OpenAI strict-mode schema compatibility still not verified (carried over from Phase 3).

## Phase 5; Extract from file (optional); DONE

`src/engine/file_input.py`; `load_text_from_file(path)`: text/md/json read
directly (no OCR); anything else (image, or `.pdf` first page) goes through
OCR then the same `Pipeline`. New CLI flag `--file`.

- **OCR order:** PaddleOCR (`AuditAid/PaddleOCR-VL-1.6-0.9B`) primary → `qwen3-vl:2b` via Ollama fallback. Confirmed the private `AuditAid/...` HF repo is gated (401, not publicly inspectable); the adapter is built against the public base model `PaddlePaddle/PaddleOCR-VL`'s documented `paddleocr.PaddleOCRVL(pipeline_version="v1").predict(path)` API, which the ticket's own framing already anticipated might not be exactly right ("if OCR packages are painful... isolate... keep working if import fails"); the isolation/fallback contract is what's actually verified, not this specific niche model's exact call shape.
- **Isolation:** `paddleocr`/`paddlepaddle` and `PyMuPDF` (PDF rasterization) are **not** added as project dependencies; both are lazily imported only when actually needed, and any failure (not installed, broken install, load/inference error) raises `OcrError` internally, caught and turned into a fallback (PaddleOCR → Ollama) or a clear CLI error (PDF without PyMuPDF) rather than a crash or an import-time failure for the rest of the project.
- **`qwen3-vl:2b` fallback needed zero changes to `OllamaProvider`**; Ollama's native `/api/chat` takes an `images: [base64, ...]` key directly on a message dict (verified against docs.ollama.com), and `OllamaProvider.complete()` already passes messages through as plain dicts.
- **VRAM unload order** (docs/RUNBOOK.md): OCR/VL model extracts → gets unloaded (Ollama: `keep_alive=0` in a `finally`, best-effort; PaddleOCR: goes out of scope, GC'd) → **only then** does `Pipeline.run()` load the generate model.
- `tests/test_file_input.py`; 8 tests: text/md/json skip OCR, PaddleOCR path (faked via `sys.modules` injection, since it's genuinely not installed), fallback to a fake Ollama VL provider when PaddleOCR import fails, both-fail → `OcrError`, PDF without PyMuPDF → clear `OcrError`, unload called in both the success and failure fallback cases.
- Fixture: reused `tests/fixtures/invoice.txt` from Phase 4 (already "a small synthetic text invoice file") for the skip-OCR tests and the `--file` CLI example; no image/PDF fixture was created (none of the OCR-path tests need a real one; downloading a real scanned document was explicitly out of scope).

**Verified:** `uv run python -m unittest discover -s tests -v` → 56/56. Live: `--file tests/fixtures/invoice.txt` (text, skips OCR) run against real Ollama, identical result to `--text-file`. The OCR paths themselves (PaddleOCR and the `qwen3-vl:2b` Ollama fallback) are verified only via the mocked unit tests above, not live; no real image input existed to test with.

**Not done this phase:**
- No real image/PDF was ever OCR'd live, by either backend; real-world accuracy of either OCR path is unverified.
- The generate model isn't explicitly unloaded before a repair-stage model switch (carried over from Phase 4).
- `--file`'s OCR prompt asks the VL model for verbatim text extraction, not structured markdown/layout preservation; untuned.

## Phase 6; Streamlit UI + eval harness + real run.cmd; DONE

`src/ui/app.py`; sidebar (provider/model/repair model/pin-provider/max
attempts/fallback mode/schema-or-paste-JSON-Schema), Run tab (text area or
file upload → `Pipeline` → validated JSON, errors table, attempt timeline,
raw-text expander), Schema tab (JSON Schema + example), Eval tab (runs
`tests/eval/cases.jsonl`, shows valid/repair rate, mean attempts, latency).

- `schemas/dynamic.py`; best-effort JSON-Schema-to-Pydantic (`create_model`) for the sidebar's "Paste JSON Schema" option; no `$ref`/`$defs`/`anyOf`/`oneOf`/`allOf`.
- `eval/runner.py`; `load_cases()` / `run_eval()`, exactly the metrics `docs/EVAL.md` speced back in Phase 2.
- `tests/eval/cases.jsonl`; 16 cases, 4 per schema × {clean, messy, missing_fields, almost_json}.
- Attempt timeline needed **zero changes to `pipeline.py`**; a `logging.Handler` on the existing `"engine.pipeline"` logger captures the args of each already-emitted `logger.info(...)` call (see Phase 4) as structured rows.
- `run.cmd` rewritten for real end users: plain `venv` + `pip install -r requirements.txt` (not `uv`; deliberately, since a target machine may not have it), copies `.env.example` → `.env`, warns (doesn't fail) if Ollama is unreachable, launches the UI. `requirements.txt` is now accurate (was a stale stub) since this path actually installs from it.
- `tests/test_ui_app.py`; `st.testing.v1.AppTest` (in-process, headless, no browser): app loads, all schemas + paste option present, Schema tab renders schema+example, invalid/valid pasted schemas, missing-API-key shows a clean error, empty input warns instead of running, Eval tab shows case count.

**Verified:** `uv run python -m unittest discover -s tests` → 73/73. Live: `AppTest` driving the real Run flow against real Ollama (invoice text → valid `InvoiceDraft`, attempt timeline populated); confirmed both the pipeline wiring and the logging-based timeline capture actually work, not just render. Separately, `run.cmd` itself run from a byte-for-byte clean state (renamed the dev `.venv` aside, let the script create its own plain venv from scratch): venv creation, `pip install`, `.env` copy, Ollama reachability check, and Streamlit startup (HTTP 200) all verified, then torn down and the original `.venv` restored.

**Not done this phase (addressed in Phase 8, or still open; see there):**
- OCR still never exercised live from the UI (same gap as Phase 5; no real image/PDF fixture).
- No provider-model dropdown scoped to `OllamaProvider.installed_models()`; model is a free-text field for all providers.
- Eval tab has no per-schema breakdown or export, just the aggregate + a flat results table.

## Phase 7; Docs-only pass (no new features; 73/73 tests unchanged); DONE

- `docs/TECHNICAL.md`; provider structured-output support matrix, an "Extraction rules" section, and retry policy consolidated with `Pipeline`'s real 3-stage ladder front and center (legacy `StructuredOutputEngine` clearly marked as such; then deleted next phase).
- `docs/SCHEMAS.md`; concrete "Adding a fifth schema" walkthrough.
- `docs/EVAL.md`; real numbers from a local run (Ollama was reachable): `granite4.1:3b`, 16/16 cases, 93.75% valid rate, 0% repair rate, 1 deliberate failure (`contact_missing_fields`), 1.12 mean attempts, 2586ms mean latency.
- `requirements.txt`; pinned to exact (`==`) versions.

## Phase 8; Close the known gaps; MOSTLY DONE

- **Deleted `engine/core.py` (`StructuredOutputEngine`) and its test**; legacy, never connected to any real provider, superseded entirely by `engine/pipeline.py`. Also deleted the unused `src/repair/` stub package (Phase 1 scaffolding, nothing ever used it). Removed both from `pyproject.toml`'s `module-name` list.
- **Unload before repair-stage provider switch**; `Pipeline.run()` now calls `old_provider.unload(old_model)` (best-effort, duck-typed on `hasattr(..., "unload")`) when attempt 3 switches to a different provider than attempt 1/2 used, before making the repair call. Skipped when `pin_provider=True` (never switches, nothing to unload). New tests in `tests/test_pipeline.py`.
- **Model dropdown, not free text**; sidebar's Model field is now `st.selectbox`: for `ollama`, options come live from `OllamaProvider.installed_models()` (cached 30s, falls back to the full allowlist if Ollama's unreachable); for the three hosted providers, a fixed known-models list (NOTES.md). Verified live against the real local Ollama server.
- **OCR exercised live, for real, for the first time**; generated a synthetic (non-copyrighted) `tests/fixtures/invoice_scan.png` via PIL and ran it through `load_text_from_file` with PaddleOCR genuinely absent: the `qwen3-vl:2b` Ollama fallback extracted the text near-verbatim, and feeding that into `Pipeline.run()` against `invoice_draft` produced a fully valid `InvoiceDraft` on the first attempt. This was a manual live verification, not added to the committed (hermetic, mocked) test suite.
- **Hosted-provider eval comparison; blocked, not a code issue.** A single-call viability check against `GeminiProvider` failed with `API_KEY_INVALID` from Google's API; the configured `GOOGLE_API_KEY` isn't a working credential (or doesn't cover this fictional model name). Did not proceed to OpenAI-compatible/Agnes to avoid further exposing key material in error output. **Action needed from the user:** supply a working `GOOGLE_API_KEY` / `OPENAI_API_KEY`+`OPENAI_BASE_URL` / `AGNES_API_KEY` to get a real comparison run.
- **Not attempted:** installing `paddlepaddle`/`paddleocr` for real; the ticket's own Phase 5 brief flagged this as likely painful on native Windows, and the Ollama VL fallback above already gives genuine, live, working OCR coverage without that risk. Still opt-in per `docs/RUNBOOK.md`.
- Cross-provider fallback beyond the fixed repair-model switch remains out of scope; a hard outage on both `provider` and `repair_provider` still ends in `ok=False`. Treated as an accepted design boundary, not a bug, given no spec ever asked for a deeper fallback chain.
