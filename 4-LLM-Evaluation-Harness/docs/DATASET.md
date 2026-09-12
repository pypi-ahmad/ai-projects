# Dataset

Golden cases live under `datasets/golden/*.jsonl` — one JSON object per line. Loaded and
validated by `src/dataset` (`Case` and friends in `src/dataset/models.py`, all with
`extra="forbid"` -- an unknown field in a case is a validation error, not a silent no-op).

## Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique case id (duplicates across all files in a directory are rejected) |
| `suite` | `"smoke" \| "regression" \| "quality"` | yes | Which suite this case belongs to |
| `input.user` | string | yes | The user turn sent to the candidate model |
| `input.system` | string | no | System prompt, if any |
| `input.context` | string | no | Extra context; folded into the user turn by the candidate runner as `"Context:\n<context>\n\n<user>"` |
| `expected.answer` | string | no | Drives the `exact_match` metric |
| `expected.contains_any` | list[string] | no | Drives `contains_any` |
| `expected.contains_all` | list[string] | no | Drives `contains_all` |
| `expected.forbidden_any` | list[string] | no | Drives `forbidden_any` |
| `expected.regex` | string | no | Drives `regex` |
| `expected.json_schema_name` | string | no | Drives `json_parse_ok` (validity only, not schema-checked -- see docs/METRICS.md) |
| `judge.rubric_id` | string | only if `judge` is set | Which `rubrics/*.yaml` file to grade against |
| `judge.required` | bool | no, default `false` | If judging this case never produces a valid verdict, `required: true` forces a `judge_error` (fails the case); `false` just skips it |
| `tags` | list[string] | no, default `[]` | Free-form tags; each one becomes its own group in `summary.json`'s `by_tag` |
| `metadata` | object | no, default `{}` | Free-form, unused by the harness itself |
| `skip_if.needs_ollama` | bool | no, default `false` | Skip this case (never call the provider) unless the candidate run's `--provider` is `ollama` |
| `skip_if.needs_gpu` | bool | no, default `false` | Same as `needs_ollama` -- Ollama is the only provider in this repo backed by a local GPU, so "needs a GPU" and "needs Ollama" resolve identically |
| `skip_if.needs_provider` | string | no | Skip unless the candidate run's `--provider` exactly matches this value |

A metric only runs when its `expected.*` field is set (see docs/METRICS.md for exactly
which). A case with no `expected` fields at all and no `judge` still runs -- it just
carries no pass/fail signal beyond `latency_ms` and `length_tokens_approx`.

`skip_if` is checked by `src/runners/candidate.py` before the provider is ever called
(see `skip_reason()`). A skipped case gets a `candidates.jsonl` record with
`skip_reason` set, `text: null`, `error: null`, `latency_ms: 0.0` -- `src.metrics` and
`src.eval` both exclude it from the run entirely (not counted as an error, not part of
`n_cases`), and `src.judge` never sees it (it already skips any record with `text: null`).

## Example

```json
{"id": "smoke-002", "suite": "smoke", "input": {"user": "Name the largest planet in the solar system."}, "expected": {"contains_any": ["Jupiter"]}, "tags": ["smoke", "contains"]}
{"id": "regression-009", "suite": "regression", "input": {"user": "Explain in a few sentences why automated testing matters."}, "judge": {"rubric_id": "answer_quality", "required": true}, "tags": ["regression", "judge"]}
```

See `datasets/golden/smoke.jsonl` (5 cases) and `datasets/golden/regression.jsonl` (10
cases) for the current sets.

## Validating

```
python -m src.dataset validate datasets/golden
```
