"""Per-model USD/1k-token pricing, loaded from config/prices.yaml.

Unknown model -> (None, "UNPRICED"). Never invents a rate. Must not know
about spans/traces/export formats - export/common.py is the only caller
that bridges this to a Span. `_cache` is process-lifetime state populated
on first use; tests that change cwd (see tests/test_api.py) must call
clear_prices_cache() or they'll read a stale table from a previous cwd.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

PRICES_PATH = Path("config/prices.yaml")

PricingStatus = Literal["PRICED", "UNPRICED"]


class ModelRate(BaseModel):
    in_per_1k: float
    out_per_1k: float


def load_prices(path: Path = PRICES_PATH) -> dict[str, ModelRate]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = data.get("models", {})
    return {name: ModelRate(**rate) for name, rate in models.items()}


_cache: dict[str, ModelRate] | None = None


def get_prices() -> dict[str, ModelRate]:
    global _cache  # noqa: PLW0603 - simple lazy-loaded module cache
    if _cache is None:
        _cache = load_prices()
    return _cache


def clear_prices_cache() -> None:
    """For test isolation: a stale cache from a chdir'd test would otherwise
    leak into every later test in the same process."""
    global _cache  # noqa: PLW0603 - simple lazy-loaded module cache
    _cache = None


def estimate_cost(
    model: str | None,
    in_tokens: int | None,
    out_tokens: int | None,
    *,
    existing_cost: float | None = None,
    prices: dict[str, ModelRate] | None = None,
) -> tuple[float | None, PricingStatus]:
    """Cost for a model/token pair, or (None, "UNPRICED") if the model has no known rate.

    existing_cost: an already-computed cost_est (e.g. set by the caller via
    span.set_usage(cost_est=...)) is trusted as-is and reported "PRICED".
    """
    if existing_cost is not None:
        return existing_cost, "PRICED"
    rates = prices if prices is not None else get_prices()
    rate = rates.get(model) if model else None
    if rate is None:
        return None, "UNPRICED"
    cost = (in_tokens or 0) / 1000 * rate.in_per_1k + (out_tokens or 0) / 1000 * rate.out_per_1k
    return cost, "PRICED"
