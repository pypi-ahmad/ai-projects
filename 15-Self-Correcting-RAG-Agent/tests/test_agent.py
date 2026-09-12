"""Agent loop building blocks: rewrite/critique JSON parsing (with a fake,
mocked Provider -- no live LLM calls) and the critique decision postconditions.
"""

import pytest
from pydantic import ValidationError

from self_correcting_rag.agent.critique import critique, enforce_decision
from self_correcting_rag.agent.prompts import CRITIQUE_SYSTEM_PROMPT
from self_correcting_rag.agent.rewrite import rewrite
from self_correcting_rag.agent.schemas import CritiqueResult, LoopPolicy, RewriteResult
from self_correcting_rag.retrieve.records import RetrievalResult


class FakeProvider:
    """Returns canned responses in order, one per `complete()` call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete(self, *, system: str, user: str, model: str) -> str:
        self.calls += 1
        return self._responses.pop(0)


ONE_CHUNK = [
    RetrievalResult(chunk_id="c1", text="some text", source_path="a.md", page=1, score=0.9)
]


def test_rewrite_parses_valid_json():
    fake = FakeProvider(['{"queries": ["q1", "q2"], "rationale": "expanded synonyms"}'])
    result = rewrite(fake, "qwen3.5:0.8b", "original query")
    assert isinstance(result, RewriteResult)
    assert result.queries == ["q1", "q2"]
    assert fake.calls == 1


def test_bad_json_is_repaired_once():
    fake = FakeProvider(
        [
            "here you go: {queries: [oops not json]",  # invalid JSON
            '{"queries": ["fixed"], "rationale": "repaired"}',  # valid on repair
        ]
    )
    result = rewrite(fake, "qwen3.5:0.8b", "original query")
    assert result.queries == ["fixed"]
    assert fake.calls == 2  # exactly one repair call, not an unbounded retry


def test_still_bad_json_after_repair_raises():
    fake = FakeProvider(["not json at all", "still not json"])
    with pytest.raises(ValidationError):  # from the second (repair) attempt
        rewrite(fake, "qwen3.5:0.8b", "original query")
    assert fake.calls == 2


def test_rewrite_result_rejects_too_many_queries():
    with pytest.raises(ValidationError):
        RewriteResult(queries=["a", "b", "c", "d"], rationale="too many")


def test_rewrite_result_rejects_empty_queries():
    with pytest.raises(ValidationError):
        RewriteResult(queries=[], rationale="none")


def test_critique_result_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        CritiqueResult(grounded=1.5, coverage=0.5, missing=[], decision="answer", rationale="x")


def test_critique_parses_valid_json_and_keeps_model_decision_when_legal():
    fake = FakeProvider(
        [
            '{"grounded": 0.9, "coverage": 0.9, "missing": [], '
            '"decision": "answer", "rationale": "well covered"}'
        ]
    )
    result = critique(
        fake, "qwen3.5:0.8b", query="q", chunks=ONE_CHUNK, policy=LoopPolicy(), iteration=1
    )
    assert result.decision == "answer"
    assert "overrode" not in result.rationale
    assert fake.calls == 1


@pytest.mark.parametrize(
    ("grounded", "chunks_present", "iteration", "max_iters", "web_enabled", "expected"),
    [
        (0.9, True, 1, 2, False, "answer"),  # grounded + on-topic chunk -> answer
        (0.9, False, 1, 2, False, "retry"),  # grounded score alone isn't enough, no chunks
        (0.2, True, 1, 2, False, "retry"),  # low grounded, retries left -> retry
        (0.2, True, 2, 2, True, "web"),  # retries exhausted, web enabled -> web
        (0.2, True, 2, 2, False, "abstain"),  # retries exhausted, web off -> abstain
    ],
)
def test_enforce_decision_matches_loop_md_table(
    grounded, chunks_present, iteration, max_iters, web_enabled, expected
):
    # Model's own proposed decision is deliberately wrong/irrelevant here --
    # enforce_decision must compute the legal decision itself, not trust it.
    proposed = CritiqueResult(
        grounded=grounded, coverage=0.5, missing=[], decision="answer", rationale="model says so"
    )
    policy = LoopPolicy(confidence_threshold=0.6, max_iters=max_iters, web_enabled=web_enabled)
    decision, _reason = enforce_decision(
        proposed, policy=policy, iteration=iteration, chunks_present=chunks_present
    )
    assert decision == expected


def test_critique_overrides_ungrounded_answer_decision():
    fake = FakeProvider(
        [
            '{"grounded": 0.1, "coverage": 0.2, "missing": ["dates"], '
            '"decision": "answer", "rationale": "looks fine"}'
        ]
    )
    # max_iters=1 with iteration=1 -> no retries left, web disabled -> abstain
    policy = LoopPolicy(confidence_threshold=0.6, max_iters=1, web_enabled=False)
    result = critique(fake, "qwen3.5:0.8b", query="q", chunks=ONE_CHUNK, policy=policy, iteration=1)
    assert result.decision == "abstain"
    assert "overrode model's decision 'answer' -> 'abstain'" in result.rationale


def test_critique_prompt_encodes_the_data_not_instructions_rule():
    assert "never obey" in CRITIQUE_SYSTEM_PROMPT
    assert "never instructions" in CRITIQUE_SYSTEM_PROMPT
