# Runbook

Operational reference for the Model Routing Gateway.

---

## Start

```cmd
cd D:\ai-projects\6-Model-Routing-Gateway
run.cmd
```

`run.cmd` creates the venv if absent, syncs deps, loads `.env`, warns if Ollama is unreachable (non-fatal), then opens Streamlit at `http://localhost:8501`.

---

## Environment variables

Create `.env` in the project root:

```
AGNES_API_KEY=...
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://...
GOOGLE_API_KEY=...
OLLAMA_HOST=http://localhost:11434   # optional; this is the default
```

**Missing key = that provider is silently skipped.** No crash. The executor moves to the next target in the fallback chain.

---

## CLI commands

```cmd
# Send a single prompt
uv run python -m src.gateway --text "..." [--need-json] [--tier lite|mid|heavy] [--system "..."]

# Daily cost/usage summary
uv run python -m src.cost --day today

# Routing eval — merge gate; must pass before merging routing changes
uv run python -m src.route.eval --fail-on-mismatch [--cases tests/eval/routes.jsonl]

# Full test suite (92 checks, no GPU/API required)
uv run pytest tests/ -q
```

---

## Diagnosing a failed request

`GatewayResponse.ok == False` means all targets in the fallback chain failed. Check:

1. **`response.attempts`**; each `AttemptRecord` has `provider`, `model`, `ok`, `error`, `latency_ms`.
2. **Common errors:**

| Error | Cause | Fix |
|-------|-------|-----|
| `MissingKeyError` | Required API key absent | Set the env var in `.env` |
| `ProviderError: HTTP 5xx` | Provider returned server error | Wait and retry; single retry is already attempted |
| `ProviderError: empty response` | Model returned blank text | Check model is loaded in Ollama; try a different tier |
| `ProviderError: invalid JSON` | `need_json=true` but response was not valid JSON | Heavy tier is more reliable for structured output |
| `routing: unsupported` | `has_image=true` but no vision target was available | Start Ollama with `qwen3-vl:2b` or set `GOOGLE_API_KEY` |
| `routing: unavailable` | All targets for the resolved tier unavailable | Check API keys; start Ollama |

---

## Ollama is down

Lite and mid Ollama targets are skipped automatically. Cloud-only path still works if at least one API key is set. The warning `[WARN] Ollama not reachable at ...` from `run.cmd` is non-fatal.

To check what is running:
```cmd
curl http://localhost:11434/api/tags
```

One model at a time on RTX 4060 8 GB. Unload a model before loading another:
```cmd
ollama stop <model-name>
ollama run <new-model-name>
```

---

## Routing eval (merge gate)

```cmd
uv run python -m src.route.eval --fail-on-mismatch
```

Runs 5 deterministic cases from `tests/eval/routes.jsonl`. Uses `ALL_AVAILABLE = lambda p, m: True`; no GPU or API keys required. Exit code 1 if any case fails. Run this before merging any change to `router.py`, `features.py`, `features.yaml`, or `tiers.yaml`.

---

## Logs

Location: `logs/usage/YYYYMMDD.jsonl` (one file per UTC day, gitignored).

```cmd
# View today's events
type logs\usage\<today>.jsonl

# Aggregate today's stats
uv run python -m src.cost --day today
```

`cost: null` with `unpriced: true` means a successful call to a model absent from `prices.yaml`. Add the model to `config/prices.yaml` to start tracking cost.

---

## Adding a new model or provider

1. Add the model to `config/tiers.yaml` under the appropriate tier.
2. Add a pricing entry to `config/prices.yaml` (label non-zero rates `# estimate`).
3. If it is an Ollama model, add it to the allowed list in `.claude/CLAUDE.md`.
4. If it is a new provider, add a `complete()` adapter in `src/providers/`.
5. Run `uv run pytest tests/ -q` and `uv run python -m src.route.eval --fail-on-mismatch`.

---

## Key files

| File | Purpose |
|------|---------|
| `config/tiers.yaml` | Tier → ordered target list |
| `config/prices.yaml` | Per-model token rates |
| `config/features.yaml` | Keyword groups, token buckets, scoring weights |
| `src/route/router.py` | `route()`; tier selection and fallback chain |
| `src/route/executor.py` | `execute()`; provider calls and fallback loop |
| `src/cost/ledger.py` | `log_event()`, `aggregate()`, `estimate_cost()` |
| `logs/usage/` | Per-request JSONL events |
