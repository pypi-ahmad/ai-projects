"""Discover -> call -> parse -> validate -> permission check -> execute -> result, bounded retries.

`run()` drives one conversation forward: call the provider with the
registry's tool schemas; if it made a tool call (native, or JSON-in-prompt
text shaped like one), execute it, append the result, and go again; if it
just answered, return that as the final text; after `max_tool_iters`
rounds with no final answer, stop with HIT_MAX_TOOLS instead of looping
forever.

Every iteration is appended to `data/logs/runs.jsonl`, one JSON object per
line, with any string over `REDACT_MAX_LEN` characters replaced by a
`<redacted: N chars>` placeholder -- this catches a `write_note` body or a
long final answer alike, not just tool text specifically.

CLI: `python -m src.tools.loop --text "..."` (run from the project root).

Next: providers.py, for what `provider.chat()` actually does per backend,
or api.py, for the HTTP endpoint that calls `run()` on a model's behalf.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any

from .builtins import register_builtins
from .parse import ParseFail, RepairModel, ToolCall, ToolError, ToolErrorCode, ToolResult, parse_tool_call, try_extract_call
from .providers import Provider, get_provider
from .registry import Registry
from .sandbox import execute_with_retry

LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "logs" / "runs.jsonl"
REDACT_MAX_LEN = 200


class LoopStatus(StrEnum):
    FINAL = "FINAL"
    HIT_MAX_TOOLS = "HIT_MAX_TOOLS"


def _redact_long_strings(obj: Any, max_len: int) -> Any:
    if isinstance(obj, str):
        return obj if len(obj) <= max_len else f"<redacted: {len(obj)} chars>"
    if isinstance(obj, dict):
        return {k: _redact_long_strings(v, max_len) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_long_strings(v, max_len) for v in obj]
    return obj


def _log_iteration(entry: dict[str, Any], *, redact_max_len: int = REDACT_MAX_LEN) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    redacted = _redact_long_strings(entry, redact_max_len)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(redacted, default=str) + "\n")


def _default_registry() -> Registry:
    registry = Registry()
    register_builtins(registry)
    return registry


def _attempt_tool_call(
    registry: Registry,
    text: str | None,
    native_tool_calls: list[dict[str, Any]] | None,
    *,
    max_parse_retries: int,
    repair_model: RepairModel | None,
) -> ToolCall | ToolResult | None:
    """None means this reply is a final answer, not a tool-call attempt.

    A ToolResult return means a call was attempted but never parsed/
    validated even after repair retries -- fed back to the model as a
    failed "exec" (see docstring), not a different code path.
    """
    is_native = bool(native_tool_calls)
    is_json_in_prompt_call = not is_native and text is not None and try_extract_call(text) is not None
    if not is_native and not is_json_in_prompt_call:
        return None
    try:
        return parse_tool_call(
            registry,
            raw_output=text,
            native_tool_calls=native_tool_calls,
            max_parse_retries=max_parse_retries,
            repair_model=repair_model,
        )
    except ParseFail as exc:
        last = exc.errors[-1] if exc.errors else ToolError(code=ToolErrorCode.PARSE_ERROR, message="unknown parse failure")
        return ToolResult(tool="<unparsed>", ok=False, error=last)


def run(
    messages: list[dict[str, Any]],
    *,
    registry: Registry | None = None,
    provider: Provider | None = None,
    run_id: str | None = None,
    max_tool_iters: int = 4,
    max_parse_retries: int = 1,
    repair_model: RepairModel | None = None,
) -> dict[str, Any]:
    """Run the tool-calling loop. Returns {"status", "text", "messages", "iterations"}."""
    registry = registry or _default_registry()
    provider = provider or get_provider()
    run_id = run_id or uuid.uuid4().hex
    messages = list(messages)
    tools = registry.list()

    for iteration in range(1, max_tool_iters + 1):
        reply = provider.chat(messages, tools)
        attempt = _attempt_tool_call(
            registry,
            reply.text,
            reply.native_tool_calls,
            max_parse_retries=max_parse_retries,
            repair_model=repair_model,
        )

        if attempt is None:
            messages.append({"role": "assistant", "content": reply.text})
            _log_iteration(
                {"run_id": run_id, "iteration": iteration, "status": "FINAL", "text": reply.text}
            )
            return {"status": LoopStatus.FINAL, "text": reply.text, "messages": messages, "iterations": iteration}

        call_args: dict[str, Any] | None = None
        if isinstance(attempt, ToolCall):
            call_args = attempt.args
            messages.append(
                {
                    "role": "assistant",
                    "content": reply.text,
                    "tool_call": {"tool": attempt.tool, "args": attempt.args},
                }
            )
            result = execute_with_retry(registry, attempt, run_id=run_id)
        else:
            result = attempt  # a ToolResult already representing a failed parse

        messages.append({"role": "tool", "name": result.tool, "content": json.dumps(result.model_dump())})
        _log_iteration(
            {
                "run_id": run_id,
                "iteration": iteration,
                "tool": result.tool,
                "args": call_args,
                "ok": result.ok,
                "value": result.value,
                "error": result.error.model_dump() if result.error else None,
                "duration_ms": result.duration_ms,
            }
        )

    _log_iteration({"run_id": run_id, "status": "HIT_MAX_TOOLS", "iterations": max_tool_iters})
    return {"status": LoopStatus.HIT_MAX_TOOLS, "text": None, "messages": messages, "iterations": max_tool_iters}


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.tools.loop")
    parser.add_argument("--text", required=True, help="user message to start the conversation with")
    parser.add_argument("--provider", default="ollama", choices=["ollama", "openai", "agnes", "gemini"])
    parser.add_argument("--model", default=None, help="override the provider's default model")
    parser.add_argument("--max-tool-iters", type=int, default=4)
    args = parser.parse_args(argv)

    provider_kwargs = {"model": args.model} if args.model and args.provider != "agnes" else {}
    provider = get_provider(args.provider, **provider_kwargs)

    result = run([{"role": "user", "content": args.text}], provider=provider, max_tool_iters=args.max_tool_iters)

    print(f"status: {result['status']}")
    if result["text"] is not None:
        print(result["text"])
    return 0 if result["status"] == LoopStatus.FINAL else 1


if __name__ == "__main__":
    sys.exit(_main())
