# Threat notes

Read before changing `src/tools/{parse,loop,sandbox}.py`.

## Security posture

This is a local, single-user allowlist of tools, not a secure
multi-tenant sandbox. Everything below (permission flags, the
`fs_write` jail, timeouts, retry bounds) defends against a model
picking the wrong tool, mangling arguments, or hanging -- not against a
second, mutually-distrusting tenant, and not against an actively
malicious caller trying to break out of the process.

Concretely: `src/tools/api.py` binds to `127.0.0.1` but has no
authentication -- any process on the same machine that can reach that
port can call any registered tool as itself, with no per-caller
identity or quota. There is one registry, one sandbox root namespaced
only by `run_id` (not by user), and no isolation between runs beyond
that directory split. Running this where an untrusted party can reach
the API port, or registering a tool that itself grants access to other
users' data, is out of scope for everything documented below.

## Prompt-injected tool names

Text the model reads (a tool result, a fetched document, user input)
could contain something shaped like a tool call, trying to get the model
to invoke a tool it wasn't meant to, or to invoke a name that doesn't
exist.

- Mitigation: the registry only dispatches to names it registered at
  process start — no dynamic lookup by arbitrary string, no `eval`/
  `getattr`-by-model-supplied-name path. An unknown name is a validation
  error, not a fallback search.
- The loop acts only on the model's structured tool-call output for that
  turn. Text found inside a tool's *result* is data returned to the
  model, never re-interpreted by the loop itself as a new call.

## Path traversal

A tool with `fs_write` (or, more openly, `fs_read`) could receive an
argument that points outside its intended directory.

- `fs_write`: `src/tools/sandbox.py:sandbox_path` rejects an absolute
  `name` outright (pathlib's `/` operator would otherwise let an
  absolute right-hand side silently replace the sandbox root instead of
  joining onto it), then resolves the candidate and checks it with
  `Path.is_relative_to(root)` against `data/sandbox/<run_id>/`. `..`
  segments and symlinks that resolve outside the root raise `ValueError`
  instead of being clamped back inside — a bug in the check should fail
  loud, not fail into "somewhere probably fine." Both `write_note` and
  `read_note` call this one function (see `src/tools/builtins.py`) so
  the guard exists once, not once per tool. Phase 4's executor
  (`sandbox.py:execute`) catches that `ValueError` the same way it
  catches any other tool exception -- `EXEC_ERROR`, not a crash -- so
  traversal stays blocked even when a tool is invoked through `execute`
  rather than called directly.
- `fs_read`: no root confinement yet (see [PERMISSIONS.md](PERMISSIONS.md)).
  `read_note` reuses the same `sandbox_path` jail as `write_note`, so
  it's covered today; a future `fs_read`-only built-in that isn't a note
  tool would need its own jail or a shared one added to `sandbox.py`.

## Retry storms

Two different retry loops exist, each with its own bound -- a storm in
either burns GPU (model/repair calls) or CPU (parse/execute) on every
pass if left unbounded:

- **Parse-time** (`src/tools/parse.py:parse_tool_call`): a model stuck
  emitting malformed JSON, an unknown tool name, or invalid args gets a
  repair-model attempt and re-validation, bounded by `max_parse_retries`.
  Exhausting it raises `ParseFail` with every attempt's `ToolError`
  attached -- implemented, Phase 3.
- **Execution-time** (`src/tools/sandbox.py:execute_with_retry`): a
  `TIMEOUT` or `EXEC_ERROR` ("5xx-like": likely transient, worth another
  try) gets retried with exponential backoff, bounded by
  `ToolSpec.max_retries`. `PERMISSION_DENIED`, `VALIDATION_ERROR`, and
  `RESULT_VALIDATION_ERROR` are fixed outcomes -- retrying can't change
  them, so they return on the first attempt instead of consuming a retry
  slot pointlessly -- implemented, Phase 4.

Both bounds are per tool-call attempt within one turn, not across an
entire conversation — a later phase may need a conversation-level cap
too if a model keeps retrying the same failing call turn after turn.

## JSON-in-prompt ambiguity (Agnes AI)

A native-tool-calling provider tells `loop.py` explicitly "this is a tool
call" via a structured `tool_calls` field, separate from any plain text.
`AgnesProvider` (see [ARCHITECTURE.md](ARCHITECTURE.md)) has no such
signal -- the whole reply is text, and `loop._attempt_tool_call` decides
it's a tool-call attempt purely by whether `parse.try_extract_call`
recognizes a `{"tool", "args"}` shape in it.

- Consequence: if a user's actual request is answered with output that
  happens to parse as that exact shape (e.g. "reply with JSON like
  `{\"tool\": \"foo\", \"args\": {}}`"), it's treated as a tool-call
  attempt instead of the final answer. This is a real, known limitation
  of JSON-in-prompt mode, not a bug to silently patch around -- a
  provider without a structured signal genuinely can't distinguish these
  two intents any other way from text alone.
- This is a false-positive risk (an answer mistaken for a call), not a
  privilege-escalation one: a misfired "call" still has to name a real
  registered tool and pass its schema, same as any other attempt.
