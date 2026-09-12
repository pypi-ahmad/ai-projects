"""Permission check, timeout, fs_write jail, sandboxed execution.

Timeout is thread-based (`concurrent.futures.ThreadPoolExecutor`), not
signal-based: Windows has no `SIGALRM`, so `signal.alarm`/`signal.setitimer`
aren't available here and a signal-based timeout wouldn't be portable to
the platform this project targets. A thread-based timeout runs the same on
every platform, but it can only give up *waiting* -- Python has no safe API
to kill a running thread. When a call exceeds `timeout_s`, `execute()`
reports TIMEOUT and moves on, but the tool's function keeps running in the
background until it finishes on its own or the process exits (`pool.
shutdown(wait=False)` below -- `wait=True`, the default, would block on
exactly the hung call we're trying to stop waiting for). `asyncio.
wait_for` would have the identical caveat: a synchronous tool function
still has to run on a thread underneath it, so cancelling the await
doesn't stop that thread either. Neither approach forcibly terminates a
runaway call; only a process-level sandbox (a container or VM boundary --
explicitly out of scope, see docs/PERMISSIONS.md) can do that.

No tool in this module or in builtins.py shells out. `ToolPermissions.
shell` plus `sandbox_path`'s traversal guard are the enforcement surface a
future subprocess-based tool would sit behind -- add that opt-in
explicitly on that one tool; nothing here defaults to it.

Next: loop.py, which is what actually calls `execute_with_retry` as part
of a model-driven conversation (as opposed to a direct, single manual
call).
"""

from __future__ import annotations

import inspect
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import fields
from pathlib import Path, PurePath
from typing import Any

from pydantic import BaseModel, ValidationError

from .parse import ToolCall, ToolError, ToolErrorCode, ToolResult
from .registry import Registry
from .schema import ToolPermissions, ToolSpec

SANDBOX_ROOT = Path(__file__).resolve().parents[2] / "data" / "sandbox"

_PERMISSION_FIELDS = tuple(f.name for f in fields(ToolPermissions))
_RETRYABLE_EXEC_CODES = frozenset({ToolErrorCode.TIMEOUT, ToolErrorCode.EXEC_ERROR})


def run_dir(run_id: str) -> Path:
    """Sandbox directory for one run, created on first use."""
    d = (SANDBOX_ROOT / run_id).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def sandbox_path(run_id: str, name: str) -> Path:
    """Resolve `name` inside this run's sandbox dir; reject anything escaping it.

    `name` must be relative -- an absolute path is rejected outright, before
    it ever gets joined with the sandbox root (pathlib's `/` operator would
    otherwise let an absolute right-hand side silently replace the root).
    Whatever survives that check still has to resolve to somewhere inside
    the root; `..` segments and symlinks that escape it are rejected too.
    """
    if PurePath(name).is_absolute():
        msg = f"path traversal rejected: {name!r} (absolute path)"
        raise ValueError(msg)
    root = run_dir(run_id)
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root):
        msg = f"path traversal rejected: {name!r}"
        raise ValueError(msg)
    return candidate


def check_permissions(spec: ToolSpec, requested: ToolPermissions) -> None:
    """Raise PermissionError if `requested` asks for anything `spec.permissions` doesn't grant.

    `spec.permissions` is the ceiling a tool declared for itself; `requested`
    cannot exceed it, ever -- this is a one-way check, not a merge.
    """
    for field_name in _PERMISSION_FIELDS:
        if getattr(requested, field_name) and not getattr(spec.permissions, field_name):
            msg = f"{spec.name}: requested {field_name!r} exceeds declared permissions"
            raise PermissionError(msg)


def _call_fn(spec: ToolSpec, args: BaseModel, run_id: str) -> Any:
    """write_note/read_note also take run_id; calc/now/json_query don't ask for it."""
    if "run_id" in inspect.signature(spec.fn).parameters:
        return spec.fn(args, run_id=run_id)
    return spec.fn(args)


