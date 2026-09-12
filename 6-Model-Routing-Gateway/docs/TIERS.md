# Tiers

Three tiers route requests from cheapest/fastest to most capable. Promotion is **upward only**: lite → mid → heavy. The gateway never falls back to a cheaper tier.

---

## Tier definitions

### lite — Short, cheap, low-risk tasks

| Field | Value |
|-------|-------|
| Target | `ollama / qwen3.5:0.8b` |
| Max input tokens | 4 096 |
| Timeout | 30 s |
| Vision | No |
| Fallback | → mid |

**When lite is ineligible (hard rules):**
- `complexity_label == "hard"` AND `need_json == true` — hard + structured-output requests are never sent to lite regardless of preferred_tier or score thresholds.
- `flags.has_image == true` — lite has no vision-capable target.

---

### mid — Default production tasks

Targets are tried in order; first available wins:

| # | Provider | Model | Max tokens | Timeout | Vision |
|---|----------|-------|-----------|---------|--------|
| 1 | ollama | `qwen3.5:2b` | 8 192 | 60 s | No |
| 2 | ollama | `qwen3-vl:2b` | 4 096 | 60 s | **Yes** |
| 3 | ollama | `granite4.1:3b` | 8 192 | 60 s | No |

`qwen3-vl:2b` is the **only mid-tier vision target**. When `flags.has_image` is true, targets 1 and 3 are skipped automatically and `qwen3-vl:2b` is selected.

Fallback: → heavy

---

### heavy — Hard / long / structured-output tasks

Targets are tried in order; first available wins:

| # | Provider | Model | Max tokens | Timeout | Vision |
|---|----------|-------|-----------|---------|--------|
| 1 | agnes | `agnes-2.5-flash` | 32 768 | 120 s | No |
| 2 | openai | `gpt-5.6-luna` | 32 768 | 120 s | No |
| 3 | gemini | `gemini-3.7-flash` | 32 768 | 120 s | **Yes** |
| 4 | ollama | `granite4.1:3b` | 8 192 | 60 s | No |

Target 4 (`granite4.1:3b`) is the cloud-key-absent last resort. It is skipped when any cloud key is set and that provider is reachable.

Fallback: none. If all heavy targets fail, `GatewayResponse(ok=False)` is returned.

---

## Hard routing rules (enforced in code, not config)

| Condition | Effect |
|-----------|--------|
| `complexity_label == "hard"` AND `need_json == true` | Lite targets ineligible; routing starts at mid |
| `flags.has_image == true` | Only `vision_ok: true` targets eligible across all tiers; if none is available → `status = "unsupported"` |

---

## Availability check

`default_available(provider, model)` is called at routing time:
- **ollama**: checks `OLLAMA_HOST/api/tags` (default `http://localhost:11434`); target skipped if unreachable or model not in tag list.
- **agnes**: target skipped if `AGNES_API_KEY` is not set.
- **openai**: target skipped if `OPENAI_API_KEY` is not set.
- **gemini**: target skipped if `GOOGLE_API_KEY` is not set.

A missing key is never a crash — that target is silently omitted from the fallback chain.

---

## preferred_tier and disallow_tiers

- `preferred_tier`: router starts at the specified tier, bypassing complexity-based auto-selection. Hard rules still apply.
- `disallow_tiers`: list of tier names to exclude. The router starts at the first non-excluded tier.
