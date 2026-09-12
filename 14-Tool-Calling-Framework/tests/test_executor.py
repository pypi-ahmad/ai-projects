"""Timeout tool; write_note -> read_note round trip; traversal blocked at exec layer.

Plus two more directly-requested behaviors not named in the phase's Tests
bullets but explicit in its Executor/Retry bullets: permission checks
("requested cannot exceed spec") and the retry-with-backoff policy.
"""

import time

from pydantic import BaseModel

from tools.builtins import register_builtins
from tools.parse import ToolCall, ToolErrorCode
from tools.registry import Registry
from tools.sandbox import execute, execute_with_retry
from tools.schema import ToolArgs, ToolPermissions, ToolSpec


def _registry() -> Registry:
    registry = Registry()
    register_builtins(registry)
    return registry


class _SleepArgs(ToolArgs):
    seconds: float


class _SleepResult(BaseModel):
    slept: float


def _sleep(args: _SleepArgs) -> _SleepResult:
    time.sleep(args.seconds)
    return _SleepResult(slept=args.seconds)


def test_timeout_tool():
    registry = _registry()
    registry.register(
        ToolSpec(
            name="sleep",
            description="test-only: block for N seconds",
            permissions=ToolPermissions(),
            args_model=_SleepArgs,
            result_model=_SleepResult,
            fn=_sleep,
            timeout_s=0.1,
            max_retries=0,
        )
    )

    result = execute(registry, ToolCall(tool="sleep", args={"seconds": 2.0}), run_id="exec-test")

    assert result.ok is False
    assert result.error.code == ToolErrorCode.TIMEOUT
    assert result.duration_ms < 2000  # gave up at timeout_s, didn't wait out the sleep


def test_write_note_then_read_note():
    registry = _registry()

    written = execute(
        registry,
        ToolCall(tool="write_note", args={"text": "hello sandbox"}),
        run_id="exec-test",
    )
    assert written.ok is True
    note_name = written.value["name"]

    read = execute(
        registry, ToolCall(tool="read_note", args={"name": note_name}), run_id="exec-test"
    )

    assert read.ok is True
    assert read.value["text"] == "hello sandbox"
    assert written.duration_ms >= 0
    assert read.duration_ms >= 0


def test_traversal_blocked_at_exec_layer():
    registry = _registry()

    result = execute(
        registry, ToolCall(tool="read_note", args={"name": "../x"}), run_id="exec-test"
    )

    assert result.ok is False
    assert result.error.code == ToolErrorCode.EXEC_ERROR
    assert "traversal" in result.error.message


def test_permission_denied_when_requested_exceeds_spec():
    registry = _registry()

    result = execute(
        registry,
        ToolCall(tool="write_note", args={"text": "x"}),
        run_id="exec-test",
        requested=ToolPermissions(fs_write=True, network=True),
    )

    assert result.ok is False
    assert result.error.code == ToolErrorCode.PERMISSION_DENIED
    assert result.error.retryable is False


class _FlakyArgs(ToolArgs):
    pass


class _FlakyResult(BaseModel):
    attempt: int


def test_execute_with_retry_retries_transient_errors_then_succeeds():
    registry = _registry()
    state = {"calls": 0}

    def _flaky(_args: _FlakyArgs) -> _FlakyResult:
        state["calls"] += 1
        if state["calls"] < 3:
            time.sleep(0.3)  # exceeds this tool's short timeout_s -> TIMEOUT
        return _FlakyResult(attempt=state["calls"])

    registry.register(
        ToolSpec(
            name="flaky",
            description="test-only: TIMEOUT twice, then succeeds",
            permissions=ToolPermissions(),
            args_model=_FlakyArgs,
            result_model=_FlakyResult,
            fn=_flaky,
            timeout_s=0.05,
            max_retries=5,
        )
    )

    result = execute_with_retry(
        registry,
        ToolCall(tool="flaky", args={}),
        run_id="exec-test",
        max_retries=3,
        backoff_base_s=0.01,
    )

    assert state["calls"] == 3
    assert result.ok is True
    assert result.value["attempt"] == 3
    assert result.attempts == 3
