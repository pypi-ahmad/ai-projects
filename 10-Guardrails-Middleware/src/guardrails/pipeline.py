"""Ordered-detector guard pipeline.

Runs a list of detectors in order, applying each one's transforms to the
working text before the next detector sees it. On the input direction this
means PII-redaction detectors belong *first* in the list, so classifier
detectors run against already-redacted text (see docs/ARCHITECTURE.md) — this
is a detector-ordering convention, not something the pipeline enforces itself.

Real detectors now implement the `Detector` protocol below: `pii.PiiDetector`,
`rules.InputRulesDetector`/`OutputRulesDetector`, and
`providers.LlmClassifierDetector`/`EmbeddingSimilarityDetector` (see `api.py`
for how they're assembled into a `Guard`). `detectors.py` still uses the
older Phase 1 dataclass types from `types.py` and has not been adapted to
this protocol -- it's intentionally unwired, kept only for its own test (see
docs/DETECTORS.md). Next: `pii.py` or `rules.py` for a concrete detector, or
`api.py` for how a `Guard` gets built and served.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from guardrails.models import (
    Action,
    Direction,
    FailMode,
    Finding,
    GuardContext,
    GuardDecision,
    apply_spans,
)
from guardrails.policies import DEFAULT_POLICY, Policy

if TYPE_CHECKING:
    from collections.abc import Iterator


class Detector(Protocol):
    """A single check the pipeline runs, in order."""

    detector_id: str

    def run(self, text: str, context: GuardContext) -> Finding: ...


class Pipeline:
    """Runs an ordered list of detectors over one piece of text."""

    def __init__(self, detectors: list[Detector], policy: Policy = DEFAULT_POLICY) -> None:
        self.detectors = detectors
        self.policy = policy

    def run(self, text: str, context: GuardContext, policy: Policy | None = None) -> GuardDecision:
        """Run every detector once. `policy` overrides `self.policy` for this call only."""
        active_policy = policy or self.policy
        start = time.perf_counter()
        working_text = text
        findings: list[Finding] = []
        action: Action = "allow"

        for detector in self.detectors:
            try:
                finding = detector.run(working_text, context)
            except Exception:  # noqa: BLE001 - any detector failure is a guardrails failure
                findings.append(
                    Finding(
                        detector_id=getattr(detector, "detector_id", "unknown"),
                        severity="block" if context.fail_mode == "closed" else "warn",
                        spans=[],
                        message="detector_error",
                    )
                )
                if context.fail_mode == "closed":
                    action = "block"
                    break
                continue  # fail-open: record the finding, keep going

            findings.append(finding)
            working_text = apply_spans(working_text, finding.spans)
            if action == "allow" and any(s.replacement is not None for s in finding.spans):
                action = "transform"

            if finding.severity == "block" and active_policy != "observe":
                action = "block"
                break  # first block finding wins

        latency_ms = (time.perf_counter() - start) * 1000
        return GuardDecision(
            action=action,
            findings=findings,
            text_in=text,
            text_out=working_text,
            policy=active_policy,
            latency_ms=latency_ms,
        )


class GuardBlocked(Exception):  # noqa: N818 - "Blocked", not "Error": this is a normal outcome, not a bug
    """Raised by `Guard.wrap_call` when the last user message is blocked."""

    def __init__(self, decision: GuardDecision) -> None:
        self.decision = decision
        super().__init__(f"input blocked: {[f.message for f in decision.findings]}")


@dataclass
class SafeMessages:
    """What `Guard.wrap_call` yields: safe messages, plus the decision behind them."""

    messages: list[dict[str, str]]
    decision: GuardDecision


def _last_user_index(messages: list[dict[str, str]]) -> int | None:
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            return i
    return None


class Guard:
    """Library facade: wraps a caller's own LLM call.

    `guard.check_input(text)` before the call, `guard.check_output(text)` after --
    or `guard.wrap_call(messages)` to cover the input side of a chat-message list
    in one step.
    """

    def __init__(  # noqa: PLR0913, PLR0917 - each param is a distinct, non-optional-to-merge config knob
        self,
        input_detectors: list[Detector] | None = None,
        output_detectors: list[Detector] | None = None,
        policy: Policy = DEFAULT_POLICY,
        fail_mode: FailMode = "closed",
        tenant: str | None = None,
        route: str | None = None,
    ) -> None:
        self.input_pipeline = Pipeline(input_detectors or [], policy=policy)
        self.output_pipeline = Pipeline(output_detectors or [], policy=policy)
        self.fail_mode = fail_mode
        self.tenant = tenant
        self.route = route

    def check_input(self, text: str, policy: Policy | None = None) -> GuardDecision:
        return self.input_pipeline.run(text, self._context("input"), policy=policy)

    def check_output(self, text: str, policy: Policy | None = None) -> GuardDecision:
        return self.output_pipeline.run(text, self._context("output"), policy=policy)

    @contextmanager
    def wrap_call(
        self, messages: list[dict[str, str]], policy: Policy | None = None
    ) -> Iterator[SafeMessages]:
        """Check the last user message; yield messages safe to send onward.

        Raises `GuardBlocked` (before the `with` body runs) if it's blocked. A
        message list with no `user` message passes through unchecked -- there's
        nothing here for `check_input` to look at.
        """
        index = _last_user_index(messages)
        if index is None:
            yield SafeMessages(
                messages=messages,
                decision=_allow_nothing_decision(policy or self.input_pipeline.policy),
            )
            return

        decision = self.check_input(messages[index]["content"], policy=policy)
        if decision.action == "block":
            raise GuardBlocked(decision)

        safe = [
            *messages[:index],
            {**messages[index], "content": decision.text_out},
            *messages[index + 1 :],
        ]
        yield SafeMessages(messages=safe, decision=decision)

    def _context(self, direction: Direction) -> GuardContext:
        return GuardContext(
            direction=direction,
            tenant=self.tenant,
            route=self.route,
            fail_mode=self.fail_mode,
        )


def _allow_nothing_decision(policy: Policy) -> GuardDecision:
    return GuardDecision(
        action="allow", findings=[], text_in="", text_out="", policy=policy, latency_ms=0.0
    )
