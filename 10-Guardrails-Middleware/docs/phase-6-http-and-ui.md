# Phase 6 — HTTP API, wrap_call, Streamlit UI

## Scope

Put the whole stack behind an HTTP surface and a manual test console, and add one new library
primitive (`Guard.wrap_call`) that both the API and any other caller can use. `run.cmd` now
actually runs something.

## What's in

- `src/guardrails/pipeline.py`:
  - `Pipeline.run()` / `Guard.check_input()` / `Guard.check_output()` now take an optional
    per-call `policy` override — needed because the API's request body carries `policy` per
    request, and mutating a shared `Pipeline.policy` per-request would race under concurrent
    requests. `self.policy` is still the default when no override is given; nothing existing
    changed behavior.
  - `Guard.wrap_call(messages)` — a context manager: finds the last `role: "user"` message,
    runs `check_input` on it, and either raises `GuardBlocked(decision)` (before the `with` body
    ever runs) or yields `SafeMessages(messages, decision)` with that message's `content`
    replaced by `decision.text_out`. A message list with no user message passes through
    unchanged — there's nothing to check.
- `src/guardrails/api.py` — FastAPI app, meant for `127.0.0.1` only (`run.cmd` and the
  `__main__` block both bind loopback explicitly):
  - `POST /v1/check_input`, `POST /v1/check_output` — `{text, policy}` in, `GuardDecision` out.
    Always `200`; these *report*, they don't enforce.
  - `POST /v1/wrap_chat` — `{messages, policy}` in. Uses `Guard.wrap_call` under the hood: a
    block becomes `400 {"error": "GUARD_BLOCK", ...}` and the provider is never called
    (verified in `tests/test_api.py`); otherwise the (possibly redacted) messages go to
    `_PROVIDER` (`EchoProvider` by default — echoes the last message back), the reply runs
    through `check_output`, and both decisions come back in the response.
  - One shared `Guard` backs all three endpoints: `PiiDetector` + `InputRulesDetector` +
    `LlmClassifierDetector` on input, `PiiDetector` + `OutputRulesDetector` on output — same
    composition as Phase 4/5's recommended one, with the classifier config-gated and off by
    default as always.
  - Isolation: `_log_finding()`, gated by `GUARDRAILS_LOG_FINDINGS=1` (off by default), appends
    `decision.model_dump(exclude={"text_in"})` plus a timestamp/direction to
    `data/logs/findings.jsonl`. `text_in` is the one field on `GuardDecision` that's ever raw,
    pre-redaction text — it's the only thing explicitly excluded.
- `src/guardrails/ui.py` — Streamlit playground: direction and policy selectors, toggles for the
  LLM classifier and embedding-similarity lane (both off by default, matching the API and every
  other entry point), a text box, and a "Check" button that shows the action (color-coded),
  a findings table, and `text_out`. Native Streamlit widgets throughout (`segmented_control`,
  `toggle`, `dataframe`), no injected CSS, `width="stretch"` not `use_container_width`.
- `run.cmd` — `uv sync --group dev`, then starts the API (`uvicorn`, bound to `127.0.0.1`) and
  the UI (`streamlit run`) each in their own `start`-ed window.
- `tests/test_api.py` — `TestClient` (in-process, no real server/socket needed): both check
  endpoints, `wrap_chat` allow/block/transform, a spy provider proving it's never called on a
  block, and two isolation tests (`GUARDRAILS_LOG_FINDINGS` unset → no file written; set → the
  written record excludes `text_in` and contains no raw input substring at all).
- `tests/test_pipeline.py` — three new tests for `wrap_call` (transform, block-raises-and-skips-
  body, passthrough-with-no-user-message) and one for the per-call `policy` override.

## Design decisions made here

- **Per-call `policy` override, not per-request `Guard` construction.** The API could have built
  a fresh `Guard` per request to honor per-request `policy`, but that re-parses/reloads every
  detector's config on every call for no reason. Passing `policy` through to `Pipeline.run()`
  is the smaller, cheaper change, and it's backward compatible — omitting it keeps the
  construction-time `self.policy`.
- **`wrap_call` lives in the library, not just the API.** The brief showed it as a plain Python
  `with` statement (`with guard.wrap_call(messages) as safe:`), not an HTTP concept — so it's a
  `Guard` method in `pipeline.py`, and `/v1/wrap_chat` is a thin HTTP wrapper around it, not a
  separate implementation of the same logic.
- **`check_input`/`check_output` never return non-200, even on `action="block"`.** Only
  `wrap_chat` turns a block into an HTTP error, because only `wrap_chat` is actually making (or
  skipping) an upstream call on the caller's behalf. The two plain check endpoints are pure
  reporting — a caller decides what to do with `action="block"` themselves.
- **Isolation is enforced by field exclusion, not by trying to scrub content.** `_log_finding`
  doesn't inspect `text_out` or `findings` for anything that "looks like" raw input — it relies
  on the invariant already established since Phase 1 (`Span` never carries raw matched text) and
  simply never touches `text_in`. Verified directly:
  `tests/test_api.py::test_log_enabled_excludes_raw_input` asserts the raw email string doesn't
  appear anywhere in the serialized log record, not just that the `text_in` key is absent.
  Verified live too, not just by the fakes: the manual API/UI smoke tests below.
- **Manual smoke tests, not just `TestClient`.** Ran the real `uvicorn`-served API and the real
  Streamlit UI (`--server.headless true`, non-default ports) and confirmed both actually serve —
  the API's `/v1/check_input` and `/v1/wrap_chat` responses matched what the fakes-based test
  suite already predicted, and the UI returned `200`. Time-boxed, then explicitly torn down: on
  Windows, `uv run streamlit`/`uv run uvicorn` spawn a child process tree that a bash `kill %1`
  doesn't reach, so both had to be stopped with `taskkill /F /T` on the actual PID from
  `netstat -ano` — confirmed via a second `netstat` pass that nothing was left listening.
- **A pre-existing, unrelated process was already listening on port 8501** (multiple established
  connections — looked like an actively-used session, not a leftover from this one) when the UI
  smoke test ran. Left it alone and used a different port instead, rather than assuming it was
  safe to touch.

## What's deliberately out

- No auth on the API — it's `127.0.0.1`-only by design, not a public service (see the
  project-wide non-goals in `docs/PHASES.md`).
- `_PROVIDER` is a single hardcoded `EchoProvider()` — no config-driven provider selection for
  the API's stub-vs-real provider choice. Swapping it means editing `api.py`.
- `detectors.py` (Phase 1 injection regex) still isn't wired into the API's `Guard`, same open
  question as Phase 4/5.
- No rate limiting, no request size limits beyond whatever `InputRulesDetector`'s `max_chars`
  already enforces.

## Run it

```powershell
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src/
```

All four pass as of this phase — 88 tests: 10 new in `test_api.py`, 4 new in `test_pipeline.py`
(3 for `wrap_call`, 1 for the policy override), 74 unchanged from Phases 2–5.

To actually run the service: `run.cmd`, or manually:

```powershell
uv run uvicorn guardrails.api:app --host 127.0.0.1 --port 8000
uv run streamlit run src/guardrails/ui.py
```