def _run_with_timeout(fn: Any, timeout_s: float) -> Any:
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeoutError:
        msg = f"execution exceeded {timeout_s}s"
        raise TimeoutError(msg) from None
    finally:
        pool.shutdown(wait=False)  # don't block on a call we just gave up waiting for


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def execute(
    registry: Registry,
    call: ToolCall,
    *,
    run_id: str,
    requested: ToolPermissions | None = None,
) -> ToolResult:
    """Run one already-parsed ToolCall. Never raises -- every failure becomes a ToolResult."""
    start = time.perf_counter()

    try:
        spec = registry.get(call.tool)
    except KeyError:
        return ToolResult(
            tool=call.tool,
            ok=False,
            error=ToolError(
                code=ToolErrorCode.NOT_FOUND, message=f"no such tool: {call.tool!r}"
            ),
            duration_ms=_elapsed_ms(start),
        )

    try:
        check_permissions(spec, spec.permissions if requested is None else requested)
    except PermissionError as exc:
        return ToolResult(
            tool=call.tool,
            ok=False,
            error=ToolError(
                code=ToolErrorCode.PERMISSION_DENIED, message=str(exc), retryable=False
            ),
            duration_ms=_elapsed_ms(start),
        )

    try:
        args = spec.args_model.model_validate(call.args)
    except ValidationError as exc:
        return ToolResult(
            tool=call.tool,
            ok=False,
            error=ToolError(
                code=ToolErrorCode.VALIDATION_ERROR,
                message=f"invalid args for {call.tool!r}",
                details=exc.errors(),
            ),
            duration_ms=_elapsed_ms(start),
        )

    try:
        raw_result = _run_with_timeout(lambda: _call_fn(spec, args, run_id), spec.timeout_s)
    except TimeoutError as exc:
        return ToolResult(
            tool=call.tool,
            ok=False,
            error=ToolError(code=ToolErrorCode.TIMEOUT, message=str(exc)),
            duration_ms=_elapsed_ms(start),
        )
    except Exception as exc:  # noqa: BLE001 -- a tool's own bug must become EXEC_ERROR, not a crash
        return ToolResult(
            tool=call.tool,
            ok=False,
            error=ToolError(
                code=ToolErrorCode.EXEC_ERROR, message=f"{type(exc).__name__}: {exc}"
            ),
            duration_ms=_elapsed_ms(start),
        )

    try:
        value = (
            raw_result
            if isinstance(raw_result, spec.result_model)
            else spec.result_model.model_validate(raw_result)
        )
    except ValidationError as exc:
        return ToolResult(
            tool=call.tool,
            ok=False,
            error=ToolError(
                code=ToolErrorCode.RESULT_VALIDATION_ERROR,
                message=f"{call.tool!r} returned a result that failed its own schema",
                details=exc.errors(),
                retryable=False,
            ),
            duration_ms=_elapsed_ms(start),
        )

    return ToolResult(
        tool=call.tool, ok=True, value=value.model_dump(), duration_ms=_elapsed_ms(start)
    )


def execute_with_retry(
    registry: Registry,
    call: ToolCall,
    *,
    run_id: str,
    requested: ToolPermissions | None = None,
    max_retries: int | None = None,
    backoff_base_s: float = 0.1,
) -> ToolResult:
    """Retry TIMEOUT/EXEC_ERROR ("5xx-like") up to max_retries times with backoff.

    Everything else -- NOT_FOUND, PERMISSION_DENIED, VALIDATION_ERROR (bad
    args), RESULT_VALIDATION_ERROR (bad result) -- is a fixed outcome that
    retrying can't change, so it's returned on the first attempt and
    surfaced to the model once, not retried here.
    """
    if max_retries is None:
        try:
            max_retries = registry.get(call.tool).max_retries
        except KeyError:
            max_retries = 0

    result = execute(registry, call, run_id=run_id, requested=requested)
    attempt = 0
    while (
        not result.ok
        and result.error is not None
        and result.error.code in _RETRYABLE_EXEC_CODES
        and attempt < max_retries
    ):
        time.sleep(backoff_base_s * (2**attempt))
        attempt += 1
        result = execute(registry, call, run_id=run_id, requested=requested)
    result.attempts = attempt + 1
    return result
