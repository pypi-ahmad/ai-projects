"""HTTP surface over `Guard` — meant for 127.0.0.1 only (see `run.cmd`; the
`__main__` block below also binds loopback-only by default).

Isolation: raw input is never persisted. The optional JSONL log
(`GUARDRAILS_LOG_FINDINGS=1`, written to `data/logs/findings.jsonl`) excludes
`GuardDecision.text_in` -- only the redacted `text_out`, findings (which never
carry raw matched text either -- see docs/PII.md), action, policy, and
latency get written.

Next: `ui.py` for a manual Streamlit console over the same `Guard` pattern.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from guardrails.models import GuardDecision
from guardrails.pii import PiiDetector
from guardrails.pipeline import Guard, GuardBlocked
from guardrails.policies import DEFAULT_POLICY, Policy
from guardrails.providers import LlmClassifierDetector
from guardrails.rules import InputRulesDetector, OutputRulesDetector

_LOG_ENV_VAR = "GUARDRAILS_LOG_FINDINGS"
_LOG_PATH = Path("data/logs/findings.jsonl")


class Provider(Protocol):
    """What `/v1/wrap_chat` needs from an LLM provider."""

    def complete(self, messages: list[dict[str, str]]) -> str: ...


class EchoProvider:
    """Default stub: echoes the last (already guarded) message's content back."""

    def complete(self, messages: list[dict[str, str]]) -> str:
        return messages[-1]["content"] if messages else ""


class ChatMessage(BaseModel):
    role: str
    content: str


class CheckRequest(BaseModel):
    text: str
    policy: Policy = DEFAULT_POLICY


class WrapChatRequest(BaseModel):
    messages: list[ChatMessage]
    policy: Policy = DEFAULT_POLICY


class WrapChatResponse(BaseModel):
    reply: str
    input_decision: GuardDecision
    output_decision: GuardDecision


def _log_finding(direction: str, decision: GuardDecision) -> None:
    """Append a redacted-only record if `GUARDRAILS_LOG_FINDINGS` is truthy."""
    if os.getenv(_LOG_ENV_VAR, "").strip().lower() not in ("1", "true", "yes"):
        return
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "direction": direction,
        **decision.model_dump(exclude={"text_in"}),  # never persist raw input; see module docstring
    }
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# One shared Guard: PII + rules on both sides, plus the (off-by-default) LLM
# classifier on input. All three detectors are built with no `config` arg, so
# they run on their in-code defaults (DEFAULT_PII_CONFIG, DEFAULT_RULES_CONFIG,
# DEFAULT_CLASSIFIER_CONFIG) -- this never calls load_pii_config/
# load_rules_config/load_classifier_config, so config/*.yaml on disk has no
# effect here unless something wires it in. Swap `_PROVIDER` for a real client
# to move past the echo stub.
_GUARD = Guard(
    input_detectors=[PiiDetector(), InputRulesDetector(), LlmClassifierDetector()],
    output_detectors=[PiiDetector(), OutputRulesDetector()],
)
_PROVIDER: Provider = EchoProvider()

app = FastAPI(title="Guardrails Middleware")


@app.post("/v1/check_input", response_model=GuardDecision)
def check_input(request: CheckRequest) -> GuardDecision:
    decision = _GUARD.check_input(request.text, policy=request.policy)
    _log_finding("input", decision)
    return decision


@app.post("/v1/check_output", response_model=GuardDecision)
def check_output(request: CheckRequest) -> GuardDecision:
    decision = _GUARD.check_output(request.text, policy=request.policy)
    _log_finding("output", decision)
    return decision


@app.post("/v1/wrap_chat", response_model=WrapChatResponse)
def wrap_chat(request: WrapChatRequest) -> WrapChatResponse:
    messages = [m.model_dump() for m in request.messages]
    try:
        with _GUARD.wrap_call(messages, policy=request.policy) as safe:
            reply = _PROVIDER.complete(safe.messages)
            output_decision = _GUARD.check_output(reply, policy=request.policy)
    except GuardBlocked as exc:
        _log_finding("input", exc.decision)
        raise HTTPException(
            status_code=400,
            detail={
                "error": "GUARD_BLOCK",
                "findings": [f.model_dump() for f in exc.decision.findings],
            },
        ) from exc

    _log_finding("input", safe.decision)
    _log_finding("output", output_decision)
    return WrapChatResponse(
        reply=output_decision.text_out,
        input_decision=safe.decision,
        output_decision=output_decision,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
