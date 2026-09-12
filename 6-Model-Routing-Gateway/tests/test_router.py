"""Tests for the router — no LLM calls, no network, no env keys required.

All availability checks use injected lambdas.
"""
import pytest
import yaml
from pathlib import Path
from pydantic import ValidationError

from src.gateway.models import GatewayRequest, RequestFlags, ReasonCode
from src.gateway.features import Features
from src.route.router import route, load_tiers

# ── fixed Features for router tests (avoids re-testing FeatureExtractor) ─────

SIMPLE = Features(
    n_chars=16, n_tokens_approx=5, n_sentences=1,
    has_code_fence=False, has_json_hint=False, has_question=True,
    keyword_hits=[], complexity_score=0.005, complexity_label="simple",
)
HARD = Features(
    n_chars=600, n_tokens_approx=130, n_sentences=9,
    has_code_fence=False, has_json_hint=True, has_question=False,
    keyword_hits=["schema", "compare", "step_by_step"],
    complexity_score=0.78, complexity_label="hard",
)

# ── minimal tiers config (mirrors real config structure) ──────────────────────

def _t(provider, model, vision_ok=False):
    return {
        "provider": provider, "model": model,
        "max_input_tokens": 8192, "timeout_s": 60,
        "vision_ok": vision_ok,
        "allowed_when": {"min_score": 0.0, "max_score": 1.0, "flags": []},
    }

TIERS_CFG = {
    "tiers": {
        "lite": {
            "targets": [_t("ollama", "qwen3.5:0.8b")],
            "fallbacks": ["mid"],
        },
        "mid": {
            "targets": [
                _t("ollama", "qwen3.5:2b"),
                _t("ollama", "qwen3-vl:2b", vision_ok=True),
                _t("ollama", "granite4.1:3b"),
            ],
            "fallbacks": ["heavy"],
        },
        "heavy": {
            "targets": [
                _t("agnes", "agnes-2.5-flash"),
                _t("openai", "gpt-5.6-luna"),
                _t("gemini", "gemini-3.7-flash", vision_ok=True),
                _t("ollama", "granite4.1:3b"),
            ],
            "fallbacks": [],
        },
    }
}

# ── availability fakes ────────────────────────────────────────────────────────

ALL_AVAILABLE  = lambda p, m: True
NONE_AVAILABLE = lambda p, m: False
ONLY_GRANITE   = lambda p, m: m == "granite4.1:3b"
NO_CLOUD_KEYS  = lambda p, m: p == "ollama"   # cloud providers unavailable
VISION_ONLY    = lambda p, m: m == "qwen3-vl:2b"

# ── basic routing ─────────────────────────────────────────────────────────────

def test_greeting_routes_to_lite():
    req = GatewayRequest(id="x", user_text="Hi how are you")
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    assert d.status == "ok"
    assert d.tier == "lite"
    assert d.model == "qwen3.5:0.8b"
    assert d.provider == "ollama"

def test_successful_route_fields_populated():
    req = GatewayRequest(id="x", user_text="Hello")
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    assert d.status == "ok"
    assert d.tier is not None
    assert d.provider is not None
    assert d.model is not None

def test_hard_json_not_lite():
    req = GatewayRequest(id="x", user_text="Extract invoice fields", need_json=True)
    d = route(req, HARD, TIERS_CFG, ALL_AVAILABLE)
    assert d.status == "ok"
    assert d.tier != "lite"

def test_hard_json_reason_code():
    req = GatewayRequest(id="x", user_text="Extract invoice fields", need_json=True)
    d = route(req, HARD, TIERS_CFG, ALL_AVAILABLE)
    assert ReasonCode.SKIPPED_HARD_JSON_LITE in d.reason_codes

def test_auto_selected_reason():
    req = GatewayRequest(id="x", user_text="Hello")
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    assert ReasonCode.AUTO_SELECTED in d.reason_codes

# ── preferred tier ────────────────────────────────────────────────────────────

def test_preferred_heavy_honored():
    req = GatewayRequest(id="x", user_text="Analyse this", preferred_tier="heavy")
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    assert d.tier == "heavy"
    assert d.model == "agnes-2.5-flash"

def test_preferred_tier_reason_code():
    req = GatewayRequest(id="x", user_text="Hello", preferred_tier="heavy")
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    assert ReasonCode.PREFERRED_TIER_USED in d.reason_codes

def test_preferred_mid_used():
    req = GatewayRequest(id="x", user_text="Hello", preferred_tier="mid")
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    assert d.tier == "mid"

