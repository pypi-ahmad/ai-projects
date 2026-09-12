# Model Routing Gateway

Windows 11 native. No WSL2. No Docker. Use `uv` for Python.

## Constraints

- Routing and cost estimation require no running model. tiktoken cl100k_base does all token counting.
- RTX 4060 8 GB: one Ollama model resident at a time. Router itself is CPU-only.
- All provider calls are optional. Missing key or unreachable host = target silently skipped.
- Promotion is only upward: lite → mid → heavy. Never downward.
- All non-zero cost rates are labeled estimates. No invoice integration.
- `use_providers=False` path must work in all tests (fake provider injection).

## Allowed Ollama models

- granite4.1:3b
- qwen3.5:2b
- qwen3.5:0.8b
- qwen3-vl:2b
- qwen3-embedding:0.6b
- qwen3-embedding:4b
- translategemma:4b
- AuditAid/PaddleOCR-VL-1.6-0.9B

## Providers

1. Ollama — detect installed models; `OLLAMA_HOST` (default `http://localhost:11434`)
2. Agnes AI — `agnes-2.5-flash`; base `https://apihub.agnes-ai.com/v1`; `AGNES_API_KEY`
3. OpenAI-compatible — `gpt-5.6-luna`, `gpt-5.6-terra`; `OPENAI_API_KEY` + `OPENAI_BASE_URL`
4. Gemini — `gemini-3.5-flash-lite`, `gemini-3.7-flash`; `GOOGLE_API_KEY`

## Layout

```
src/
  gateway/
    models.py       GatewayRequest (Pydantic v2) · RequestFlags · TierName
    features.py     FeatureExtractor · Features · ComplexityLabel
  route/            route() · fallback chain · tier promotion  [Phase 3]
  providers/        ollama · agnes · openai_compat · gemini · base  [Phase 3]
  cost/             load_prices() · estimate_cost() · log_event() · aggregate()
  ui/               Streamlit app  [Phase 4]
config/
  tiers.yaml        tier → ordered target list
  prices.yaml       per-model {in_per_1k, out_per_1k} — Ollama=0, cloud=estimates
  features.yaml     keyword groups · token_weights · feature_weights · thresholds
logs/usage/         per-request JSONL events (gitignored content)
tests/
  test_gateway.py   29 checks — GatewayRequest + FeatureExtractor
  eval/routes.jsonl 5 routing eval cases (merge gate)
docs/               ARCHITECTURE.md  TIERS.md  COST.md  RUNBOOK.md  EVAL.md
```

## Phases

**Phase 1 complete** — scaffold: docs, config stubs, src package stubs, run.cmd stub, .gitignore, pyproject.toml, requirements.txt.

**Phase 2 complete** — `GatewayRequest` (Pydantic v2), `RequestFlags`, `TierName` in `src/gateway/models.py`.
`FeatureExtractor` + `Features` + `ComplexityLabel` in `src/gateway/features.py`.
`config/features.yaml` with keyword groups, token_weights, feature_weights, thresholds.
29 tests in `tests/test_gateway.py` — all offline, 29/29 pass.

**Phase 3 complete** — `ReasonCode` + `RouteDecision` added to `src/gateway/models.py`.
`src/providers/availability.py` — `default_available(provider, model)` checks env vars + Ollama /api/tags.
`src/route/router.py` — `route()` + `load_tiers()`: preferred mode, auto-select, hard rules (hard+need_json→no lite, has_image→vision_ok only), availability checked at decision time, fallback_chain pre-computed.
`config/tiers.yaml` extended with `max_input_tokens`, `timeout_s`, `vision_ok`, `allowed_when`, `fallbacks` per tier.
22 tests in `tests/test_router.py` — all offline (injected availability fns), 51/51 total pass.

**Phase 4 complete** — Provider adapters (`src/providers/ollama.py`, `agnes.py`, `openai_compat.py`, `gemini.py`, `base.py`).
`src/route/executor.py` — `execute()` with fallback loop: primary target + fallback_chain in order; empty/invalid-JSON/ProviderError → next; 5xx retry once per provider; stops on first acceptable reply.
`GatewayResponse`, `AttemptRecord`, `UsageRecord` added to `src/gateway/models.py`.
`src/gateway/__main__.py` — CLI (`python -m src.gateway --text "..." [--need-json] [--tier lite|mid|heavy]`).
22 tests in `tests/test_executor.py` — all offline (fake provider injection), 73/73 total pass.

**Phase 6 complete** — `src/ui/app.py` — Streamlit: Playground (prompt + need_json + tier → decision reasons, attempts table, reply, cost estimate), Dashboard (today JSONL: n/fail_rate/fallback_rate/cost_sum metrics, tier bar chart, cost-by-tier chart), Config tab (read-only tiers.yaml + prices.yaml).
`tests/eval/routes.jsonl` + `src/route/eval.py` — 5 routing eval cases (lite/hard+json/vision/preferred/disallow); `python -m src.route.eval --fail-on-mismatch`; all offline, 5/5 pass.
`run.cmd` — launches Streamlit via `uv run`; warns if Ollama unreachable (non-fatal).
`README.md` — 30-second demo: lite greeting + structured extraction; all CLI commands.

**Phase 5 complete** — `config/prices.yaml` rewritten: per-model `{in_per_1k, out_per_1k}` table (Ollama=0, cloud=estimates labeled clearly).
`src/cost/ledger.py` — `load_prices()`, `estimate_cost(model, in_tokens, out_tokens, prices) -> float|None` (None=UNPRICED), `log_event(...)` appends JSONL to `logs/usage/YYYYMMDD.jsonl`, `aggregate(events) -> dict` (n, fail_rate, fallback_rate, cost_sum, cost_by_tier, avg_cost, p95_latency_ms, unpriced_count).
`src/cost/__main__.py` — aggregator CLI (`python -m src.cost --day today`).
`src/gateway/__main__.py` — calls `log_event` after each execute.
19 tests in `tests/test_cost.py` — arithmetic on canned events, 92/92 total pass.

## Run

```cmd
run.cmd                                               # Streamlit UI at :8501
uv run pytest tests/ -q                              # full suite (92 checks)
uv run python -m src.gateway --text "Hello" --tier lite
uv run python -m src.cost --day today
uv run python -m src.route.eval --fail-on-mismatch   # routing merge gate, 5/5
```
