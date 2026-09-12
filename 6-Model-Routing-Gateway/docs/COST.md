# Cost

Cost is **estimated from config**, never read from invoices. Every non-zero rate in `config/prices.yaml` is labeled `# estimate`.

---

## Formula

```
cost = (in_tokens / 1000) * in_per_1k
     + (out_tokens / 1000) * out_per_1k
```

`in_tokens` and `out_tokens` come from the provider response when reported, or from tiktoken `cl100k_base` approximation when not.

---

## prices.yaml structure

```yaml
currency: USD
unit: tokens

models:
  <model-name>:
    provider: <ollama|agnes|openai|gemini>
    in_per_1k: <USD per 1 000 input tokens>
    out_per_1k: <USD per 1 000 output tokens>
```

All Ollama models have `in_per_1k: 0.0` and `out_per_1k: 0.0`. Local inference has no API cost; electricity is not metered.

**If a model is absent from `prices.yaml`:** `estimate_cost()` returns `None`, the JSONL event records `cost: null` and `unpriced: true`. The daily aggregator tracks `unpriced_count` separately.

---

## Current rates (all non-zero are estimates)

| Model | in_per_1k (USD) | out_per_1k (USD) | Note |
|-------|----------------|-----------------|------|
| `qwen3.5:0.8b` | 0.0 | 0.0 | Ollama; free |
| `qwen3.5:2b` | 0.0 | 0.0 | Ollama; free |
| `qwen3-vl:2b` | 0.0 | 0.0 | Ollama; free |
| `granite4.1:3b` | 0.0 | 0.0 | Ollama; free |
| `agnes-2.5-flash` | 0.0003 | 0.0006 | estimate |
| `gpt-5.6-luna` | 0.0005 | 0.0015 | estimate |
| `gpt-5.6-terra` | 0.0003 | 0.0009 | estimate |
| `gemini-3.5-flash-lite` | 0.000075 | 0.0003 | estimate |
| `gemini-3.7-flash` | 0.0001 | 0.0004 | estimate |

---

## JSONL event fields (one per request)

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | str | UUID |
| `ts` | str | ISO-8601 UTC |
| `tier_planned` | str | tier selected by router |
| `tier_used` | str | tier that actually responded |
| `model` | str | model name |
| `provider` | str | provider name |
| `in_tokens` | int | input token count |
| `out_tokens` | int | output token count |
| `approximate` | bool | true when tiktoken was used, not provider-reported |
| `latency_ms` | float | wall-clock from execute() call to first reply |
| `fallbacks` | int | number of targets skipped before success |
| `ok` | bool | true = successful reply |
| `reason` | str \| null | error message when ok=false |
| `cost` | float \| null | null = UNPRICED (model absent from prices.yaml) |
| `unpriced` | bool | true when ok=true and cost is null |

Log path: `logs/usage/YYYYMMDD.jsonl` (one file per UTC day).

---

## Aggregator

```cmd
uv run python -m src.cost --day today
```

Output fields:

| Field | Description |
|-------|-------------|
| `n` | total events |
| `fail_rate` | fraction where ok=false |
| `fallback_rate` | fraction where fallbacks > 0 |
| `cost_sum` | total estimated cost (USD); excludes unpriced events |
| `cost_by_tier` | cost breakdown by tier (excludes unpriced) |
| `avg_cost` | mean cost per request (excludes unpriced) |
| `p95_latency_ms` | 95th-percentile latency (ok=true events only) |
| `unpriced_count` | events where ok=true and cost is null |

---

## Token counting

Provider-reported token counts are used when available:
- **Ollama**: `prompt_eval_count` (in) / `eval_count` (out)
- **Agnes / OpenAI-compatible**: `usage.prompt_tokens` / `usage.completion_tokens`
- **Gemini**: `usageMetadata.promptTokenCount` / `usageMetadata.candidatesTokenCount`

When a provider does not return counts, tiktoken `cl100k_base` is used and `UsageRecord.approximate = true`.
