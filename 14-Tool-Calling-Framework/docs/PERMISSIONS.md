# Permissions

Implemented in `src/tools/schema.py` (flags) and `src/tools/sandbox.py`
(enforcement: `check_permissions`, `sandbox_path`).

## Flags

Every `ToolSpec.permissions` sets these, default shown:

| Flag | Default | Effect |
|---|---|---|
| `cpu` | `True` | Tool may run compute. All tools have this. |
| `fs_read` | `False` | Tool may read files. Not path-confined beyond the note tools reusing `sandbox_path`; see [THREAT_NOTES.md](THREAT_NOTES.md), path traversal. |
| `fs_write` | `False` | Tool may write files, confined to the sandbox root below. A write path outside it is rejected, not redirected. |
| `network` | `False` | Tool may make outbound calls. None of the built-in tools set this. |
| `shell` | `False` | Tool may invoke a shell/subprocess. No default shell tool exists; this flag exists so one could be registered deliberately, never implicitly; and even then, no built-in ever shells out (see "No subprocess" below). |

Denying by default and requiring an explicit flag per tool means a new
tool starts with no reach beyond CPU until its author states otherwise.

## Requested vs. declared

`sandbox.py:execute` takes an optional `requested: ToolPermissions` for
the call. `check_permissions` checks it field-by-field against
`spec.permissions` and raises if `requested` asks for anything the tool
didn't declare; `PERMISSION_DENIED`, non-retryable, since the tool's
declaration won't change on a retry. This is one-way: `requested` is a
ceiling that can only sit at or below what the tool declared for itself,
never above it. Callers that don't pass `requested` get `spec.permissions`
as the default, i.e. exactly what the tool asked for; the check exists
for a future caller (a run/session policy in `loop.py`, say) that wants to
clamp a call down further, not to grant anything extra.

## Sandbox root

`data/sandbox/<run_id>/`; one directory per run, created before that
run's first `fs_write`-permitted call. `sandbox_path(run_id, name)`
rejects an absolute `name` outright, then resolves the joined path and
checks it against this root; `..` segments and symlinks that would land
outside it are rejected the same way; see [THREAT_NOTES.md](THREAT_NOTES.md).

`fs_read` has no equivalent root confinement of its own; a tool granted
`fs_read` can read anywhere the OS process can. `read_note` happens to be
safe because it reuses `sandbox_path`, not because `fs_read` itself is
jailed. This is a known gap, not an oversight; see
[THREAT_NOTES.md](THREAT_NOTES.md).

## No subprocess

No built-in tool shells out, and nothing in `sandbox.py` runs one on a
tool's behalf. If a future tool genuinely needs a subprocess, it must set
`permissions.shell=True` explicitly on its own `ToolSpec`; there is no
default or implicit path to a shell.
