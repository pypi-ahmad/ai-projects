# promptreg

A registry for prompts and their configs, backed by SQLite and a FastAPI
HTTP API with a Streamlit admin UI. It stores prompt bodies as immutable,
content-verified versions; lets an admin point a `prod`/`staging`
environment at a version and roll that pointer back; runs weighted, sticky
A/B experiments across versions of the same prompt; and records outcome
events (success, latency, thumbs, custom metrics) per resolved request.

## Requirements

- Python >=3.13 (`.python-version` pins `3.13.15`; developed and tested on
  it).
- Runtime dependencies, from `pyproject.toml`: `fastapi>=0.141.1`,
  `uvicorn>=0.52.4`, `pydantic>=2.13.5`, `streamlit>=1.63.0`. Dev-only:
  `pytest`, `ruff`, `ty`, `httpx>=0.28.1` (`fastapi.testclient` needs it).
  Full transitive pin list: `requirements.txt` / `uv.lock`.
- [`uv`](https://docs.astral.sh/uv/) for development (`uv sync`, `uv run`).
  Not required to just *run* the app — `run.cmd` uses plain `venv` + `pip`.
- Windows: developed and tested on Windows 11 (native, no WSL2, no
  Docker — none of the tooling here needs either). `run.cmd` is a Windows
  batch file; the underlying Python code is not Windows-specific, but
  nothing here has been run on Linux/macOS.

## Setup and run

```
run.cmd
```

Creates/reuses `.venv`, installs from `requirements.txt` (bootstrapping
`pip` via `ensurepip` first if the venv doesn't have it), then starts the
HTTP API and the Streamlit UI together (see `run.cmd` for the exact
commands it runs).

Run them separately instead:

```
uv sync --all-groups
uv run python -m promptreg.api
uv run streamlit run src/promptreg/ui/app.py
```

The API binds `127.0.0.1:8000` (override with `PROMPTREG_API_PORT`); the
UI listens on the port set in `.streamlit/config.toml` (currently `7016`).
Neither is bound to `0.0.0.0` — both are localhost-only as shipped.

The Streamlit UI imports `Registry`/`ExperimentStore`/`OutcomeStore`
directly (see `src/promptreg/ui/app.py`) — it does not call the HTTP API,
and needs no admin token.

If no `PROMPTREG_ADMIN_TOKEN` is set, the API generates one with
`secrets.token_urlsafe(24)` and prints it once at startup
(`src/promptreg/api/app.py`, `lifespan`). Every write route requires it as
the `X-Admin-Token` header; `GET /v1/prompts/{name}/versions`,
`POST /v1/resolve`, and `POST /v1/complete` don't.

### A minimal walkthrough: publish → point prod → split → rollback

With the API running and `<token>` replaced by the printed admin token:

```bash
# 1. publish — two versions, so there's something to split and roll back between
curl -X POST http://127.0.0.1:8000/v1/prompts/greet/versions -H "X-Admin-Token: <token>" -H "Content-Type: application/json" -d "{\"body\":\"Hello, {name}!\",\"config\":{\"model\":\"stub\",\"provider\":\"stub\"},\"changelog\":\"v1\",\"author\":\"ada\"}"
curl -X POST http://127.0.0.1:8000/v1/prompts/greet/versions -H "X-Admin-Token: <token>" -H "Content-Type: application/json" -d "{\"body\":\"Hi {name}, welcome!\",\"config\":{\"model\":\"stub\",\"provider\":\"stub\"},\"changelog\":\"v2\",\"author\":\"ada\"}"

# 2. point prod — at v1, then v2, so rollback (step 4) has a prior value to return to
curl -X PUT http://127.0.0.1:8000/v1/prompts/greet/pointer/prod -H "X-Admin-Token: <token>" -H "Content-Type: application/json" -d "{\"version\":1}"
curl -X PUT http://127.0.0.1:8000/v1/prompts/greet/pointer/prod -H "X-Admin-Token: <token>" -H "Content-Type: application/json" -d "{\"version\":2}"

# 3. split — an experiment starts in `draft`, so create then start
curl -X POST http://127.0.0.1:8000/v1/experiments -H "X-Admin-Token: <token>" -H "Content-Type: application/json" -d "{\"name\":\"demo-split\",\"prompt_name\":\"greet\",\"arms\":[{\"name\":\"control\",\"version\":1,\"weight\":50},{\"name\":\"treat_a\",\"version\":2,\"weight\":50}]}"
curl -X POST http://127.0.0.1:8000/v1/experiments/1/start -H "X-Admin-Token: <token>"

# 4. rollback — prod moves back from v2 to v1
curl -X POST http://127.0.0.1:8000/v1/prompts/greet/rollback/prod -H "X-Admin-Token: <token>"
```

Steps 1, 2, and 3 are two calls each: `publish` needs a second version to
have something to split and roll back between; a fresh experiment starts
in `draft` and needs an explicit `/start`; `rollback` needs two prior
pointer values to have one to return to. Four steps matching
publish/point/split/rollback, not four bare HTTP calls. This exact
sequence has been run against a live server: step 4 moves `prod` from v2
back to v1.

Prefer demo data over building it by hand?

```
uv run python scripts/seed_demo.py
```

Publishes `greet` v1/v2 (`config={"model": "stub", "provider": "stub"}`),
starts a 50/50 experiment named `greet-tone-test`, and resolves + tracks
outcomes for 20 fake users (`scripts/seed_demo.py`). Meant to run once
against an empty `data/` directory — see the script's docstring for why a
second run against the same directory will fail partway through.

The CLI also works standalone, no server needed:

```
uv run python -m promptreg.registry resolve --name support --user u1
uv run python -m promptreg.outcomes summary --experiment 1
```

`promptreg.registry`'s CLI has only the `resolve` subcommand;
`promptreg.outcomes`'s CLI has only `summary`. There is no CLI subcommand
for publish, pointer, rollback, or experiment management — those go
through the HTTP API, the Streamlit UI, or the Python classes directly.

## Configuration

**Environment variables** (all optional; every default below is what the
code falls back to when unset — verified by reading each `os.environ.get`
call, there is no `.env.example` in this repo):

| Variable | Default | Read by |
|---|---|---|
| `PROMPTREG_DB_PATH` | `data/registry.db` | api, ui, both CLIs, seed script |
| `PROMPTREG_PROMPTS_DIR` | `data/prompts` | api, ui, registry CLI, seed script |
| `PROMPTREG_OUTCOMES_JSONL` | `data/outcomes.jsonl` | api, ui, both CLIs, seed script |
| `PROMPTREG_ADMIN_TOKEN` | none — generated + printed at startup | api only |
| `PROMPTREG_API_PORT` | `8000` | api only |

**Config files:**

- `.streamlit/config.toml` — `[server] port` (`7016`) and `[theme] base`
  (`"dark"`) for the Streamlit UI. Not passed as CLI flags.
- `pyproject.toml` — `[tool.ruff]`/`[tool.ruff.lint]` (lint rules, 100-char
  lines, per-file ignores for `tests/`, `scripts/`, `**/__main__.py`) and
  `[tool.ty.environment]` (type-checker Python version).

No secrets management beyond the admin token above — nothing else in this
codebase reads a credential or API key.

## Repo map

```
src/promptreg/
  registry/   Prompt + immutable Version + env Pointer, SQLite-backed. CLI: resolve.
  split/      Experiment + Assignment, weighted/sticky resolve().
  execute/    Optional LLM call (dry unless a completer is registered) + str.format_map template render.
  outcomes/   Outcome events: SQLite + append-only JSONL, per-arm summary. CLI: summary.
  api/        FastAPI app (src/promptreg/api/app.py) + request/response schemas.
  ui/         Streamlit admin UI (single-file app, src/promptreg/ui/app.py).
scripts/
  seed_demo.py   Publishes demo data, starts an experiment, records fake outcomes.
tests/           One test file per module above, plus test_api.py for the HTTP layer.
docs/            ARCHITECTURE.md, TECHNICAL.md, DATA.md, SPLIT.md, RUNBOOK.md.
data/            Runtime state: registry.db, prompts/<name>/<version>.md, outcomes.jsonl.
                 Only data/prompts/.gitkeep is tracked; everything else is gitignored.
.streamlit/config.toml   Streamlit port + theme.
run.cmd                  venv + pip setup, then starts the API and the UI.
```

## Tests

```
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run ty check src/
```

No CI is configured in this repo (no `.github/workflows` or equivalent) —
these are run manually.

## Known limitations

These are visible directly in the code, not aspirational:

- **No real model provider is wired up.** `src/promptreg/execute/completer.py`
  keeps an empty `COMPLETERS` registry by default; `execute()` always
  returns a dry result (body + config only, no model call) unless
  something registers a completer for a given `config.provider` at
  runtime. Nothing in this repo does that registration today.
- **Single SQLite file, single machine.** `Registry`/`ExperimentStore`/
  `OutcomeStore` all point at one `PROMPTREG_DB_PATH`. Multiple
  `promptreg.api` processes can point at the same file (SQLite handles
  that), but each mints its own independent admin token and there is no
  shared cache or lock beyond what SQLite itself provides.
- **No logging module.** Nothing in `src/` imports `logging`. Diagnostics
  are `print()` (CLI output, the admin-token line at API startup) and
  whatever `uvicorn`/`streamlit` write to the console themselves — there
  is no log file.
- **Admin auth is a single header equality check.** `require_admin_token`
  in `src/promptreg/api/app.py` compares `X-Admin-Token` with `!=`; there
  is no rate limiting, no per-route scoping beyond the open/gated split
  documented in `docs/ARCHITECTURE.md`, and no token rotation.
- **The sticky-assignment hash is not a security mechanism.** See "State"
  in `docs/ARCHITECTURE.md`.
- **No CI, no LICENSE file, no `.env.example`, no commits yet.** This is a
  local, single-branch (`master`) git repository with no remote configured
  and no commit history at time of writing. `CONTRIBUTING.md` is
  deliberately not included — there is no CI or branch policy in this
  repo to document one against.

## More detail

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — request/data flow, module
map, HTTP routes, state and lifetime. [docs/TECHNICAL.md](docs/TECHNICAL.md)
— stack choices, invariants, error handling, persistence paths.
[docs/DATA.md](docs/DATA.md) — field-level schema for every table.
[docs/SPLIT.md](docs/SPLIT.md) — the sticky-assignment hash in detail.
[docs/RUNBOOK.md](docs/RUNBOOK.md) — start/stop, rollback steps,
troubleshooting by error string.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
