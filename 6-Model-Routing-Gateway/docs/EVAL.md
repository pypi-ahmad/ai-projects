# Routing Eval

The routing eval is a **merge gate for routing logic** — no GPU, no API keys, no running models required. It tests that `route()` + `FeatureExtractor` produce the correct tier, model, and status for a fixed set of cases.

---

## Running the eval

```cmd
uv run python -m src.route.eval --fail-on-mismatch
```

Exit 0 = all cases pass. Exit 1 = one or more mismatches (CI gate).

Optional flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--fail-on-mismatch` | off | Exit 1 if any case fails |
| `--cases <path>` | `tests/eval/routes.jsonl` | Path to a different case file |

---

## How it works

1. Loads `config/features.yaml` and `config/tiers.yaml`.
2. Reads cases from `tests/eval/routes.jsonl` (one JSON object per line).
3. For each case: builds a `GatewayRequest`, runs `FeatureExtractor.extract()`, calls `route()` with `availability = lambda p, m: True` — all targets treated as available so availability is not under test.
4. Checks assertions (`expected_tier`, `expected_not_tier`, `expected_model`, `expected_status`).
5. Prints per-case `[PASS]` / `[FAIL]` with tier, model, complexity score, and label.
6. Prints summary `N/N passed`.

---

## Case format (`tests/eval/routes.jsonl`)

One JSON object per line. All assertion fields are optional — include only those relevant to the case.

```jsonc
{
  "id": "case-name",
  "description": "Human-readable explanation of what this case tests.",
  "user_text": "The prompt text.",
  "need_json": false,
  "flags": { "has_image": false },       // RequestFlags fields
  "preferred_tier": "heavy",             // optional — simulates explicit tier override
  "disallow_tiers": ["lite"],            // optional — tiers to exclude
  "expected_tier": "lite",              // assert decision.tier == value
  "expected_not_tier": "lite",          // assert decision.tier != value
  "expected_model": "qwen3-vl:2b",      // assert decision.model == value
  "expected_status": "ok"               // assert decision.status == value
}
```

---

## Current cases (5/5 pass)

| ID | What it tests | Assertion |
|----|--------------|-----------|
| `lite-greeting` | Short greeting scores simple → routes to lite | `expected_tier: "lite"` |
| `hard-json-not-lite` | hard + need_json hard rule blocks lite | `expected_not_tier: "lite"` |
| `vision-routes-qwen-vl` | `has_image` skips non-vision targets; first vision target selected | `expected_model: "qwen3-vl:2b"` |
| `preferred-heavy-honored` | `preferred_tier=heavy` overrides complexity auto-select | `expected_tier: "heavy"` |
| `disallow-lite-skips-to-mid` | `disallow_tiers=["lite"]` forces mid or higher | `expected_not_tier: "lite"` |

---

## Output format

```
  [PASS] lite-greeting  tier=lite, model=qwen3.5:0.8b, score=0.05 (simple)
  [FAIL] hard-json-not-lite  tier=lite, model=qwen3.5:0.8b, score=0.66 (hard)
         ✗ tier='lite', expected NOT 'lite'

5/5 passed
```

---

## Adding a case

1. Append a JSON line to `tests/eval/routes.jsonl`.
2. Run `uv run python -m src.route.eval --fail-on-mismatch` to verify.
3. If the case fails, check whether the routing or scoring logic needs fixing, or the case expectation is wrong.

Use `expected_not_tier` over `expected_tier` when multiple tiers are acceptable — it is more robust to future tier additions.

---

## What this eval does not cover

- Actual model output quality — requires human or model-based evaluation.
- Provider availability — all targets are treated as available (`lambda p, m: True`).
- Real latency — no provider calls are made.
- Cost accuracy against invoices — rates in `config/prices.yaml` are estimates.
- Token approximation quality — tiktoken is deterministic but not exact for all models.
