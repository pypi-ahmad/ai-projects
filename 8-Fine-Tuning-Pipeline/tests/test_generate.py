# generate_rows/to_examples against fake teacher clients below — no real Ollama or cloud call.
import json

import pytest

from src.data.generate import generate_rows, to_examples


class FakeTeacher:
    """Deterministic stand-in for a real teacher: no network, always-valid, always-unique output."""

    model_name = "fake-teacher"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        i = self.calls
        self.calls += 1
        products = ["billing", "account", "mobile_app", "web_app", "api", "integrations"]
        priorities = ["low", "medium", "high", "urgent"]
        sentiments = ["positive", "neutral", "negative"]
        actions = ["escalate", "request_info", "resolve", "refund", "schedule_callback"]
        return json.dumps(
            {
                "ticket": f"Ticket #{i:04d} - unique scenario about {products[i % len(products)]}.",
                "priority": priorities[i % len(priorities)],
                "product": products[i % len(products)],
                "sentiment": sentiments[i % len(sentiments)],
                "next_action": actions[i % len(actions)],
            }
        )


class BrokenTeacher:
    """Always returns unparseable garbage, to exercise the repair path."""

    model_name = "broken-teacher"

    def complete(self, prompt: str) -> str:
        return "not json at all"


def test_generator_produces_n_valid_rows():
    teacher = FakeTeacher()
    rows = generate_rows(5, teacher)
    assert len(rows) == 5

    examples = to_examples(rows, split="train", teacher_model=teacher.model_name)
    assert len(examples) == 5
    assert all(ex.split == "train" for ex in examples)
    assert all(ex.teacher_model == "fake-teacher" for ex in examples)
    assert all(ex.source == "synthetic" for ex in examples)


def test_generator_drops_unrepairable_rows():
    rows = generate_rows(3, BrokenTeacher(), repair_teacher=BrokenTeacher())
    assert rows == []


def test_generator_fails_diversity_check_on_duplicates():
    class RepeatingTeacher:
        model_name = "repeating-teacher"

        def complete(self, prompt: str) -> str:
            return json.dumps(
                {
                    "ticket": "Same ticket text every single time, no variation at all here.",
                    "priority": "low",
                    "product": "billing",
                    "sentiment": "neutral",
                    "next_action": "resolve",
                }
            )

    with pytest.raises(RuntimeError):
        generate_rows(5, RepeatingTeacher())
