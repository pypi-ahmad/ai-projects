from __future__ import annotations

import pytest

from guardrails import Guard, GuardBlocked, GuardContext
from guardrails.models import Finding, Span


class _BlockDetector:
    detector_id = "block"

    def run(self, text: str, context: GuardContext) -> Finding:
        return Finding(detector_id=self.detector_id, severity="block", spans=[], message="blocked")


class _RedactDetector:
    detector_id = "redact"

    def run(self, text: str, context: GuardContext) -> Finding:
        idx = text.find("secret")
        if idx == -1:
            return Finding(detector_id=self.detector_id, severity="info", spans=[], message="clean")
        span = Span(
            start=idx, end=idx + len("secret"), type="test", score=1.0, replacement="[REDACTED]"
        )
        return Finding(
            detector_id=self.detector_id, severity="warn", spans=[span], message="found secret"
        )


class _EchoDetector:
    """Records whatever text it actually saw, so tests can assert on ordering."""

    detector_id = "echo"

    def __init__(self) -> None:
        self.seen: str | None = None

    def run(self, text: str, context: GuardContext) -> Finding:
        self.seen = text
        return Finding(detector_id=self.detector_id, severity="info", spans=[], message="seen")


class _BoomDetector:
    detector_id = "boom"

    def run(self, text: str, context: GuardContext) -> Finding:
        raise RuntimeError("boom")


def test_empty_pipeline_allows() -> None:
    decision = Guard().check_input("hello")
    assert decision.action == "allow"
    assert decision.findings == []
    assert decision.text_out == "hello"


def test_stub_block_detector_blocks() -> None:
    decision = Guard(input_detectors=[_BlockDetector()]).check_input("hello")
    assert decision.action == "block"
    assert decision.findings[0].severity == "block"


def test_fail_closed_blocks_on_exception() -> None:
    decision = Guard(input_detectors=[_BoomDetector()], fail_mode="closed").check_input("hello")
    assert decision.action == "block"
    assert decision.findings[0].message == "detector_error"


def test_fail_open_allows_with_finding_on_exception() -> None:
    decision = Guard(input_detectors=[_BoomDetector()], fail_mode="open").check_input("hello")
    assert decision.action == "allow"
    assert decision.findings[0].severity == "warn"
    assert decision.text_out == "hello"


def test_transform_applies_before_next_detector_runs() -> None:
    echo = _EchoDetector()
    decision = Guard(input_detectors=[_RedactDetector(), echo]).check_input("my secret is here")
    assert decision.action == "transform"
    assert decision.text_out == "my [REDACTED] is here"
    assert echo.seen == "my [REDACTED] is here"  # saw redacted text, not the raw one


def test_observe_policy_does_not_block() -> None:
    decision = Guard(input_detectors=[_BlockDetector()], policy="observe").check_input("hello")
    assert decision.action != "block"
    assert decision.findings[0].severity == "block"  # still recorded


def test_per_call_policy_overrides_construction_policy() -> None:
    guard = Guard(input_detectors=[_BlockDetector()])  # default policy="standard"
    decision = guard.check_input("hello", policy="observe")
    assert decision.action != "block"
    assert decision.policy == "observe"


# --- wrap_call ----------------------------------------------------------------------


def test_wrap_call_yields_transformed_last_user_message() -> None:
    guard = Guard(input_detectors=[_RedactDetector()])
    messages = [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "my secret is here"},
    ]
    with guard.wrap_call(messages) as safe:
        assert safe.messages[0] == messages[0]  # untouched
        assert safe.messages[1]["content"] == "my [REDACTED] is here"
        assert safe.decision.action == "transform"


def test_wrap_call_raises_and_skips_body_on_block() -> None:
    guard = Guard(input_detectors=[_BlockDetector()])
    messages = [{"role": "user", "content": "hello"}]
    body_ran = False

    with pytest.raises(GuardBlocked) as exc_info, guard.wrap_call(messages):
        body_ran = True

    assert not body_ran
    assert exc_info.value.decision.action == "block"


def test_wrap_call_passes_through_with_no_user_message() -> None:
    guard = Guard(input_detectors=[_BlockDetector()])  # would block if it ran
    messages = [{"role": "system", "content": "be helpful"}]
    with guard.wrap_call(messages) as safe:
        assert safe.messages == messages
        assert safe.decision.action == "allow"
