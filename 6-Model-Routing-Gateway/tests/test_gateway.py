"""Tests for GatewayRequest (Pydantic v2) and FeatureExtractor.

All tests are offline — no model, no network, no env keys required.
"""
import pytest
import yaml
from pathlib import Path
from pydantic import ValidationError

from src.gateway.models import GatewayRequest, RequestFlags
from src.gateway.features import FeatureExtractor

_CFG_PATH = Path("config/features.yaml")

GREETING = "Hi! How are you?"

COMPLEX = (
    "Step by step, compare the following two Python frameworks and cite your sources. "
    "Please analyze and evaluate each approach carefully across all dimensions. "
    "Output the result as a JSON schema with fields: name, pros, cons, verdict. "
    "```python\nimport os\nprint(os.getcwd())\n```\n"
    "Consider performance, scalability, developer experience, and production readiness. "
    "This is a comprehensive evaluation that requires synthesizing information "
    "from multiple sources. Please provide step-by-step reasoning for each conclusion. "
) * 3  # repeated to push token count past 500


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(_CFG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def extractor(cfg):
    return FeatureExtractor(cfg)


# ── GatewayRequest ────────────────────────────────────────────────────────────

def test_request_minimal_defaults():
    req = GatewayRequest(id="r1", user_text="hello")
    assert req.need_json is False
    assert req.disallow_tiers == []
    assert req.system is None
    assert req.max_tokens is None
    assert req.preferred_tier is None
    assert req.schema_name is None
    assert req.flags.has_image is False
    assert req.flags.has_tools is False
    assert req.flags.long_context is False


def test_request_full_fields():
    req = GatewayRequest(
        id="r2",
        user_text="Summarise this document",
        system="You are a helpful assistant.",
        need_json=True,
        max_tokens=512,
        preferred_tier="heavy",
        disallow_tiers=["lite"],
        schema_name="summary_schema",
        flags=RequestFlags(has_image=False, has_tools=True, long_context=True),
    )
    assert req.preferred_tier == "heavy"
    assert req.disallow_tiers == ["lite"]
    assert req.flags.has_tools is True
    assert req.flags.long_context is True
    assert req.need_json is True


def test_request_invalid_preferred_tier():
    with pytest.raises(ValidationError):
        GatewayRequest(id="r3", user_text="hello", preferred_tier="ultra")


def test_request_invalid_disallow_tier():
    with pytest.raises(ValidationError):
        GatewayRequest(id="r4", user_text="hello", disallow_tiers=["cheap"])


def test_request_all_valid_tiers():
    for t in ("lite", "mid", "heavy"):
        req = GatewayRequest(id="x", user_text="hi", preferred_tier=t)
        assert req.preferred_tier == t


def test_request_flags_default_factory():
    r1 = GatewayRequest(id="a", user_text="hello")
    r2 = GatewayRequest(id="b", user_text="world")
    r1.flags.has_image = True
    # r2's flags should be independent (default_factory, not shared mutable default)
    assert r2.flags.has_image is False


# ── FeatureExtractor — basic counts ──────────────────────────────────────────

def test_n_chars(extractor):
    text = "Hello world"
    req = GatewayRequest(id="x", user_text=text)
    f = extractor.extract(req)
    assert f.n_chars == len(text)


def test_n_tokens_nonzero(extractor):
    req = GatewayRequest(id="x", user_text="hello world")
    f = extractor.extract(req)
    assert f.n_tokens_approx > 0


def test_n_sentences_single(extractor):
    req = GatewayRequest(id="x", user_text="Hello world")
    f = extractor.extract(req)
    assert f.n_sentences == 1


def test_n_sentences_multi(extractor):
    req = GatewayRequest(id="x", user_text="Hello. How are you? Fine!")
    f = extractor.extract(req)
    assert f.n_sentences == 3


# ── FeatureExtractor — flags ──────────────────────────────────────────────────

def test_code_fence_detected(extractor):
    req = GatewayRequest(id="x", user_text="Here:\n```python\nprint('hi')\n```")
    assert extractor.extract(req).has_code_fence is True


def test_no_code_fence(extractor):
    req = GatewayRequest(id="x", user_text=GREETING)
    assert extractor.extract(req).has_code_fence is False


def test_json_hint_detected_explicit(extractor):
    req = GatewayRequest(id="x", user_text="Output the result as JSON.")
    assert extractor.extract(req).has_json_hint is True


def test_json_hint_not_present(extractor):
    req = GatewayRequest(id="x", user_text="Tell me a joke.")
    assert extractor.extract(req).has_json_hint is False


def test_has_question_mark(extractor):
    req = GatewayRequest(id="x", user_text="What is the capital of France?")
    assert extractor.extract(req).has_question is True


def test_has_question_start_word(extractor):
    req = GatewayRequest(id="x", user_text="How does this work")
    assert extractor.extract(req).has_question is True


def test_no_question(extractor):
    req = GatewayRequest(id="x", user_text="Summarise this document.")
    assert extractor.extract(req).has_question is False


# ── FeatureExtractor — keywords ───────────────────────────────────────────────

def test_step_by_step_hit(extractor):
    req = GatewayRequest(id="x", user_text="Explain step by step how this works")
    assert "step_by_step" in extractor.extract(req).keyword_hits


def test_compare_hit(extractor):
    req = GatewayRequest(id="x", user_text="Compare option A and option B")
    assert "compare" in extractor.extract(req).keyword_hits


def test_keyword_hits_are_known_groups(extractor, cfg):
    req = GatewayRequest(id="x", user_text=COMPLEX)
    f = extractor.extract(req)
    known = set(cfg["keywords"].keys())
    assert set(f.keyword_hits).issubset(known)


def test_no_duplicate_keyword_groups(extractor):
    req = GatewayRequest(id="x", user_text="compare compare compare")
    f = extractor.extract(req)
    assert len(f.keyword_hits) == len(set(f.keyword_hits))


def test_no_keywords_greeting(extractor):
    req = GatewayRequest(id="x", user_text=GREETING)
    assert extractor.extract(req).keyword_hits == []


# ── FeatureExtractor — complexity score / label ───────────────────────────────

def test_score_in_range(extractor):
    for text in [GREETING, COMPLEX, "x" * 5000]:
        req = GatewayRequest(id="x", user_text=text)
        f = extractor.extract(req)
        assert 0.0 <= f.complexity_score <= 1.0


def test_greeting_is_simple(extractor):
    req = GatewayRequest(id="x", user_text=GREETING)
    f = extractor.extract(req)
    assert f.complexity_label == "simple"


def test_complex_is_hard(extractor):
    req = GatewayRequest(id="x", user_text=COMPLEX, need_json=True)
    f = extractor.extract(req)
    assert f.complexity_label == "hard"


def test_need_json_raises_score(extractor):
    base = GatewayRequest(id="x", user_text=GREETING, need_json=False)
    with_json = GatewayRequest(id="y", user_text=GREETING, need_json=True)
    assert extractor.extract(with_json).complexity_score > extractor.extract(base).complexity_score


def test_longer_text_higher_score(extractor):
    short = GatewayRequest(id="x", user_text="Hello.")
    long = GatewayRequest(id="y", user_text="word " * 3000)
    assert extractor.extract(long).complexity_score > extractor.extract(short).complexity_score


def test_label_matches_thresholds(extractor, cfg):
    thr = cfg["thresholds"]
    for text, need_json in [(GREETING, False), (COMPLEX, True)]:
        req = GatewayRequest(id="x", user_text=text, need_json=need_json)
        f = extractor.extract(req)
        if f.complexity_score < thr["simple"]:
            assert f.complexity_label == "simple"
        elif f.complexity_score < thr["medium"]:
            assert f.complexity_label == "medium"
        else:
            assert f.complexity_label == "hard"


def test_deterministic(extractor):
    req = GatewayRequest(id="x", user_text=COMPLEX)
    f1 = extractor.extract(req)
    f2 = extractor.extract(req)
    assert f1.complexity_score == f2.complexity_score
    assert f1.complexity_label == f2.complexity_label
    assert f1.keyword_hits == f2.keyword_hits
