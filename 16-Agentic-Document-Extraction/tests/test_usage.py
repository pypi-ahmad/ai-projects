"""Tests for src.usage's token/cost accounting -- recording, totals, reset,
and per-model cost math (cached vs. non-cached input rates), including that
switching models mid-session doesn't reprice already-recorded calls.

Next: src/usage.py.
"""

from __future__ import annotations

from src import usage
import pytest


def test_record_and_totals():
    usage.reset()
    usage.record("extract_invoice", "gpt-5.6-terra", {
        "input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200,
        "input_token_details": {"cache_read": 300},
    })
    usage.record("parse_page", "gpt-5.6-terra", {
        "input_tokens": 500, "output_tokens": 100, "total_tokens": 600,
    })

    entries = usage.get_all()
    assert len(entries) == 2

    totals = usage.totals()
    assert totals == {"input_tokens": 1500, "output_tokens": 300, "cached_tokens": 300}


def test_record_handles_missing_usage_metadata():
    usage.reset()
    usage.record("extract_regions", "gpt-5.6-terra", None)

    assert usage.totals() == {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}


def test_reset_clears_entries():
    usage.reset()
    usage.record("x", "gpt-5.6-terra", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
    usage.reset()
    assert usage.get_all() == []


def test_cost_usd_uses_non_cached_and_cached_input_rates():
    # 1M non-cached input ($2.00) + 1M cached input ($0.20) + 1M output ($12.00)
    totals = {"input_tokens": 2_000_000, "output_tokens": 1_000_000, "cached_tokens": 1_000_000}
    assert usage.cost_usd(totals) == 2.00 + 0.20 + 12.00


def test_mixed_model_cost_does_not_reprice_previous_calls():
    counts = dict(input_tokens=2_000_000, cached_tokens=1_000_000, output_tokens=1_000_000)
    entries = [dict(counts, model="gpt-5.6-terra"), dict(counts, model="gpt-5.6-luna")]
    assert usage.cost_usd(counts, "gpt-5.6-luna") == pytest.approx(1.42)
    assert usage.session_cost_usd(entries) == pytest.approx(15.62)
    assert usage.session_cost_usd(entries[:1]) == pytest.approx(14.20)
