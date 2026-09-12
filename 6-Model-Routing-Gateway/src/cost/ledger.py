"""Cost estimation, usage-event logging, and daily aggregation.

logs/usage/YYYYMMDD.jsonl is the only persistence in this project — one
append-only file per UTC calendar day (see log_event/_load_day below). There
is no cross-day index and no database; `aggregate()` always operates over
whatever event list its caller already loaded from a single day's file.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

_PRICES_PATH = Path("config/prices.yaml")
_LOGS_DIR = Path("logs/usage")


def load_prices(path: Path = _PRICES_PATH) -> dict:
    try:
        with open(path) as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}


def estimate_cost(
    model: str,
    in_tokens: int,
    out_tokens: int,
    prices: dict,
) -> Optional[float]:
    """Return USD cost, or None when the model is absent from prices."""
    entry = prices.get("models", {}).get(model)
    if entry is None:
        return None
    return (in_tokens / 1000) * entry.get("in_per_1k", 0.0) + \
           (out_tokens / 1000) * entry.get("out_per_1k", 0.0)


def log_event(
    request_id: str,
    tier_planned: Optional[str],
    tier_used: Optional[str],
    model: Optional[str],
    provider: Optional[str],
    in_tokens: int,
    out_tokens: int,
    latency_ms: float,
    fallbacks: int,
    ok: bool,
    reason: Optional[str],
    prices: dict,
    logs_dir: Path = _LOGS_DIR,
) -> dict:
    """Append one UsageEvent to today's JSONL and return the event dict."""
    cost = estimate_cost(model or "", in_tokens, out_tokens, prices) if model else None
    unpriced = cost is None and ok  # succeeded but no price known

    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "tier_planned": tier_planned,
        "tier_used": tier_used,
        "model": model,
        "provider": provider,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "cost": cost,
        "unpriced": unpriced,
        "latency_ms": round(latency_ms, 2),
        "fallbacks": fallbacks,
        "ok": ok,
        "reason": reason,
    }

    # Day boundary is UTC, not local time — a request just after local
    # midnight in a timezone ahead of UTC can still land in the *previous*
    # UTC day's file (and vice versa behind UTC). `python -m src.cost --day
    # today` uses the same UTC boundary, so the two stay consistent with
    # each other, just not with a local wall-clock "today".
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    log_file = logs_dir / f"{today}.jsonl"
    logs_dir.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")

    return event


def _p95(values: list[float]) -> float:
    # Nearest-rank percentile (no interpolation between the two closest
    # ranks) — an approximation, not the statistically precise percentile.
    # `min(..., len(s) - 1)` clamps the index so this never reads past the
    # end of the sorted list for small `values`.
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(int(len(s) * 0.95), len(s) - 1)]


def aggregate(events: list[dict]) -> dict:
    """Summarise a list of UsageEvent dicts into daily metrics."""
    n = len(events)
    if n == 0:
        return {"n": 0}

    failed = sum(1 for e in events if not e.get("ok"))
    with_fallbacks = sum(1 for e in events if (e.get("fallbacks") or 0) > 0)
    unpriced = sum(1 for e in events if e.get("unpriced"))

    costs = [e["cost"] for e in events if e.get("cost") is not None]
    latencies = [
        e["latency_ms"]
        for e in events
        if e.get("ok") and e.get("latency_ms") is not None
    ]

    cost_by_tier: dict[str, float] = {}
    for e in events:
        if e.get("cost") is not None:
            tier = e.get("tier_used") or "unknown"
            cost_by_tier[tier] = cost_by_tier.get(tier, 0.0) + e["cost"]

    return {
        "n": n,
        "fail_rate": round(failed / n, 4),
        "fallback_rate": round(with_fallbacks / n, 4),
        "cost_sum": round(sum(costs), 8) if costs else None,
        "cost_by_tier": {k: round(v, 8) for k, v in cost_by_tier.items()},
        "avg_cost": round(sum(costs) / len(costs), 8) if costs else None,
        "p95_latency_ms": round(_p95(latencies), 2),
        "unpriced_count": unpriced,
    }
