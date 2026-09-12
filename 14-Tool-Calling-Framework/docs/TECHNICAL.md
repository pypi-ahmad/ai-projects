# Technical notes

## Stack

Plain Python 3.13, no application framework beyond FastAPI (HTTP surface)
and Streamlit (UI). No database, no ORM, no message queue anywhere in
`src/tools/`.

| Library | Used for | Why (per the code) |
|---|---|---|
| `pydantic` v2 | `ToolSpec.args_model`/`result_model`, all request/response bodies in `api.py` | Both runtime validation (`ToolArgs` subclasses set `model_config = ConfigDict(extra="forbid")` — an argument the model wasn't asked for is a validation error, not a silent drop) and JSON Schema generation: `Registry.list()`/`list_schemas()` call `.model_json_schema()` directly on each tool's args model to build what gets sent to the LLM. |
| `requests` | `OllamaProvider`, `OpenAICompatibleProvider`, `AgnesProvider` | `providers.py`'s module docstring: these three backends' wire protocol is "simple, stable, already verified" (OpenAI-shaped JSON over plain HTTP), so no SDK is needed. |
| `google-genai` | `GeminiProvider` only | Same docstring, for the opposite reason: Gemini's function-calling wire format (camelCase REST fields, distinct `functionCall`/`functionResponse` content parts) is called out as a "distinct protocol" not safe to hand-roll — the official SDK is used specifically to avoid getting that wrong. |
| `fastapi` + `uvicorn` | `src/tools/api.py` | The three documented HTTP endpoints; `uvicorn` is the ASGI server `run.cmd` invokes it with. |
| `streamlit` | `src/tools/ui.py` | The only UI in the repo. |
| `concurrent.futures.ThreadPoolExecutor` (stdlib) | `sandbox.py`'s `_run_with_timeout` | Module docstring: Windows has no `SIGALRM`, so a signal-based timeout isn't portable here; a thread-based timeout works everywhere but can only stop *waiting* for a call, not kill the thread running it. |
| `ast` (stdlib) | `builtins.py`'s `calc` tool | Parses the expression and walks the tree, evaluating only an explicit allowlist of node types (`Add`/`Sub`/`Mult`/`Div`/`FloorDiv`/`Mod`/`Pow`/`UAdd`/`USub`, and `Constant` restricted to `int`/`float` with `bool` explicitly excluded). Any other node — a `Name`, a `Call` — hits the final `raise ValueError` in `_eval_node`. This is how "no names, no calls" is enforced structurally, not by pattern-matching the input string. |
| `zoneinfo` (stdlib) | `builtins.py`'s `now` tool | Named-timezone lookups (`ZoneInfo(args.tz)`). See the `tzdata` note below — this only works because of a dependency that isn't pinned for this purpose. |

`tzdata` (currently `2026.4` in this environment) is installed but does
**not** appear in `requirements.txt`. It's present only because `pandas`
(itself pulled in transitively by `streamlit`) depends on it. Windows
doesn't ship the IANA timezone database, and `zoneinfo` falls back to the
`tzdata` PyPI package when the OS doesn't provide one — so the `now` tool's
`tz` argument works today, but nothing in `requirements.txt` guarantees it
keeps working if `streamlit`'s or `pandas`'s own dependencies ever change.

## Invariants

- **Tool names** must match `^[a-z][a-z0-9_]*$`, enforced in
  `ToolSpec.__post_init__` (`schema.py`) — this is also the exact string an
  LLM is asked to emit to call the tool.
- **Registry entries are write-once.** `Registry.register()` raises
  `ValueError` on a duplicate name; there is no update/overwrite path.
- **Permission requests are one-way.** `sandbox.check_permissions()` only
  ever checks that a `requested: ToolPermissions` doesn't exceed
  `spec.permissions`; there's no merge and no way for a caller to grant a
  tool more than it declared for itself.
- **Sandbox paths reject absolute input before joining.**
  `sandbox.sandbox_path()` calls `PurePath(name).is_absolute()` and raises
  first, specifically because pathlib's `/` operator lets an absolute
  right-hand operand silently replace the left side instead of joining
  onto it — joining first and checking after would have been too late.
  After that, the joined-and-resolved path is still checked with
  `Path.is_relative_to(root)` against `data/sandbox/<run_id>/`.
- **Two separate, differently-scoped retry bounds exist.**
  `parse_tool_call(..., max_parse_retries=...)` (a plain function argument,
  not stored anywhere) bounds re-prompting the model after a parse/
  validation failure. `ToolSpec.max_retries` (a field on the tool's static
  spec) bounds `sandbox.execute_with_retry()`'s backoff-and-retry of
  `TIMEOUT`/`EXEC_ERROR` outcomes. They are unrelated numbers read from
  unrelated places, despite the similar names.

## Error handling

`sandbox.execute()` is written to never raise: a missing tool, a
permission check failure, an invalid-args error, a timeout, any exception
raised by the tool's own `fn`, and a result that fails its own
`result_model` validation are all caught and returned as
`ToolResult(ok=False, error=ToolError(code=..., ...))` with a
`ToolErrorCode` (`NOT_FOUND`, `PERMISSION_DENIED`, `VALIDATION_ERROR`,
`TIMEOUT`, `EXEC_ERROR`, `RESULT_VALIDATION_ERROR`) and a `retryable` flag.
`api.py`'s `POST /v1/call` returns this directly, so an unknown tool name
is an HTTP 200 with `"ok": false`, not a 500.

That contract does **not** extend to the provider layer. `api.py`'s
`POST /v1/loop` calls `get_provider(req.provider)` and then `loop_run(...)`
with no `try`/`except` around either call. A missing required environment
variable raises `RuntimeError` from `providers._require_env`; a
provider's `requests.post` call raises `requests.exceptions.RequestException`
(or subclasses, e.g. a connection error if Ollama isn't running) if the
HTTP call itself fails before returning a response. Neither is caught
anywhere between `providers.py` and `api.py`, so both surface as an
unhandled exception — FastAPI's default 500 response for `/v1/loop`, or a
raw Python traceback for the CLI (`python -m src.tools.loop`).

## Persistence

Two locations under `data/`, both gitignored except for a tracked
`.gitkeep` in each (see `.gitignore`):

- `data/sandbox/<run_id>/` — created on first use by `sandbox.run_dir()`.
  Currently only written to by `write_note` and read from by `read_note`.
  Nothing deletes old run directories.
- `data/logs/runs.jsonl` — appended to by `loop._log_iteration()`, one JSON
  object per loop iteration (a tool call's `tool`/`args`/`ok`/`value`/
  `error`/`duration_ms`, or a final `status`/`text`/`iterations`). Any
  string over `loop.REDACT_MAX_LEN` (200) characters is replaced with
  `<redacted: N chars>` before writing — this is a blanket string-length
  check (`loop._redact_long_strings`), not specific to any one tool's
  field. Nothing rotates or trims this file.

## Extending: adding a tool

A tool is a plain function plus a `ToolSpec` registered into a `Registry`
— there is no decorator or filesystem/plugin discovery mechanism
(`registry.register(spec)` is the only entry point; see `src/tools/
builtins.py` for the five built-in tools and `src/tools/schema.py` for
every `ToolSpec` field). The args model must subclass `schema.ToolArgs`
to get the `extra="forbid"` behavior described above.
