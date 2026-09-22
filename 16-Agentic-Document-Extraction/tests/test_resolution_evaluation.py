"""No-network proofs for the approved evaluation's limits and promotion gate."""
import json

import pytest

from scripts import evaluate_resolution as evaluation
from src.schema import ParsePage


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "prompts/runtime").mkdir(parents=True)
    (root / "prompts/runtime/parse-page.md").write_text("fixed prompt")
    (root / "data/inbox").mkdir(parents=True)
    references = tmp_path / "references"
    references.mkdir()
    for name, _ in evaluation.APPROVED_SAMPLES:
        (root / "data/inbox" / f"{name}.pdf").write_bytes(b"mock input")
        (references / f"{name}.parse.json").write_text("{}")
    monkeypatch.setattr(evaluation, "ROOT", root)
    monkeypatch.setattr(evaluation, "REFERENCES", references)
    monkeypatch.setattr(evaluation, "preprocess_pages", lambda path, **k: [dict(
        page=k["start_page"], doc_sha256="mock", width=k["max_long_edge"], height=100,
        base64="", mime="image/png")])
    monkeypatch.setattr(evaluation, "score_page", lambda page, reference: dict(
        reference_token_f1=0.6 if page.width_px == 3200 else 0.5))
    return tmp_path / "output"


def outcome(payload, *, known=True, status="parsed", output_tokens=100):
    return dict(page=payload["page"], status=status,
                result=ParsePage(page=payload["page"], width_px=payload["width"], height_px=100, blocks=[]).model_dump(),
                diagnostics=dict(usage_known=known, input_tokens=1000, output_tokens=output_tokens))


def test_comparison_uses_only_five_pages_and_ten_bounded_requests(corpus):
    calls = []
    def run(payload, prompt, **kwargs):
        calls.append(payload)
        assert prompt == "fixed prompt"
        assert kwargs == dict(max_completion_tokens=8192, reasoning_effort="medium")
        return outcome(payload)
    result = evaluation.compare(corpus, runner=run)
    assert len(calls) == result["requests"] == 10
    assert result["metric_gate_passed"] and not result["promoted"]
    assert result["visual_review"] == "not_started"
    assert result["estimated_cost_usd"] == pytest.approx(0.03)
    assert result["stop_reason"] == "completed"
    assert "BadgeCare" not in json.dumps(result)
    assert (corpus / "manifest.json").exists()


@pytest.mark.parametrize("limit,expected", [(1, 1), (3, 3)])
def test_request_limit_stops_before_next_call(corpus, limit, expected):
    result = evaluation.compare(corpus, runner=lambda p, *a, **k: outcome(p), max_requests=limit)
    assert result["requests"] == expected and result["stop_reason"] == "request_limit"
    assert not result["metric_gate_passed"]


def test_budget_reserves_next_request(corpus):
    result = evaluation.compare(corpus, runner=lambda *a, **k: pytest.fail("Unexpected call"), budget_usd=0.19)
    assert result["requests"] == 0 and result["stop_reason"] == "estimated_budget"


def test_reported_spend_stops_next_request(corpus):
    result = evaluation.compare(corpus, runner=lambda p, *a, **k: outcome(p), budget_usd=0.20)
    assert result["requests"] == 1 and result["stop_reason"] == "estimated_budget"


def test_unknown_usage_stops_immediately(corpus):
    result = evaluation.compare(corpus, runner=lambda p, *a, **k: outcome(p, known=False))
    assert result["requests"] == 1 and result["stop_reason"] == "unknown_usage"


def test_rejected_pages_are_not_resubmitted_at_other_resolution(corpus):
    result = evaluation.compare(corpus, runner=lambda p, *a, **k: outcome(p, status="content_filtered"))
    assert result["requests"] == 5
    assert all(p["profile"] == "baseline" for p in result["pages"])
    assert not result["metric_gate_passed"]


def test_limits_cannot_be_increased(corpus):
    for kwargs in (dict(max_requests=11), dict(budget_usd=2.01)):
        with pytest.raises(ValueError):
            evaluation.compare(corpus, **kwargs)
    assert not corpus.exists()


def test_any_page_regression_blocks_promotion():
    pages = [dict(document="sample", page=n, profile=profile, status="parsed",
                  metrics=dict(reference_token_f1=0.8 if profile == "baseline" else 0.9))
             for n in range(1, 6) for profile in evaluation.PROFILES]
    assert evaluation.metric_gate(pages)
    pages[1]["metrics"]["reference_token_f1"] = 0.7
    assert not evaluation.metric_gate(pages)
