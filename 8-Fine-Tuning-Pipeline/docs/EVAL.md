# Evaluation

Same code path scores both the frozen prompt-only baseline (`src/eval/baseline.py`) and LoRA
(`src/eval/bakeoff.py`, via `LocalAdapterModel` implementing the same `ChatClient` shape) — see
`run_baseline`/`score_one`/`aggregate_metrics` in `src/eval/baseline.py`. Same test set, same
system prompt (`configs/baseline_prompt.txt`), same decoding (temperature 0 / greedy).

## Metrics (`aggregate_metrics`)

All four fields (`priority`, `product`, `sentiment`, `next_action`) are closed enums (see
`docs/TASK.md`), so every metric here is exact-match based — there is no fuzzy/"contains" metric.
(Phase 1's original plan mentioned "exact/contains"; contains doesn't really apply to enum
classification, so it was dropped rather than built as a no-op. Recording that as a deliberate
deviation, not an oversight.)

| Metric | Definition |
|---|---|
| `json_valid_rate` | Fraction of items whose raw model output parses as JSON matching the `TicketTarget` schema (see `parse_ticket_target`). Unparseable output (bad JSON, wrong enum value, missing field) counts as invalid, not a crash. |
| `field_micro_f1` | Correct field predictions ÷ (n_items × 4 fields). Since each field is single-label multi-class, micro-precision = micro-recall = micro-F1 = per-field-flattened accuracy; an invalid-JSON item contributes 0 correct across all 4 fields. |
| `full_exact_rate` | Fraction of items where all 4 fields match gold exactly (implies valid JSON). |
| `per_field_accuracy` | Same per-field breakdown, one accuracy number per field, for debugging which field the model struggles with. |

## Per-item errors

`write_report` writes `reports/{baseline,lora}_<name>.json` (the aggregate numbers above) and
`reports/{baseline,lora}_<name>_errors.csv` — **only the non-exact-match rows** (ticket text, gold
vs. predicted per field, which fields mismatched, and the parse error if JSON was invalid).

## Bake-off (`src/eval/bakeoff.py`)

`reports/bakeoff.md`: a metric-by-metric table (baseline 0.8b, baseline 2b if that report exists,
lora, delta) plus an explicit verdict section that states in plain text when LoRA **regressed** on
any metric and whether it beat baseline overall on `full_exact_rate` — no silent win-washing (see
`write_bakeoff_md`, and `tests/test_bakeoff.py::test_write_bakeoff_md_states_when_lora_lost`).

If the adapter directory has no `train_meta.json` (training was never run), `bakeoff.md` says
**"adapter missing"** and the process exits non-zero — it does not write a table of fabricated or
degenerate (all-zero) scores (`write_adapter_missing_md`).

## Optional judge (off by default)

`--judge` (default off) — only runs on items where baseline's and LoRA's predictions actually
*disagree* with each other (`find_disagreements`), not on every item. For each disagreement, a
judge model (`granite4.1:3b` by default, or a cloud model via `--judge-model`) is shown the ticket,
gold label, and both predictions, and returns a `Pydantic`-validated verdict:
`winner: "baseline" | "lora" | "tie"`. Tallied counts are appended to `bakeoff.md` and saved to
`reports/judge_<run_id>.json`. An unparseable judge reply counts as `"tie"` rather than crashing
the run. **Not exercised live in this repo** — see known gaps in `RUNBOOK.md`.
