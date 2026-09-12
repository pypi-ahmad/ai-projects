"""Optional LLM execution.

No completers are registered by default, so `execute` always returns a
dry result (body + config only, no model call) until something registers
one for the resolved version's `config.provider` — real providers
(Ollama, Agnes AI, OpenAI-compatible, Gemini) are a later phase.
"""

from __future__ import annotations

import time
from typing import Protocol

from promptreg.execute.models import ExecutionResult
from promptreg.registry.models import PromptConfig


class Completer(Protocol):
    def __call__(self, body: str, config: PromptConfig) -> str: ...


COMPLETERS: dict[str, Completer] = {}


def execute(body: str, config: PromptConfig) -> ExecutionResult:
    """Run body+config through the provider's completer, if one is registered.

    No completer registered for `config.provider` -> dry result: `ok=True`,
    `dry=True`, `output=None`, `latency_ms=0.0`. A registered completer that
    raises degrades to `ok=False` rather than propagating — a bad provider
    call should never take down the resolve/execute/record pipeline.
    """
    completer = COMPLETERS.get(config.provider)
    if completer is None:
        return ExecutionResult(
            body=body, config=config, dry=True, output=None, ok=True, latency_ms=0.0
        )

    start = time.monotonic()
    try:
        output = completer(body, config)
    except Exception:  # noqa: BLE001 -- provider failures degrade to ok=False, never propagate
        latency_ms = (time.monotonic() - start) * 1000
        return ExecutionResult(
            body=body, config=config, dry=False, output=None, ok=False, latency_ms=latency_ms
        )
    latency_ms = (time.monotonic() - start) * 1000
    return ExecutionResult(
        body=body, config=config, dry=False, output=output, ok=True, latency_ms=latency_ms
    )
