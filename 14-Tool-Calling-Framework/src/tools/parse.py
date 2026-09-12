"""Parse model output into a validated ToolCall, with a JSON-repair retry pass.

Accepted forms, tried in order:
1. provider-native `tool_calls` (OpenAI/Ollama-style: `function.name` +
   `function.arguments` as a JSON string), if given.
2. a bare `{"tool": name, "args": {...}}` JSON object.
3. the same shape inside a fenced code block.

`parse_tool_call` ties extraction + registry lookup + args validation into
one retry loop: any failure (can't extract, unknown tool, invalid args) is
sent to a `repair_model` callable -- errors + schema, "JSON only" -- for up
to `max_parse_retries` attempts before raising `ParseFail`.

Next: sandbox.py, which takes the `ToolCall` this produces and actually
runs it, and shares the `ToolError`/`ToolResult` types defined here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from .registry import Registry

RepairModel = Callable[[str], str]

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


class ToolCall(BaseModel):
    """A parsed, schema-validated call, ready to execute."""

    tool: str
    args: dict[str, Any]


class ToolErrorCode(StrEnum):
    # parse-time (src/tools/parse.py)
    PARSE_ERROR = "PARSE_ERROR"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    # execution-time (src/tools/sandbox.py, Phase 4)
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TIMEOUT = "TIMEOUT"
    EXEC_ERROR = "EXEC_ERROR"
    RESULT_VALIDATION_ERROR = "RESULT_VALIDATION_ERROR"


class ToolError(BaseModel):
    code: ToolErrorCode
    message: str
    details: Any = None
    retryable: bool = True


class ToolResult(BaseModel):
    """Outcome of executing a ToolCall (src/tools/sandbox.py:execute, Phase 4)."""

    tool: str
    ok: bool
    value: Any = None
    error: ToolError | None = None
    duration_ms: float = 0.0
    attempts: int = 1
    """How many execute() calls it took. >1 only via execute_with_retry (Phase 6)."""


class ParseFail(Exception):
    """Raised when a tool call can't be parsed/validated within max_parse_retries."""

    def __init__(self, errors: list[ToolError]) -> None:
        self.errors = errors
        codes = [e.code.value for e in errors]
        super().__init__(f"parse failed after {len(errors)} attempt(s): {codes}")


class _RawParseError(Exception):
    """Internal: raw text didn't yield a {"tool", "args"} shape at all."""


def _from_native_tool_call(entry: dict) -> tuple[str, dict[str, Any]]:
    function = entry.get("function", {})
    name = function.get("name")
    raw_args = function.get("arguments", "{}")
    if not isinstance(name, str):
        msg = "native tool_call missing function.name"
        raise _RawParseError(msg)
    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    if not isinstance(args, dict):
        msg = "native tool_call arguments did not decode to an object"
        raise _RawParseError(msg)
    return name, args


def _from_json_object(text: str) -> tuple[str, dict[str, Any]]:
    data = json.loads(text)
    if not isinstance(data, dict) or "tool" not in data or "args" not in data:
        msg = 'expected {"tool": name, "args": {...}}'
        raise _RawParseError(msg)
    tool, args = data["tool"], data["args"]
    if not isinstance(tool, str) or not isinstance(args, dict):
        msg = '"tool" must be a string and "args" an object'
        raise _RawParseError(msg)
    return tool, args


def extract_call(
    raw_output: str | None = None,
    native_tool_calls: list[dict] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Try native tool_calls, then bare JSON, then fenced JSON.

    Raises _RawParseError if none of the three forms produce a call.
    """
    if native_tool_calls:
        return _from_native_tool_call(native_tool_calls[0])
    if raw_output is None:
        msg = "no model output to parse"
        raise _RawParseError(msg)
    try:
        return _from_json_object(raw_output.strip())
    except (json.JSONDecodeError, _RawParseError):
        pass
    match = _FENCE_RE.search(raw_output)
    if match:
        try:
            return _from_json_object(match.group(1).strip())
        except (json.JSONDecodeError, _RawParseError):
            pass
    msg = f"could not extract a tool call from: {raw_output!r}"
    raise _RawParseError(msg)


def try_extract_call(
    raw_output: str | None = None,
    native_tool_calls: list[dict] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Non-raising `extract_call`: None means "this isn't shaped like a tool call".

    For a JSON-in-prompt provider, the whole reply is plain text and there's
    no structural signal (unlike a native `tool_calls` field) saying whether
    the model meant to call a tool. This lets a caller (loop.py) tell "not a
    tool call, this is the final answer" apart from "tried to call a tool
    and got the JSON wrong" -- only the latter should go through
    `parse_tool_call`'s repair loop.
    """
    try:
        return extract_call(raw_output, native_tool_calls)
    except _RawParseError:
        return None


def validate_call(registry: Registry, tool: str, args: dict[str, Any]) -> ToolCall | ToolError:
    """Look up the tool and validate its args against the tool's schema."""
    try:
        spec = registry.get(tool)
    except KeyError:
        return ToolError(code=ToolErrorCode.NOT_FOUND, message=f"no such tool: {tool!r}")
    try:
        validated = spec.args_model.model_validate(args)
    except ValidationError as exc:
        return ToolError(
            code=ToolErrorCode.VALIDATION_ERROR,
            message=f"invalid args for {tool!r}",
            details=exc.errors(),
        )
    return ToolCall(tool=tool, args=validated.model_dump())


def build_repair_prompt(registry: Registry, tool: str | None, bad_text: str, error: str) -> str:
    """Errors + schema, "JSON only" -- what gets sent to the repair model."""
    schema: Any = None
    if tool is not None:
        try:
            schema = registry.get(tool).args_model.model_json_schema()
        except KeyError:
            schema = None
    if schema is None:
        schema = registry.list_schemas()
    return (
        "A tool call could not be parsed or validated.\n"
        f"Error: {error}\n"
        'Required shape: {"tool": <tool name>, "args": <object>}\n'
        f"Schema: {json.dumps(schema)}\n"
        f"Original output:\n{bad_text}\n\n"
        "Reply with corrected JSON only. No prose, no code fences."
    )


def parse_tool_call(
    registry: Registry,
    *,
    raw_output: str | None = None,
    native_tool_calls: list[dict] | None = None,
    max_parse_retries: int,
    repair_model: RepairModel | None = None,
) -> ToolCall:
    """Extract + validate a tool call, repairing failed attempts via repair_model.

    Raises ParseFail once max_parse_retries repair attempts are exhausted
    (or immediately after the first failure if no repair_model is given).
    """
    errors: list[ToolError] = []
    text, native = raw_output, native_tool_calls
    last_tool: str | None = None

    for attempt in range(max_parse_retries + 1):
        try:
            tool, args = extract_call(text, native)
        except _RawParseError as exc:
            errors.append(ToolError(code=ToolErrorCode.PARSE_ERROR, message=str(exc)))
            last_tool = None
        else:
            last_tool = tool
            result = validate_call(registry, tool, args)
            if isinstance(result, ToolCall):
                return result
            errors.append(result)

        if attempt == max_parse_retries or repair_model is None:
            break
        prompt = build_repair_prompt(registry, last_tool, text or "", errors[-1].message)
        text, native = repair_model(prompt), None

    raise ParseFail(errors)
