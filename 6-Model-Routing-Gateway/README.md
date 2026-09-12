# Model Routing Gateway

Routes LLM requests across three cost tiers, retries failed calls, and records estimated cost and latency for every request. Unit economics are part of the design.

---

## Three tiers

| Tier | Role | Targets (in order) |
|------|------|--------------------|
| `lite` | Short, cheap, low-risk | `qwen3.5:0.8b` (Ollama) |
| `mid` | Default production | `qwen3.5:2b` → `qwen3-vl:2b` (vision) → `granite4.1:3b` |
| `heavy` | Hard / long / structured | `agnes-2.5-flash` → `gpt-5.6-luna` → `gemini-3.7-flash` → `granite4.1:3b` |

Promotion is **upward only** (lite → mid → heavy). The gateway never falls back to a cheaper tier.

---

## 30-second demo

**Route a simple greeting (lite tier):**

```cmd
uv run python -m src.gateway --text "Hi there, how are you?"
```

Expected: `"tier_used": "lite"`, `"model": "qwen3.5:0.8b"`

**Route a structured extraction (heavy tier required):**

```cmd
uv run python -m src.gateway --text "Extract all line items, quantities, prices and totals from this invoice into structured output as a json schema format." --need-json
```

Expected: `"tier_used"` is `"mid"` or `"heavy"` (never `"lite"`; hard+need_json blocks it).

**Daily cost summary:**

```cmd
uv run python -m src.cost --day today
```

**Run the routing eval (merge gate, no GPU):**

```cmd
uv run python -m src.route.eval --fail-on-mismatch
```

---

## How routing works

```
caller            gateway                        model
  │                  │                              │
  │  route(prompt)   │                              │
  │─────────────────>│                              │
  │                  │── score complexity ──────────│
  │                  │── pick tier + target ────────│
  │                  │── call first target ─────────│
  │                  │◄── reply or error ───────────│
  │                  │── on failure: next target ───│
  │                  │── on tier exhausted: promote─│
  │                  │── write UsageEvent JSONL ────│
  │◄─ GatewayResponse│                              │
```

Hard routing rules (in code, not config):
- `complexity==hard` AND `need_json` → lite ineligible
- `has_image` → only `vision_ok` targets eligible

---

## Cost

Estimated from `config/prices.yaml`; not read from invoices. All non-zero rates are labeled `# estimate`. Local Ollama calls cost $0.00.

```
cost = (in_tokens / 1000) * in_per_1k + (out_tokens / 1000) * out_per_1k
```

---

## Start

```cmd
cd D:\ai-projects\6-Model-Routing-Gateway
run.cmd          # syncs deps, loads .env, warns if Ollama is down, opens Streamlit
```

Browser opens at `http://localhost:8501`.

If Ollama is down, local (lite/mid) targets are skipped. Cloud (heavy) targets are used when the relevant API keys are set.

---

## API keys (optional)

Create a `.env` file in the project root:

```
AGNES_API_KEY=...
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://...
GOOGLE_API_KEY=...
OLLAMA_HOST=http://localhost:11434   # optional; default shown
```

When a key is missing, that provider is silently skipped.

---

## CLI

```cmd
uv run python -m src.gateway --text "..." [--need-json] [--tier lite|mid|heavy]
uv run python -m src.cost --day today
uv run python -m src.route.eval --fail-on-mismatch
uv run pytest tests/ -q
```

---

## Requirements

- Python 3.11+ and `uv` (`winget install astral-sh.uv`)
- No GPU required for routing logic; RTX 4060 8 GB used only for local Ollama models

---

## Layout

```
src/
  gateway/     GatewayRequest · FeatureExtractor · GatewayResponse · CLI
  route/       route() · executor() · eval runner
  providers/   ollama · agnes · openai_compat · gemini · availability
  cost/        estimate_cost() · log_event() · aggregate() · CLI
  ui/          Streamlit front-end (run.cmd)
config/
  tiers.yaml   Tier → ordered target list with timeouts and vision flags
  prices.yaml  Per-model token rates (all non-zero = estimates)
  features.yaml  Keyword groups, token buckets, complexity thresholds
logs/usage/    Per-request JSONL (YYYYMMDD.jsonl)
tests/
  test_gateway.py    29 checks — request + feature extraction
  test_router.py     22 checks — routing decisions
  test_executor.py   22 checks — fallback loop
  test_cost.py       19 checks — cost arithmetic
  eval/routes.jsonl  5 routing eval cases (merge gate)
docs/          ARCHITECTURE.md  TECHNICAL.md  TIERS.md  COST.md  RUNBOOK.md  EVAL.md
```

---

## Known limitations

- Cost figures are config-driven estimates (`config/prices.yaml`), never reconciled against real invoices; see `docs/COST.md`.
- Retry is limited to one attempt on a 5xx response, per target, inside each provider adapter (`src/providers/*.py`). There is no exponential backoff and no retry on other error classes.
- "One Ollama model resident at a time" (RTX 4060 8 GB) is an operational constraint from `.claude/CLAUDE.md`; the router does not enforce or check GPU memory.
- The Streamlit UI has no authentication; anyone who can reach `http://localhost:8501` can view the Dashboard and the Config tab, which prints the raw contents of `config/tiers.yaml` and `config/prices.yaml`.
- No CI is configured in this repository (no `.github/workflows`); `pytest` and the routing eval are run manually per `docs/RUNBOOK.md`.
- The routing eval (`tests/eval/routes.jsonl`) checks routing decisions only. It does not evaluate actual model output quality, real provider latency, or cost accuracy against real invoices; see `docs/EVAL.md`.

---

## Contributing

No `docs/CONTRIBUTING.md`; there is no CI, no branch policy, and no formal review process in this repository to document; it currently has a single maintainer. If that changes, add branch and test expectations here once they exist.

---

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
