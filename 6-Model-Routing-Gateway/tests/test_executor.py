"""Tests for the execute loop — all offline, fake provider injection."""
from __future__ import annotations
import pytest
from src.gateway.models import GatewayRequest, RouteDecision, ReasonCode
from src.providers.base import ProviderError, ProviderResult
from src.route.executor import execute

# ── minimal tiers config ──────────────────────────────────────────────────────

def _tgt(provider, model, timeout_s=60):
    return {
        "provider": provider, "model": model,
        "timeout_s": timeout_s, "vision_ok": False,
        "max_input_tokens": 4096,
        "allowed_when": {"min_score": 0.0, "max_score": 1.0, "flags": []},
    }

TIERS = {
    "tiers": {
        "lite": {"targets": [_tgt("p1", "m1", 30)], "fallbacks": ["mid"]},
        "mid":  {"targets": [_tgt("p2", "m2", 60)], "fallbacks": []},
    }
}

# ── helpers ───────────────────────────────────────────────────────────────────

def _decision(provider="p1", model="m1", tier="lite", chain=None):
    return RouteDecision(
        status="ok", tier=tier, provider=provider, model=model,
        reason_codes=[ReasonCode.AUTO_SELECTED],
        fallback_chain=chain or [],
    )

def _ok_fn(text="hello"):
    def fn(provider, model, request, timeout_s):
        return ProviderResult(text=text, in_tokens=5, out_tokens=3, approximate=False)
    return fn

def _fail_fn(error="timeout"):
    def fn(provider, model, request, timeout_s):
        raise ProviderError(error)
    return fn

def _fail_then_ok(text="fallback reply"):
    calls = [0]
    def fn(provider, model, request, timeout_s):
        calls[0] += 1
        if calls[0] == 1:
            raise ProviderError("first call fails")
        return ProviderResult(text=text, in_tokens=4, out_tokens=2, approximate=False)
    return fn

# ── basic success ─────────────────────────────────────────────────────────────

def test_success_ok():
    req = GatewayRequest(id="x", user_text="Hello")
    assert execute(_decision(), req, TIERS, _ok_fn()).ok is True

def test_success_text():
    req = GatewayRequest(id="x", user_text="Hello")
    assert execute(_decision(), req, TIERS, _ok_fn("the answer")).text == "the answer"

def test_success_one_attempt():
    req = GatewayRequest(id="x", user_text="Hello")
    resp = execute(_decision(), req, TIERS, _ok_fn())
    assert len(resp.attempts) == 1 and resp.attempts[0].ok is True

def test_success_usage_recorded():
    req = GatewayRequest(id="x", user_text="Hello")
    resp = execute(_decision(), req, TIERS, _ok_fn())
    assert resp.usage is not None
    assert resp.usage.in_tokens == 5
    assert resp.usage.out_tokens == 3

def test_success_tier_used():
    req = GatewayRequest(id="x", user_text="Hello")
    assert execute(_decision(tier="lite"), req, TIERS, _ok_fn()).tier_used == "lite"

def test_success_provider_model():
    req = GatewayRequest(id="x", user_text="Hello")
    resp = execute(_decision(provider="p1", model="m1"), req, TIERS, _ok_fn())
    assert resp.provider == "p1" and resp.model == "m1"

# ── fallback: first fails → second succeeds ───────────────────────────────────

def test_fallback_second_succeeds():
    req = GatewayRequest(id="x", user_text="Hello")
    resp = execute(_decision(chain=["p2:m2"]), req, TIERS, _fail_then_ok("fallback reply"))
    assert resp.ok is True and resp.text == "fallback reply"

def test_fallback_two_attempts_recorded():
    req = GatewayRequest(id="x", user_text="Hello")
    assert len(execute(_decision(chain=["p2:m2"]), req, TIERS, _fail_then_ok()).attempts) == 2

def test_fallback_first_attempt_not_ok():
    req = GatewayRequest(id="x", user_text="Hello")
    resp = execute(_decision(chain=["p2:m2"]), req, TIERS, _fail_then_ok())
    assert resp.attempts[0].ok is False and resp.attempts[1].ok is True

