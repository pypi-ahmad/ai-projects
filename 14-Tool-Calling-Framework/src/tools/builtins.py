"""Built-in allowlisted tools: calc, now, json_query, write_note, read_note.

calc/now/json_query take only their args model. write_note/read_note also
take `run_id` (the sandbox directory to confine to) -- sandbox.py's
`_call_fn` inspects each tool's `fn` signature at call time and passes
`run_id` only to the ones that ask for it, so this file doesn't need to
standardize the two shapes itself.

Next: sandbox.py, for how these get executed (permission check, timeout,
the `sandbox_path` jail `write_note`/`read_note` rely on).
"""

from __future__ import annotations

import ast
import operator
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .registry import Registry
from .sandbox import sandbox_path
from .schema import ToolArgs, ToolPermissions, ToolSpec

# --- calc ---------------------------------------------------------------

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_MAX_POW_MAGNITUDE = 1000  # ponytail: caps ** so one call can't hang on a huge exponent


class CalcArgs(ToolArgs):
    expression: str


class CalcResult(BaseModel):
    value: float


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            msg = f"unsupported constant: {node.value!r}"
            raise ValueError(msg)
        return node.value
    if isinstance(node, ast.BinOp):
        op = _ALLOWED_BINOPS.get(type(node.op))
        if op is None:
            msg = f"unsupported operator: {type(node.op).__name__}"
            raise ValueError(msg)
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if op is operator.pow and (abs(left) > _MAX_POW_MAGNITUDE or abs(right) > _MAX_POW_MAGNITUDE):
            msg = "exponent too large"
            raise ValueError(msg)
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_UNARYOPS.get(type(node.op))
        if op is None:
            msg = f"unsupported operator: {type(node.op).__name__}"
            raise ValueError(msg)
        return op(_eval_node(node.operand))
    msg = f"unsupported expression: {type(node).__name__} (names are not allowed)"
    raise ValueError(msg)


def calc(args: CalcArgs) -> CalcResult:
    tree = ast.parse(args.expression, mode="eval")
    return CalcResult(value=float(_eval_node(tree)))


# --- now ------------------------------------------------------------------


class NowArgs(ToolArgs):
    tz: str | None = None


class NowResult(BaseModel):
    iso: str
    tz: str
    epoch: float


def now(args: NowArgs) -> NowResult:
    dt = datetime.now(UTC) if args.tz is None else datetime.now(ZoneInfo(args.tz))
    return NowResult(iso=dt.isoformat(), tz=args.tz or "UTC", epoch=dt.timestamp())


# --- json_query -------------------------------------------------------------


class JsonQueryArgs(ToolArgs):
    obj: Any
    pointer: str


class JsonQueryResult(BaseModel):
    value: Any


def _resolve_pointer(obj: Any, pointer: str) -> Any:
    if pointer == "":
        return obj
    if not pointer.startswith("/"):
        msg = f"pointer must start with '/': {pointer!r}"
        raise ValueError(msg)
    current = obj
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            msg = f"cannot index into {type(current).__name__} with {token!r}"
            raise KeyError(msg)
    return current


def json_query(args: JsonQueryArgs) -> JsonQueryResult:
    return JsonQueryResult(value=_resolve_pointer(args.obj, args.pointer))


# --- write_note / read_note -------------------------------------------------


class WriteNoteArgs(ToolArgs):
    text: str


class WriteNoteResult(BaseModel):
    name: str
    bytes_written: int


def write_note(args: WriteNoteArgs, run_id: str) -> WriteNoteResult:
    name = f"{uuid.uuid4().hex}.txt"
    data = args.text.encode("utf-8")
    sandbox_path(run_id, name).write_bytes(data)
    return WriteNoteResult(name=name, bytes_written=len(data))


class ReadNoteArgs(ToolArgs):
    name: str


class ReadNoteResult(BaseModel):
    text: str


def read_note(args: ReadNoteArgs, run_id: str) -> ReadNoteResult:
    path = sandbox_path(run_id, args.name)
    if not path.is_file():
        msg = f"no such note: {args.name!r}"
        raise FileNotFoundError(msg)
    return ReadNoteResult(text=path.read_text(encoding="utf-8"))


# --- registration -----------------------------------------------------------


def register_builtins(registry: Registry) -> None:
    registry.register(
        ToolSpec(
            name="calc",
            description="Evaluate a basic arithmetic expression (+ - * / // % **). No names, no calls.",
            permissions=ToolPermissions(),
            args_model=CalcArgs,
            result_model=CalcResult,
            fn=calc,
            timeout_s=5.0,
            max_retries=1,
        )
    )
    registry.register(
        ToolSpec(
            name="now",
            description="Current date/time, optionally in a named IANA timezone (e.g. 'America/New_York').",
            permissions=ToolPermissions(),
            args_model=NowArgs,
            result_model=NowResult,
            fn=now,
            timeout_s=5.0,
            max_retries=1,
        )
    )
    registry.register(
        ToolSpec(
            name="json_query",
            description="Extract a value from a JSON-like object using an RFC 6901 JSON Pointer.",
            permissions=ToolPermissions(),
            args_model=JsonQueryArgs,
            result_model=JsonQueryResult,
            fn=json_query,
            timeout_s=5.0,
            max_retries=1,
        )
    )
    registry.register(
        ToolSpec(
            name="write_note",
            description="Write text to a new note file in this run's sandbox directory.",
            permissions=ToolPermissions(fs_write=True),
            args_model=WriteNoteArgs,
            result_model=WriteNoteResult,
            fn=write_note,
            timeout_s=5.0,
            max_retries=1,
        )
    )
    registry.register(
        ToolSpec(
            name="read_note",
            description="Read a note file, by name, from this run's sandbox directory.",
            permissions=ToolPermissions(fs_read=True),
            args_model=ReadNoteArgs,
            result_model=ReadNoteResult,
            fn=read_note,
            timeout_s=5.0,
            max_retries=1,
        )
    )
