"""Token/cost accounting using explicitly owned per-run ledgers.
The graph owns its ledger; the UI accumulates completed runs per session.

Must not: treat a missing/partial usage report as zero tokens -- see the
`usage_known` flag threaded through `record()`, which keeps a genuinely
unreported call visibly distinct from a legitimately empty one so the UI's
cost estimate doesn't silently under-report.

Next: src/models.py for the per-model rate table this multiplies against.
"""

from __future__ import annotations
from src.models import DEFAULT_MODEL, MODEL_RATES

# Backward-compatible default rates.
(
    PRICE_PER_1M_INPUT,
    PRICE_PER_1M_CACHED_INPUT,
    PRICE_PER_1M_CACHE_WRITE,
    PRICE_PER_1M_OUTPUT,
) = MODEL_RATES[DEFAULT_MODEL]


def record(call: str, model: str, usage_metadata: dict | None, *,
           usage_known: bool | None = None, entries: list[dict] | None = None) -> dict:
    known = usage_metadata is not None if usage_known is None else usage_known
    usage_metadata = usage_metadata or {}
    input_tokens = usage_metadata.get("input_tokens", 0) or 0
    output_tokens = usage_metadata.get("output_tokens", 0) or 0
    input_details = usage_metadata.get("input_token_details") or {}
    cached_tokens = input_details.get("cache_read", 0) or 0
    cache_write_tokens = input_details.get("cache_write", 0) or 0
    entry = {
        "call": call,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "usage_known": known,
    }
    if entries is not None:
        entries.append(entry)
    return entry


def totals(entries: list[dict]) -> dict:
    return {
        "input_tokens": sum(e["input_tokens"] for e in entries),
        "output_tokens": sum(e["output_tokens"] for e in entries),
        "cached_tokens": sum(e["cached_tokens"] for e in entries),
        "cache_write_tokens": sum(e.get("cache_write_tokens", 0) for e in entries),
    }


def cost_usd(totals_dict: dict, model: str = DEFAULT_MODEL) -> float:
    """Cost in USD for a totals dict as returned by `totals()`.

    `input_tokens` already includes cached and cache-write tokens, so the
    ordinary-input portion excludes both.
    """
    cached = totals_dict.get("cached_tokens", 0)
    cache_write = totals_dict.get("cache_write_tokens", 0)
    input_rate, cached_rate, cache_write_rate, output_rate = MODEL_RATES[model]
    non_cached_input = max(totals_dict["input_tokens"] - cached - cache_write, 0)
    return (
        non_cached_input * input_rate
        + cached * cached_rate
        + cache_write * cache_write_rate
        + totals_dict["output_tokens"] * output_rate
    ) / 1_000_000


def session_cost_usd(entries: list[dict]) -> float:
    return sum(cost_usd(entry, entry.get("model", DEFAULT_MODEL)) for entry in entries)
