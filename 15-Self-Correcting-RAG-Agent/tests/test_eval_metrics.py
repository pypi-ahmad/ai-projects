"""Pure unit tests for the eval headline metrics -- no live calls."""

from self_correcting_rag.eval.metrics import (
    abstain_on_unknown_rate,
    citation_legality_rate,
    no_web_when_disabled_rate,
)
from self_correcting_rag.eval.records import EvalCase, EvalCaseResult


def _case(id_: str, category: str) -> EvalCase:
    return EvalCase(id=id_, question="q", category=category)


def test_citation_legality_rate_counts_only_answered_cases():
    results = [
        EvalCaseResult(
            _case("a", "in_corpus"),
            answered=True,
            illegal_citation_found=False,
            web_fired=False,
            reason=None,
        ),
        EvalCaseResult(
            _case("b", "in_corpus"),
            answered=True,
            illegal_citation_found=True,
            web_fired=False,
            reason=None,
        ),
        EvalCaseResult(
            _case("c", "out_of_corpus"),
            answered=False,
            illegal_citation_found=False,
            web_fired=False,
            reason="abstained",
        ),
    ]
    # 2 answered, 1 of them illegal -> 1/2
    assert citation_legality_rate(results) == 0.5


def test_citation_legality_rate_undefined_when_nothing_answered():
    results = [
        EvalCaseResult(
            _case("a", "out_of_corpus"),
            answered=False,
            illegal_citation_found=False,
            web_fired=False,
            reason="x",
        ),
    ]
    assert citation_legality_rate(results) is None


def test_abstain_on_unknown_rate_only_considers_out_of_corpus():
    results = [
        EvalCaseResult(
            _case("a", "in_corpus"),
            answered=True,
            illegal_citation_found=False,
            web_fired=False,
            reason=None,
        ),
        EvalCaseResult(
            _case("b", "out_of_corpus"),
            answered=False,
            illegal_citation_found=False,
            web_fired=False,
            reason="x",
        ),
        EvalCaseResult(
            _case("c", "out_of_corpus"),
            answered=True,
            illegal_citation_found=False,
            web_fired=False,
            reason=None,
        ),
    ]
    # 2 out_of_corpus cases, 1 correctly abstained -> 1/2
    assert abstain_on_unknown_rate(results) == 0.5


def test_abstain_on_unknown_rate_undefined_with_no_out_of_corpus_cases():
    results = [
        EvalCaseResult(
            _case("a", "in_corpus"),
            answered=True,
            illegal_citation_found=False,
            web_fired=False,
            reason=None,
        ),
    ]
    assert abstain_on_unknown_rate(results) is None


def test_no_web_when_disabled_rate_perfect_score():
    results = [
        EvalCaseResult(
            _case("a", "in_corpus"),
            answered=True,
            illegal_citation_found=False,
            web_fired=False,
            reason=None,
        ),
        EvalCaseResult(
            _case("b", "out_of_corpus"),
            answered=False,
            illegal_citation_found=False,
            web_fired=False,
            reason="x",
        ),
    ]
    assert no_web_when_disabled_rate(results, web_enabled=False) == 1.0


def test_no_web_when_disabled_rate_catches_a_regression():
    results = [
        EvalCaseResult(
            _case("a", "in_corpus"),
            answered=True,
            illegal_citation_found=False,
            web_fired=True,
            reason=None,
        ),
        EvalCaseResult(
            _case("b", "in_corpus"),
            answered=True,
            illegal_citation_found=False,
            web_fired=False,
            reason=None,
        ),
    ]
    assert no_web_when_disabled_rate(results, web_enabled=False) == 0.5


def test_no_web_when_disabled_rate_undefined_when_web_was_enabled():
    results = [
        EvalCaseResult(
            _case("a", "in_corpus"),
            answered=True,
            illegal_citation_found=False,
            web_fired=True,
            reason=None,
        ),
    ]
    assert no_web_when_disabled_rate(results, web_enabled=True) is None
