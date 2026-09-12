# Evaluation

`src/eval/runner.py` (`load_cases`, `run_eval`) runs `tests/eval/cases.jsonl`
(16 cases across the 4 built-in schemas) through a `Pipeline` and reports
the metrics below. Used by the Streamlit UI's Eval tab and directly callable
without it.

## Metrics

- **Valid rate**; fraction of runs with `ok=True` and no repair attempt
  (`attempts == 1`). The cleanest signal of how well a
  model+schema+prompt combination performs unaided.
- **Repair rate**; fraction of runs with `ok=True` but `attempts > 1`.
  High repair rate with high eventual success is a different problem than
  low valid rate outright; it points at prompt/schema clarity, not model
  capability.
- **Failure rate**; fraction of runs ending `ok=False`.
- **Schema error types**; for `ok=False` results, `EvalCaseResult.error_types`
  comes straight from `StructuredResult.errors[i].type` (`missing`, `enum`,
  `extra_forbidden`, `parse_error`, `provider_error`, etc.); no
  string-parsing, see `docs/TECHNICAL.md`.
- **Latency**; `mean_latency_ms` across cases; each case's own
  `latency_ms` is `Pipeline`'s cumulative wall-clock time for that run
  (all attempts included, from `StructuredResult.latency_ms`).

## Last local run

Ollama was reachable, so this is a real run, not a placeholder:

- **Date:** 2026-09-11
- **Config:** `provider=ollama`, `model=granite4.1:3b`, defaults otherwise (`max_attempts=3`, `fallback=partial`, repair model `qwen3.5:0.8b`)
- **Command:** `run_eval(Pipeline(OllamaProvider("granite4.1:3b"), "granite4.1:3b"), load_cases("tests/eval/cases.jsonl"))`

| Metric | Value |
|---|---|
| Total cases | 16 |
| Valid rate | 93.75% (15/16) |
| Repair rate | 0.00% |
| Failure rate | 6.25% (1/16) |
| Mean attempts | 1.12 |
| Mean latency | 2586 ms |

The one failure was `contact_missing_fields` (deliberately: "Met a guy named
Bob at the meetup. Didn't get his email or anything else."; `email` has no
source material at all). All 3 attempts failed to produce a valid `email`;
`fallback="partial"` reconstruction couldn't fill `name` either, so both
ended up in `errors` as `type="missing"` rather than a fabricated value.
The intended behavior is not a bug. Every other case (including the
`messy`/`almost_json` categories) validated on the first attempt against
`granite4.1:3b` with Ollama's schema-constrained decoding; 0% repair rate
here reflects that constrained decoding, not that repair is untested (see
`tests/test_pipeline.py` for repair-path coverage against a fake provider).

If Ollama isn't reachable when this doc is regenerated: **not run**; there
is no cached/mocked substitute for these numbers; re-run the command above
against a live provider to refresh them.

## Not yet decided

- No per-provider comparison run yet (only `ollama`/`granite4.1:3b` above); the hosted providers would need real API keys to include here.
- No CI wiring to refresh these numbers automatically; they're a manual snapshot.