def test_preferred_in_disallow_falls_to_auto():
    req = GatewayRequest(id="x", user_text="Hello",
                         preferred_tier="lite", disallow_tiers=["lite"])
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    assert d.status == "ok"
    assert d.tier == "mid"

# ── no cloud keys / unavailable ───────────────────────────────────────────────

def test_no_cloud_keys_preferred_heavy_falls_to_granite():
    req = GatewayRequest(id="x", user_text="Hard task", preferred_tier="heavy")
    d = route(req, HARD, TIERS_CFG, NO_CLOUD_KEYS)
    assert d.status == "ok"
    assert d.tier == "heavy"
    assert d.model == "granite4.1:3b"
    assert d.provider == "ollama"

def test_no_cloud_keys_auto_selects_mid_granite():
    # lite/qwen3.5:0.8b unavailable; mid/granite available
    req = GatewayRequest(id="x", user_text="Medium task")
    d = route(req, SIMPLE, TIERS_CFG, ONLY_GRANITE)
    assert d.status == "ok"
    assert d.model == "granite4.1:3b"

def test_all_unavailable_status():
    req = GatewayRequest(id="x", user_text="Hello")
    d = route(req, SIMPLE, TIERS_CFG, NONE_AVAILABLE)
    assert d.status == "unavailable"
    assert d.tier is None
    assert d.model is None

def test_unavailable_reason_code_recorded():
    req = GatewayRequest(id="x", user_text="Hello")
    d = route(req, SIMPLE, TIERS_CFG, NONE_AVAILABLE)
    assert ReasonCode.SKIPPED_UNAVAILABLE in d.reason_codes

def test_disallow_lite_skips_to_mid():
    req = GatewayRequest(id="x", user_text="Hello", disallow_tiers=["lite"])
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    assert d.status == "ok"
    assert d.tier == "mid"

# ── vision routing ────────────────────────────────────────────────────────────

def test_has_image_uses_vision_ok_target():
    req = GatewayRequest(id="x", user_text="Describe this image",
                         flags=RequestFlags(has_image=True))
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    assert d.status == "ok"
    assert d.model == "qwen3-vl:2b"   # first vision_ok target in mid

def test_has_image_no_vision_targets_unsupported():
    cfg = {
        "tiers": {
            "lite": {
                "targets": [_t("ollama", "qwen3.5:0.8b", vision_ok=False)],
                "fallbacks": [],
            }
        }
    }
    req = GatewayRequest(id="x", user_text="Describe image",
                         flags=RequestFlags(has_image=True))
    d = route(req, SIMPLE, cfg, ALL_AVAILABLE)
    assert d.status == "unsupported"

def test_has_image_skipped_reason_recorded():
    req = GatewayRequest(id="x", user_text="Describe image",
                         flags=RequestFlags(has_image=True))
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    # lite/qwen3.5:0.8b is skipped for vision
    assert ReasonCode.SKIPPED_NO_VISION in d.reason_codes

# ── fallback chain ────────────────────────────────────────────────────────────

def test_fallback_chain_populated_after_lite():
    req = GatewayRequest(id="x", user_text="Hello")
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    # lite selected; chain includes mid + heavy targets
    assert len(d.fallback_chain) > 0

def test_fallback_chain_entries_are_provider_model():
    req = GatewayRequest(id="x", user_text="Hello")
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    for entry in d.fallback_chain:
        assert ":" in entry

def test_preferred_heavy_fallback_chain_has_remaining():
    req = GatewayRequest(id="x", user_text="Hello", preferred_tier="heavy")
    d = route(req, SIMPLE, TIERS_CFG, ALL_AVAILABLE)
    # agnes selected; chain has openai, gemini, granite
    assert len(d.fallback_chain) == 3

# ── load from real file ───────────────────────────────────────────────────────

def test_load_tiers_from_file():
    cfg = load_tiers("config/tiers.yaml")
    assert "tiers" in cfg
    for name in ("lite", "mid", "heavy"):
        assert name in cfg["tiers"]
        assert "targets" in cfg["tiers"][name]
        assert "fallbacks" in cfg["tiers"][name]

def test_route_with_real_config_file():
    cfg = load_tiers("config/tiers.yaml")
    req = GatewayRequest(id="x", user_text="Hello")
    d = route(req, SIMPLE, cfg, ALL_AVAILABLE)
    assert d.status == "ok"
    assert d.tier in ("lite", "mid", "heavy")
