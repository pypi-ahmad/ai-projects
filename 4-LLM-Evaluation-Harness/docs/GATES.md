# Gate

`python -m src.gate` compares a run's summary against `config/gate.yaml`'s thresholds
and, if present, `baselines/current.json`. It never trains or reruns anything -- it only
reads `reports/<run>/summary.json` (written by `python -m src.eval`).

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Pass |
| `2` | Quality gate fail (a threshold or regression check failed) |
| `3` | Harness/infra error (missing/malformed summary, config, or baseline) -- **not** a quality regression, callers should not treat this as "the model got worse" |

## `config/gate.yaml`

| Field | Type | Meaning |
|---|---|---|
| `min_rule_pass_rate` | float, optional | Fail if `summary.mean_rule_pass_rate` is below this **or is missing entirely** (unlike the judge checks below, there's no `allow_missing_*` bypass for this one -- a dataset with no rule-checkable `expected.*` fields anywhere will fail this check whenever it's configured, even though nothing actually regressed) |
| `min_judge_overall` | float, optional | Fail if `summary.mean_judge_overall` is below this |
| `max_p95_latency_ms` | float, optional | Fail if `summary.p95_latency_ms` is above this |
| `max_regression_delta` | float, optional | Applied to **both** `mean_rule_pass_rate` and `mean_judge_overall`: fail if `current < baseline - delta` for either. Only checked when a baseline exists. |
| `allow_missing_judge` | bool, default `false` | If the run has no judge data (`mean_judge_overall` is `null`) and this is `true`, both `min_judge_overall` and the judge half of `max_regression_delta` are skipped instead of failing. Set `true` for CPU-only CI where no judge runs. |

Every field is independently optional except `allow_missing_judge` -- a gate only checks
what it's configured to check. A missing baseline file doesn't cause an infra error: the
regression-delta checks are simply skipped (there's nothing to regress against yet), while
the absolute thresholds (`min_rule_pass_rate`, `min_judge_overall`, `max_p95_latency_ms`)
still apply.

## Baseline

`baselines/current.json` is the last **accepted** summary, written by:

```
python -m src.gate --accept reports/<run>
```

It refuses to run when the `CI` environment variable is set (GitHub Actions sets this
automatically) -- accepting a baseline is a local-only action; CI only ever evaluates.

Its shape (`Baseline` in `src/gate/models.py`):

```json
{
  "summary": { "...": "the full RunSummary from summary.json" },
  "config": {
    "candidate_provider": "ollama",
    "candidate_model": "granite4.1:3b",
    "judge_provider": "ollama",
    "judge_model": "qwen3.5:2b",
    "dataset_path": "datasets/golden/smoke.jsonl",
    "dataset_hash": "sha256 of the dataset file at accept time"
  }
}
```

`candidate_provider`/`candidate_model` come from the first record of the run's
`candidates.jsonl`; `judge_provider`/`judge_model` from the first record of
`judge_scores.jsonl` if it exists (`null` otherwise). `dataset_path`/`dataset_hash` are
carried over from the run's own `summary.json` (computed there by `src.eval`, which is
given `--dataset` and hashes it).

`python -m src.gate --run` compares the current run's `dataset_hash` against the
baseline's and prints a warning to stderr on mismatch ("dataset has changed since the
baseline was accepted..."). This is a warning only, not a `GateFailure` -- it doesn't
affect the exit code, since a dataset change is often intentional (e.g. adding cases);
it just flags that the regression-delta comparison may not be apples-to-apples.

## Usage

```
python -m src.gate --run reports/<run> --baseline baselines/current.json --config config/gate.yaml
python -m src.gate --accept reports/<run>
```