def test_fallback_error_recorded_in_attempt():
    req = GatewayRequest(id="x", user_text="Hello")
    resp = execute(_decision(chain=["p2:m2"]), req, TIERS, _fail_then_ok())
    assert resp.attempts[0].error is not None

def test_fallback_provider_model_from_chain():
    req = GatewayRequest(id="x", user_text="Hello")
    resp = execute(_decision(chain=["p2:m2"]), req, TIERS, _fail_then_ok())
    assert resp.provider == "p2" and resp.model == "m2"

# ── all fail ─────────────────────────────────────────────────────────────────

def test_all_fail_ok_false():
    req = GatewayRequest(id="x", user_text="Hello")
    assert execute(_decision(chain=["p2:m2"]), req, TIERS, _fail_fn()).ok is False

def test_all_fail_error_set():
    req = GatewayRequest(id="x", user_text="Hello")
    assert execute(_decision(chain=["p2:m2"]), req, TIERS, _fail_fn()).error is not None

def test_all_fail_attempts_recorded():
    req = GatewayRequest(id="x", user_text="Hello")
    resp = execute(_decision(chain=["p2:m2"]), req, TIERS, _fail_fn())
    assert len(resp.attempts) == 2 and all(not a.ok for a in resp.attempts)

def test_no_fallback_one_attempt_on_fail():
    req = GatewayRequest(id="x", user_text="Hello")
    resp = execute(_decision(), req, TIERS, _fail_fn())
    assert resp.ok is False and len(resp.attempts) == 1

# ── routing failure ───────────────────────────────────────────────────────────

def test_unavailable_decision_not_ok():
    req = GatewayRequest(id="x", user_text="Hello")
    assert execute(RouteDecision(status="unavailable"), req, TIERS, _ok_fn()).ok is False

def test_unsupported_decision_not_ok():
    req = GatewayRequest(id="x", user_text="Hello")
    assert execute(RouteDecision(status="unsupported"), req, TIERS, _ok_fn()).ok is False

# ── empty response treated as failure ─────────────────────────────────────────

def test_empty_response_falls_to_fallback():
    req = GatewayRequest(id="x", user_text="Hello")
    calls = [0]
    def fn(provider, model, request, timeout_s):
        calls[0] += 1
        return ProviderResult(text="" if calls[0] == 1 else "good",
                              in_tokens=1, out_tokens=1, approximate=False)
    resp = execute(_decision(chain=["p2:m2"]), req, TIERS, fn)
    assert resp.ok is True and resp.text == "good"

# ── need_json validation ──────────────────────────────────────────────────────

def test_need_json_invalid_falls_to_fallback():
    req = GatewayRequest(id="x", user_text="Hello", need_json=True)
    calls = [0]
    def fn(provider, model, request, timeout_s):
        calls[0] += 1
        return ProviderResult(
            text="not json" if calls[0] == 1 else '{"ok": true}',
            in_tokens=1, out_tokens=1, approximate=False,
        )
    resp = execute(_decision(chain=["p2:m2"]), req, TIERS, fn)
    assert resp.ok is True and resp.text == '{"ok": true}'

def test_need_json_valid_succeeds():
    req = GatewayRequest(id="x", user_text="Hello", need_json=True)
    assert execute(_decision(), req, TIERS, _ok_fn('{"answer": 42}')).ok is True

# ── latency + usage approximate flag ─────────────────────────────────────────

def test_latency_recorded():
    req = GatewayRequest(id="x", user_text="Hello")
    resp = execute(_decision(), req, TIERS, _ok_fn())
    assert resp.attempts[0].latency_ms >= 0

def test_usage_approximate_flag_preserved():
    req = GatewayRequest(id="x", user_text="Hello")
    def fn(p, m, r, t):
        return ProviderResult(text="hi", in_tokens=3, out_tokens=2, approximate=True)
    resp = execute(_decision(), req, TIERS, fn)
    assert resp.usage.approximate is True
