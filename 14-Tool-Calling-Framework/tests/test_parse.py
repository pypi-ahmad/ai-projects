"""Repair pass on malformed JSON; extra/missing args rejected as ToolError."""

from tools.builtins import register_builtins
from tools.parse import ToolCall, ToolError, ToolErrorCode, parse_tool_call, validate_call
from tools.registry import Registry


def _registry() -> Registry:
    registry = Registry()
    register_builtins(registry)
    return registry


def test_bad_json_repaired_by_fake_repair_model():
    def fake_repair_model(_prompt: str) -> str:
        return '{"tool": "calc", "args": {"expression": "2+2"}}'

    call = parse_tool_call(
        _registry(),
        raw_output="not json at all",
        max_parse_retries=1,
        repair_model=fake_repair_model,
    )

    assert isinstance(call, ToolCall)
    assert call.tool == "calc"
    assert call.args == {"expression": "2+2"}


def test_extra_args_rejected():
    result = validate_call(_registry(), "calc", {"expression": "2+2", "extra": "nope"})

    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.VALIDATION_ERROR


def test_missing_required_arg_rejected():
    result = validate_call(_registry(), "calc", {})

    assert isinstance(result, ToolError)
    assert result.code == ToolErrorCode.VALIDATION_ERROR
