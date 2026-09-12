"""loop.run: tool-call -> final; JSON-in-prompt tool-call; HIT_MAX_TOOLS; log redaction.

No test here makes a real network call to any provider -- Phase 5 gave no
Tests bullet (unlike Phases 2-4), and a live LLM call would be flaky,
require real API keys/a running Ollama server, and non-deterministic
model output, none of which belong in an automated suite. These use an
in-process FakeProvider, the same pattern Phase 3 used for repair_model.
"""

import json

from tools.builtins import register_builtins
from tools.loop import LoopStatus, _redact_long_strings, run
from tools.providers import ProviderReply
from tools.registry import Registry


def _registry() -> Registry:
    registry = Registry()
    register_builtins(registry)
    return registry


class _FakeProvider:
    def __init__(self, replies: list[ProviderReply]) -> None:
        self._replies = replies
        self.calls = 0

    def chat(self, _messages, _tools) -> ProviderReply:
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return reply


def test_run_executes_native_tool_call_then_returns_final_text():
    provider = _FakeProvider(
        [
            ProviderReply(
                text=None,
                native_tool_calls=[{"function": {"name": "calc", "arguments": {"expression": "2+2"}}}],
            ),
            ProviderReply(text="The answer is 4.", native_tool_calls=None),
        ]
    )

    result = run(
        [{"role": "user", "content": "what is 2+2?"}],
        registry=_registry(),
        provider=provider,
        max_tool_iters=4,
    )

    assert result["status"] == LoopStatus.FINAL
    assert result["text"] == "The answer is 4."
    assert provider.calls == 2


def test_run_handles_json_in_prompt_tool_call():
    provider = _FakeProvider(
        [
            ProviderReply(text='{"tool": "calc", "args": {"expression": "3*3"}}'),
            ProviderReply(text="9"),
        ]
    )

    result = run([{"role": "user", "content": "3*3?"}], registry=_registry(), provider=provider)

    assert result["status"] == LoopStatus.FINAL
    assert result["text"] == "9"


def test_run_hits_max_tool_iters():
    provider = _FakeProvider(
        [
            ProviderReply(
                text=None,
                native_tool_calls=[{"function": {"name": "calc", "arguments": {"expression": "1+1"}}}],
            )
        ]
    )

    result = run(
        [{"role": "user", "content": "loop forever"}],
        registry=_registry(),
        provider=provider,
        max_tool_iters=3,
    )

    assert result["status"] == LoopStatus.HIT_MAX_TOOLS
    assert result["iterations"] == 3
    assert provider.calls == 3


def test_redact_long_strings():
    data = {"a": "x" * 300, "b": "short", "c": [{"d": "y" * 250}]}

    redacted = _redact_long_strings(data, 200)

    assert redacted["a"] == "<redacted: 300 chars>"
    assert redacted["b"] == "short"
    assert redacted["c"][0]["d"] == "<redacted: 250 chars>"


def test_run_logs_and_redacts_long_note_body(tmp_path, monkeypatch):
    import tools.loop as loop_module

    monkeypatch.setattr(loop_module, "LOG_PATH", tmp_path / "runs.jsonl")

    long_text = "x" * 500
    provider = _FakeProvider(
        [
            ProviderReply(
                text=None,
                native_tool_calls=[{"function": {"name": "write_note", "arguments": {"text": long_text}}}],
            ),
            ProviderReply(text="done"),
        ]
    )

    result = run(
        [{"role": "user", "content": "write a long note"}],
        registry=_registry(),
        provider=provider,
        run_id="log-test",
    )

    assert result["status"] == LoopStatus.FINAL
    lines = loop_module.LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    tool_entry = json.loads(lines[0])
    assert tool_entry["args"]["text"] == "<redacted: 500 chars>"
