# ToolSpec

Implemented in `src/tools/schema.py` (Phase 2). `src/tools/loop.py:run`
calls `fn` end-to-end via `sandbox.py:execute`/`execute_with_retry`
(Phase 4-6); nothing here is aspirational anymore.

A call in flight (before/after `fn` runs) is a different set of types --
`ToolCall`, `ToolError` (codes: `PARSE_ERROR`, `NOT_FOUND`,
`VALIDATION_ERROR`, `PERMISSION_DENIED`, `TIMEOUT`, `EXEC_ERROR`,
`RESULT_VALIDATION_ERROR`; see `ToolErrorCode` in `src/tools/parse.py`
for the current, authoritative list), `ToolResult`; defined in
`src/tools/parse.py` (Phase 3-4), not here. `ToolSpec` is the tool's
static contract; those are a call's runtime state.

## Fields

| Field | Type | Purpose |
|---|---|---|
| `name` | `str` | Stable identifier the model must emit exactly to call this tool. Unique in the registry; registering a duplicate name raises, never silently overwrites. Must match `^[a-z][a-z0-9_]*$` (enforced in `__post_init__`). |
| `description` | `str` | Natural-language summary shown to the model during discovery; what the tool does and when to use it. |
| `args_model` | `type[pydantic.BaseModel]` | Defines and validates the tool's arguments. Its JSON schema is what the model sees (via `Registry.list`/`list_schemas`); incoming call arguments are parsed against this model before execution. Every built-in subclasses `tools.schema.ToolArgs`, which sets `model_config = ConfigDict(extra="forbid")`; an argument the model wasn't asked for is a validation error, not silently dropped. |
| `result_model` | `type[pydantic.BaseModel]` | Shape of a successful result. `sandbox.py:execute` accepts `fn` returning an instance of it directly, or coerces via `result_model.model_validate(raw_result)` if not; either way, a result that doesn't fit the schema is `ToolErrorCode.RESULT_VALIDATION_ERROR`, not a silent pass-through. |
| `permissions` | `ToolPermissions` | `{cpu, fs_read, fs_write, network, shell}` flags (see [PERMISSIONS.md](PERMISSIONS.md)). Default: cpu-only. |
| `fn` | `Callable[..., Any]` | The actual function invoked once args are validated and permissions clear. Built-ins take `(args_model_instance)`; `write_note`/`read_note` also take `run_id`. `sandbox.py:_call_fn` calls whichever shape applies via `inspect.signature(spec.fn)`; a tool's own signature decides, not a flag on `ToolSpec`. |
| `timeout_s` | `float` | Wall-clock limit for one execution, enforced by `sandbox.py:execute` (`concurrent.futures.ThreadPoolExecutor`; see that module's docstring for what a timeout on Windows can and can't actually stop). Exceeding it produces `ToolErrorCode.TIMEOUT`. |
| `max_retries` | `int` | Bound on retrying a `TIMEOUT`/`EXEC_ERROR` **execution** failure, consumed by `sandbox.py:execute_with_retry` with exponential backoff. Unrelated to `parse_tool_call`'s `max_parse_retries` argument (a separate, caller-supplied bound for repairing a malformed/invalid *parse* attempt, not a `ToolSpec` field); see [ARCHITECTURE.md](ARCHITECTURE.md) and [THREAT_NOTES.md](THREAT_NOTES.md) (retry storms) for both. |

## Registration

```python
from tools.registry import Registry
from tools.schema import ToolPermissions, ToolSpec

registry = Registry()
registry.register(
    ToolSpec(
        name="calc",
        description="...",
        permissions=ToolPermissions(),
        args_model=CalcArgs,
        result_model=CalcResult,
        fn=calc,
        timeout_s=5.0,
        max_retries=1,
    )
)
```

Plain imperative `register(spec)`; no decorator, no filesystem or plugin
scan. Discovery (`Registry.list`/`list_schemas`) only ever lists what was
explicitly registered at process start; there is no path for a tool to
register itself from model output or user-supplied code (see
[THREAT_NOTES.md](THREAT_NOTES.md), prompt-injected tool names).
`src/tools/builtins.py:register_builtins(registry)` registers the five
built-in tools this way.

## Naming rule

`name` must match `^[a-z][a-z0-9_]*$`; this is also the exact string the
model is asked to emit, so it stays unambiguous against surrounding
prompt or tool-result text.
