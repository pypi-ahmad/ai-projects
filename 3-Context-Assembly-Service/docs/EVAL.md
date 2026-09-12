# Evaluation

## Eval runner

`tests/eval/run_eval.py` — reads `tests/eval/cases.jsonl`, runs `allocate` + `pack` for each
case, checks expected invariants, and prints aggregate metrics.

```cmd
uv run python tests/eval/run_eval.py
uv run python tests/eval/run_eval.py --json   # machine-readable output
```

## Metrics

| Metric | Definition | Target |
|--------|-----------|--------|
| `overflow_count` | Cases where `token_total > context_window` | **0** (hard requirement) |
| `drop_rate` | `total_dropped / total_input_blocks` across all cases | < 0.25 for well-tuned priorities |
| `compress_rate` | `total_compress_jobs / total_input_blocks` | — (informational) |
| `avg_leftover` | Average `usable − token_budget_used` across cases | — (informational) |

`overflow_count` is the primary hard gate, but the runner exits non-zero if either
`overflow_count > 0` **or** any case fails its `expect` assertions (`failed > 0`).

## Case format (`cases.jsonl`)

Each line is a JSON object:

```jsonc
{
  "id": "case-name",
  "description": "...",
  "context_window": 400,
  "reserve_output_tokens": 80,
  "user_message": "...",
  "policy": "balanced",
  "expect": {
    "no_overflow": true,    // token_total <= context_window
    "user_present": true,   // user message appears in messages
    "max_drops": 0,         // optional: upper bound on drop count
    "has_compress_jobs": true  // optional: at least one compress job expected
  },
  "blocks": [
    {"id": "b1", "family": "docs", "text": "...", "priority": 70,
     "compressible": true, "droppable": true}
  ]
}
```

## Built-in cases (6)

| ID | What it tests |
|----|---------------|
| `all-fit-small` | All blocks fit; zero drops expected |
| `doc-overflow` | Oversized docs force drops; window still not exceeded |
| `tiny-window` | Extreme window; everything except force-keeps may drop |
| `compress-eligible` | Compressible block overflows into a compress job |
| `tools-heavy-policy` | `tools_heavy` policy allocates more room for tool schemas |
| `memory-only` | Empty docs and tools families do not break cap logic |

## Per-request invariants (unit tests)

The four unit test suites enforce the core invariants on every code change:

| Suite | Invariants |
|-------|-----------|
| `tests/test_blocks.py` | Token counting is deterministic; empty string is 0; window lookup |
| `tests/test_budget.py` | Window never exceeded; user never dropped; borrow works; empty family OK |
| `tests/test_packer.py` | packed_tokens + reserves ≤ window; report IDs match messages; rerun stable |
| `tests/test_compress.py` | Offline-safe; UNAVAILABLE moves to dropped; FAILED moves to dropped; budget updated |

## Block survival invariant

A high-priority block (`priority ≥ 80`) should never be dropped while a lower-priority block
(`priority < 50`) is kept in the same family. The allocator's priority-descending sort in Passes
A and B guarantees this within a family. Cross-family ordering is governed by policy caps, not
priority, so a `priority=90` docs block can be excluded if the docs cap is exhausted and the
borrow pool is consumed by higher-priority blocks in other families — this is expected behavior,
not a bug.

## What is not evaluated here

- Compression quality (summary accuracy, fact preservation) — requires human or model-based
  evaluation outside this codebase.
- Retrieval quality — this service does not retrieve docs; the caller supplies candidate blocks.
- Latency under load.
