"""Tests for cost estimation and daily aggregation — no file I/O, no network."""
from __future__ import annotations
import pytest
from src.cost.ledger import estimate_cost, aggregate

# ── canned prices dict (no YAML file needed) ──────────────────────────────────

PRICES = {
    "models": {
        # Ollama — free
        "qwen3.5:0.8b":  {"in_per_1k": 0.0,      "out_per_1k": 0.0},
        "granite4.1:3b": {"in_per_1k": 0.0,      "out_per_1k": 0.0},
        # Cloud — estimates
        "agnes-2.5-flash":    {"in_per_1k": 0.0003,  "out_per_1k": 0.0006},
        "gpt-5.6-luna":       {"in_per_1k": 0.0005,  "out_per_1k": 0.0015},
        "gemini-3.7-flash":   {"in_per_1k": 0.0001,  "out_per_1k": 0.0004},
    }
}

# ── estimate_cost ──────────────────────────────────────────────────────────────

def test_ollama_cost_is_zero():
    assert estimate_cost("qwen3.5:0.8b", 1000, 500, PRICES) == 0.0

def test_cloud_cost_arithmetic():
    # 1000 in × 0.0003/1k + 500 out × 0.0006/1k = 0.3 + 0.3 = 0.0003 + 0.0003 = 0.6 ... let me redo
    # cost = (1000/1000)*0.0003 + (500/1000)*0.0006 = 0.0003 + 0.0003 = 0.0006
    result = estimate_cost("agnes-2.5-flash", 1000, 500, PRICES)
    assert abs(result - 0.0006) < 1e-10

def test_openai_cost_arithmetic():
    # (2000/1000)*0.0005 + (1000/1000)*0.0015 = 0.001 + 0.0015 = 0.0025
    result = estimate_cost("gpt-5.6-luna", 2000, 1000, PRICES)
    assert abs(result - 0.0025) < 1e-10

def test_missing_model_returns_none():
    assert estimate_cost("unknown-model-xyz", 100, 50, PRICES) is None

def test_zero_tokens_gives_zero():
    assert estimate_cost("agnes-2.5-flash", 0, 0, PRICES) == 0.0

def test_empty_model_name_returns_none():
    assert estimate_cost("", 100, 50, PRICES) is None

# ── aggregate: basic metrics ──────────────────────────────────────────────────

def _ev(ok=True, cost=0.0, latency_ms=100.0, fallbacks=0, tier="lite", unpriced=False):
    return {
        "ok": ok, "cost": cost, "latency_ms": latency_ms,
        "fallbacks": fallbacks, "tier_used": tier, "unpriced": unpriced,
    }

def test_aggregate_empty():
    result = aggregate([])
    assert result["n"] == 0

def test_aggregate_n():
    events = [_ev(), _ev(), _ev()]
    assert aggregate(events)["n"] == 3

def test_aggregate_fail_rate():
    events = [_ev(ok=True), _ev(ok=False), _ev(ok=True), _ev(ok=False)]
    assert aggregate(events)["fail_rate"] == 0.5

def test_aggregate_fallback_rate():
    events = [_ev(fallbacks=0), _ev(fallbacks=0), _ev(fallbacks=1), _ev(fallbacks=1)]
    assert aggregate(events)["fallback_rate"] == 0.5

def test_aggregate_cost_sum():
    events = [_ev(cost=0.001), _ev(cost=0.002), _ev(cost=0.003)]
    result = aggregate(events)
    assert abs(result["cost_sum"] - 0.006) < 1e-10

def test_aggregate_avg_cost():
    events = [_ev(cost=0.002), _ev(cost=0.004)]
    assert abs(aggregate(events)["avg_cost"] - 0.003) < 1e-10

def test_aggregate_cost_sum_none_when_all_null():
    events = [_ev(cost=None), _ev(cost=None)]
    assert aggregate(events)["cost_sum"] is None

def test_aggregate_avg_cost_none_when_all_null():
    events = [_ev(cost=None), _ev(cost=None)]
    assert aggregate(events)["avg_cost"] is None

def test_aggregate_cost_by_tier():
    events = [
        _ev(cost=0.001, tier="lite"),
        _ev(cost=0.002, tier="heavy"),
        _ev(cost=0.003, tier="heavy"),
    ]
    result = aggregate(events)["cost_by_tier"]
    assert abs(result["lite"] - 0.001) < 1e-10
    assert abs(result["heavy"] - 0.005) < 1e-10

def test_aggregate_p95_latency():
    # 10 events: latencies 10..100 ms (step 10), all ok
    events = [_ev(ok=True, latency_ms=float(i * 10)) for i in range(1, 11)]
    p95 = aggregate(events)["p95_latency_ms"]
    # sorted: [10,20,...,100]; idx = int(10*0.95)=9; s[9]=100
    assert p95 == 100.0

def test_aggregate_p95_excludes_failed():
    # failed events have huge latency — should not skew p95
    events = [_ev(ok=True, latency_ms=50.0)] * 9 + [_ev(ok=False, latency_ms=9999.0)]
    p95 = aggregate(events)["p95_latency_ms"]
    assert p95 == 50.0

def test_aggregate_unpriced_count():
    events = [_ev(unpriced=True), _ev(unpriced=False), _ev(unpriced=True)]
    assert aggregate(events)["unpriced_count"] == 2

def test_aggregate_all_zeros_ok():
    events = [_ev(ok=True, cost=0.0, latency_ms=10.0)]
    result = aggregate(events)
    assert result["fail_rate"] == 0.0
    assert result["fallback_rate"] == 0.0
    assert result["cost_sum"] == 0.0
    assert result["p95_latency_ms"] == 10.0
