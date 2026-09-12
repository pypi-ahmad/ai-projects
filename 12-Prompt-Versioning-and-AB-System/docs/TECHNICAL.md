# Technical notes

## Stack, and why (where the code makes it obvious)

- **SQLite via stdlib `sqlite3`, no ORM.** Every store (`Registry`,
  `ExperimentStore`, `OutcomeStore`) opens its own connection per call
  (`sqlite3.connect(...)`, closed via `contextlib.closing`). No
  connection pool, no ORM layer; schema is raw `CREATE TABLE IF NOT
  EXISTS` strings executed at construction time.
- **Pydantic v2 models everywhere** (`registry/models.py`,
  `split/models.py`, `outcomes/models.py`, `execute/models.py`,
  `api/schemas.py`); both the domain types and the HTTP request/response
  bodies are the same kind of model, and FastAPI serializes the domain
  models directly as `response_model`.
- **FastAPI + uvicorn** for the HTTP layer (`api/app.py`, `api/__main__.py`)
 ; the app uses the current `lifespan` async-context-manager startup
  pattern, not the deprecated `@app.on_event`.
- **Streamlit** for the admin UI (`ui/app.py`); a single-file script;
  page config, theme, and port live in `.streamlit/config.toml`.
- **`argparse`** for both CLIs (`registry/__main__.py`,
  `outcomes/__main__.py`); stdlib only, one subcommand each.
- **`uv` + `uv_build`** for packaging (`pyproject.toml`
  `[build-system]`); `requirements.txt` is a generated export
  (`uv export --no-dev --no-hashes`), not hand-maintained.

## Invariants

- **A `Version` row is never updated, only inserted.** `Registry.publish`
  (`registry/storage.py`) always does `INSERT`; there is no `UPDATE`
  statement touching `versions` anywhere in the codebase.
- **Version numbers are monotonic per prompt, not content-addressed.**
  Publishing identical `(body, config)` twice creates two distinct
  version rows with different `version` numbers; `publish` does not
  deduplicate by content hash.
- **Body files on disk are never overwritten.** `Registry.get` re-reads
  the file at `body_path` and recomputes its sha256 on every call,
  raising `IntegrityError` if it no longer matches the value stored at
  publish time (`registry/storage.py`).
- **At most one `running` experiment per prompt.** Enforced by a SQLite
  partial unique index (`CREATE UNIQUE INDEX ... WHERE status =
  'running'` in `split/storage.py`), not just application logic.
- **Arm weights must sum to exactly 100.** Validated in
  `split/models.py`'s `validate_arms`, called both when constructing an
  `Experiment` (Pydantic `model_validator`) and again explicitly in
  `ExperimentStore.create_experiment` before the row is written.
- **A user's first sticky assignment sticks, even if the experiment's
  salt or weights change later.** `ExperimentStore._assign`
  (`split/storage.py`) does `INSERT OR IGNORE` into `assignments`, then
  re-reads whatever row is actually there; so a concurrent duplicate
  resolve can't overwrite an existing assignment.
- **`user_key` is never persisted in plain text.** `OutcomeStore.record`
  (`outcomes/storage.py`) stores only `sha256(user_key)`; the raw value
  exists only transiently in memory during the call.
- **The sticky-assignment hash and its salt are not a security
  mechanism**; see "State" in `docs/ARCHITECTURE.md`.

## Error handling

Every `raise` in `src/promptreg/` (grep for `raise ` to confirm this list
is current):

| Exception | Raised where | Meaning |
|---|---|---|
| `KeyError` | `registry/storage.py`, `split/storage.py` | no such version / prompt / experiment (missing lookup) |
| `IntegrityError` (`registry/storage.py`) | `Registry.get` | on-disk body no longer matches its stored sha256 |
| `ValueError` | `registry/models.py`, `registry/storage.py`, `split/models.py`, `split/storage.py` | bad slug, no prior pointer to roll back to, arms don't sum to 100 / aren't unique / are empty, a second `running` experiment for the same prompt |
| `TemplateRenderError` (`execute/render.py`) | `render` | a `{placeholder}` in the prompt body had no matching key in `variables` |
| `RuntimeError` | `outcomes/storage.py`, `split/storage.py`, `registry/__main__.py` | an insert/update that should have produced a row didn't (defensive; not expected to trigger in normal operation) |

The HTTP API (`api/app.py`) maps these centrally via
`@app.exception_handler(...)`: `KeyError` -> 404, `ValueError` -> 400,
`IntegrityError` -> 500, `TemplateRenderError` -> 400. No route has its
own per-error try/except beyond that.

Nothing in `src/` catches and silently swallows an exception except one
deliberate spot: `execute()` (`execute/completer.py`) catches any
exception raised by a *registered* completer and converts it to
`ExecutionResult(ok=False, ...)` rather than propagating; the comment
there explains why (a bad provider call should never take down the
resolve/execute/record pipeline).

## Persistence paths

| Path | Format | Written by |
|---|---|---|
| `data/registry.db` (or `$PROMPTREG_DB_PATH`) | SQLite | `Registry`, `ExperimentStore`, `OutcomeStore`; one shared file, separate tables |
| `data/prompts/<name>/<version>.md` | plain text | `Registry.publish`, never rewritten after |
| `data/outcomes.jsonl` (or `$PROMPTREG_OUTCOMES_JSONL`) | JSON Lines, append-only | `OutcomeStore.record` (one line), `OutcomeStore.track` (one more line per call); never rewritten in place |

Field-by-field schema for every SQLite table: `docs/DATA.md`.
