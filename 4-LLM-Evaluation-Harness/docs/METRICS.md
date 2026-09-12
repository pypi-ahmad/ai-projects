# Metrics

Metrics implemented by `src/metrics`. Each metric is a pure function that returns a
`MetricResult`: `name`, `score` (`float` 0.0-1.0, or `null` for informational metrics),
`passed` (`bool` or `null`), `detail` (`str | null`, populated mainly on failure).

`CaseScore` aggregates the `MetricResult`s that apply to one candidate answer for one
case: `case_id` + `metrics: list[MetricResult]`.

## Which metrics run

A metric runs only when its corresponding `case.expected.*` field is truthy (set and
non-empty) -- a missing/empty field means the metric is **skipped**, not failed, so it
never appears in `CaseScore.metrics`. `length_tokens_approx` and `latency_ms` are the
exception: they always run (when candidate text exists) since they don't depend on
`expected`. If the candidate call itself failed (`text` is `null`), every text-dependent
metric is skipped and only `latency_ms` is recorded.

## Deterministic (rule-based)

| Metric | Runs when | Definition |
|---|---|---|
| `exact_match` | `expected.answer` set | Candidate and expected are both whitespace-collapsed, stripped, and lowercased (unless `case_sensitive=True`), then compared for equality -- the "quasi-exact-match" convention common in eval harnesses (e.g. lm-evaluation-harness), not a byte-for-byte `==`. |
| `contains_all` | `expected.contains_all` set | Passes if every phrase is a case-insensitive substring of the candidate. |
| `contains_any` | `expected.contains_any` set | Passes if at least one phrase is a case-insensitive substring of the candidate. |
| `forbidden_any` | `expected.forbidden_any` set | Passes if none of the phrases appear as a case-insensitive substring of the candidate. |
| `regex` | `expected.regex` set | Passes if `re.search(pattern, candidate)` finds a match. The pattern controls its own case-sensitivity (e.g. `(?i)`) -- no flag is forced. |
| `json_parse_ok` | `expected.json_schema_name` set | Passes if `json.loads(candidate)` succeeds. This is JSON *validity* only -- it does not validate against the named schema (no schema registry exists). |
| `length_tokens_approx` | always (candidate text present) | `len(text.split())` -- a word-count proxy for token count, no tokenizer dependency. Informational: `score`/`passed` are always `null`. |
| `latency_ms` | always | Pass-through of the candidate record's recorded latency. Informational: `score`/`passed` are always `null`. |

`contains_all` / `contains_any` / `forbidden_any` / `exact_match` all default to
case-insensitive matching; each function takes a `case_sensitive=True` override, not
currently exposed on the case schema.

Citation-format checking (named in the Phase 1 draft of this doc) was dropped: there is
no `expected.citation*` field on the case schema, and it wasn't part of this phase's scope.

## LLM-as-judge

Rubrics live under `rubrics/*.yaml` (schema in `src/judge/rubric.py`: `id`, `version`,
`dimensions: [{name, description, weight}]`, weights summing to 1.0). Weights are given
to the judge model in the prompt to guide how it weighs each dimension -- `overall` and
`pass` are the judge model's own outputs, not recomputed here from `scores`.

Default rubric `answer_quality`: `correctness`, `completeness`, `groundedness_if_context`
(scored 1.0 when no context was given), `instruction_following`.

| Field | What it is |
|---|---|
| `scores` | Per-dimension score, 0.0-1.0, keyed by dimension name |
| `overall` | The judge's own overall score, 0.0-1.0 |
| `pass` | The judge's own pass/fail verdict |
| `rationale` | Short free-text explanation |
| `evidence_spans` | Quotes from the candidate answer supporting the verdict |

Judge output must validate against `JudgeVerdict` (Pydantic) before any of it is trusted
-- judge free text never counts as a score. Both the judge call and the repair call pass
`think=False` to Ollama, since a thinking model can otherwise burn its whole output
budget on chain-of-thought and never emit the JSON at all (see docs/RUNBOOK.md). One
JSON-repair pass (`qwen3.5:0.8b` on Ollama, falling back to the judge's own
provider/model if Ollama is unavailable) is attempted on a malformed response; if it's
still invalid, the case gets a `judge_error` record (`overall: null`, `pass: false`) when
`case.judge.required` is true, or is skipped otherwise. If the judge provider+model is
the same as the candidate's, the record is flagged `same_model_warning` and the CLI
prints a warning (self-judging risks bias).
