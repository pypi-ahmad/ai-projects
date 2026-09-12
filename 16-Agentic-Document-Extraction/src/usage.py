"""Process-wide token/cost accounting for every model call the active graph
makes. `reset()` is called once per document run (src/graph.py's
`run_graph`); `record()` is called by every call site in src/extract.py's
`_invoke_structured`. src/ui/app.py reads `get_all()`/`totals()`/
`session_cost_usd()` to show the running session total.

Must not: treat a missing/partial usage report as zero tokens -- see the
`usage_known` flag threaded through `record()`, which keeps a genuinely
unreported call visibly distinct from a legitimately empty one so the UI's
cost estimate doesn't silently under-report.

Next: src/models.py for the per-model rate table this multiplies against.
"""

from __future__ import annotations
from src.models import DEFAULT_MODEL, MODEL_RATES

# Backward-compatible default rates.
PRICE_PER_1M_INPUT, PRICE_PER_1M_CACHED_INPUT, PRICE_PER_1M_OUTPUT = MODEL_RATES[DEFAULT_MODEL]

# ponytail: a plain module-level list, not per-run-isolated state. Safe for
# concurrent *pages within one document* (list.append is atomic under the
# GIL) but not for multiple documents' graphs running concurrently in the
# same process -- this is a single-user desktop tool that runs one document
# at a time, so that's fine. Upgrade to a per-run token/contextvar if that
# ever changes.
_entries: list[dict] = []


def reset() -> None:
    _entries.clear()


def record(call: str, model: str, usage_metadata: dict | None, *, usage_known: bool | None = None) -> None:
    known = usage_metadata is not None if usage_known is None else usage_known
    usage_metadata = usage_metadata or {}
    input_tokens = usage_metadata.get("input_tokens", 0) or 0
    output_tokens = usage_metadata.get("output_tokens", 0) or 0
    cached_tokens = (usage_metadata.get("input_token_details") or {}).get("cache_read", 0) or 0
    _entries.append(
        {
            "call": call,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "usage_known": known,
        }
    )


def get_all() -> list[dict]:
    return list(_entries)


def totals(entries: list[dict] | None = None) -> dict:
    entries = _entries if entries is None else entries
    return {
        "input_tokens": sum(e["input_tokens"] for e in entries),
        "output_tokens": sum(e["output_tokens"] for e in entries),
        "cached_tokens": sum(e["cached_tokens"] for e in entries),
    }


def cost_usd(totals_dict: dict, model: str = DEFAULT_MODEL) -> float:
    """Cost in USD for a totals dict as returned by `totals()`.

    `input_tokens` already includes cached tokens (that's what
    langchain-core's UsageMetadata reports), so the non-cached portion is
    input_tokens - cached_tokens.
    """
    cached = totals_dict["cached_tokens"]
    input_rate, cached_rate, output_rate = MODEL_RATES[model]
    non_cached_input = max(totals_dict["input_tokens"] - cached, 0)
    return (
        non_cached_input * input_rate
        + cached * cached_rate
        + totals_dict["output_tokens"] * output_rate
    ) / 1_000_000


def session_cost_usd(entries: list[dict]) -> float:
    return sum(cost_usd(entry, entry.get("model", DEFAULT_MODEL)) for entry in entries)
