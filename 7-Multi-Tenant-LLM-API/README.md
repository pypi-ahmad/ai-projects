# Multi-tenant LLM API

A gateway API that authenticates requests by per-tenant API key, enforces
per-tenant rate limits and a monthly token budget, forwards the request to
one of four upstream LLM providers (Ollama, Agnes AI, a generic
OpenAI-compatible endpoint, or Gemini), and records the resulting usage.
A separate Streamlit application provides an admin UI over the same admin
HTTP API (create/suspend tenants, issue/revoke keys, set limits, view
usage).

## Requirements

- Python >= 3.14 (`pyproject.toml`: `requires-python = ">=3.14"`; `uv.lock`
  resolves against the same constraint).
- [uv](https://docs.astral.sh/uv/) for dependency and environment
  management. The repository has no `requirements.txt`-based install path
  as the primary route — `requirements.txt` is a generated export (see
  Configuration below). No uv version is pinned anywhere in the repo.
- A local Ollama server if you want `/v1/chat` to actually reach a model —
  the code defaults to `http://127.0.0.1:11434` and does not start Ollama
  itself. Not required to run the API or its tests.

`uv.lock`'s resolution markers cover Windows and non-Windows platforms, so
the Python dependencies themselves are not Windows-specific. The provided
launcher, `run.cmd`, is a Windows `cmd.exe` batch script (it uses
`setlocal enabledelayedexpansion` and `start "name" ...`) and will not run
as-is on macOS/Linux. No equivalent Unix shell script exists in the repo;
see "Setup and run" below for the underlying commands `run.cmd` wraps,
which are plain `uv run ...` invocations and do work on any OS uv supports.

## Setup and run

Install dependencies (creates `.venv`, reads `uv.lock`):
```
uv sync
```

Start both processes at once (Windows only):
```
run.cmd
```
This runs `uv sync --quiet`, optionally loads a `.env` file if one is
present, then starts the API and the Streamlit admin UI as two separate
console windows via `start "api" ...` / `start "admin" ...`.

The same two processes, started directly (works on any OS with `uv`):
```
uv run uvicorn src.api.app:app --host 127.0.0.1 --port 8000
uv run streamlit run src/ui/app.py --server.port 7011
```
`src/api/app.py` and `src/ui/app.py` are the only two entrypoints in the
repository. There is no `src/api/main.py`.

Other scripts (Python modules run with `-m`, verified against
`if __name__ == "__main__"` blocks in each file):
```
uv run python -m src.tenants.seed_dev     # creates/reuses a tenant named "dev", prints a raw API key once
uv run python -m src.quota.cli <tenant_name>   # prints rpm/rpd/budget usage for one tenant
```

### Example: create a tenant and send a chat request

```
curl -X POST http://localhost:8000/admin/tenants ^
  -H "X-Admin-Token: %ADMIN_TOKEN%" ^
  -H "Content-Type: application/json" ^
  -d "{\"name\": \"acme-corp\"}"
```
Returns a JSON object with the new tenant's `id`.

```
curl -X POST http://localhost:8000/admin/tenants/<tenant_id>/keys ^
  -H "X-Admin-Token: %ADMIN_TOKEN%" ^
  -H "Content-Type: application/json" ^
  -d "{\"name\": \"first-key\"}"
```
Returns a JSON object containing `raw_key`. This is the only response that
ever contains the raw key; only its hash is stored.

```
curl -X POST http://localhost:8000/v1/chat ^
  -H "Authorization: Bearer <tenant_key>" ^
  -H "Content-Type: application/json" ^
  -d "{\"messages\": [{\"role\": \"user\", \"content\": \"hello\"}]}"
```
Returns a JSON object with `request_id`, `model`, `provider`, `message`,
and `usage`. Reaching a real provider (Ollama by default, for the tenant's
default model) requires that provider to actually be reachable; see
`docs/RUNBOOK.md` for the error returned when it is not.

## Configuration

Environment variables read directly by the code (grep-verified against
`os.environ.get(...)` call sites):

| Variable | Read by | Default if unset |
|---|---|---|
| `ADMIN_TOKEN` | `src/auth/admin.py` | none — admin routes reject every request |
| `OPENAI_API_KEY` | `src/providers/openai_compatible_provider.py` | none — that provider returns `UPSTREAM_UNAVAILABLE` |
| `OPENAI_BASE_URL` | `src/providers/openai_compatible_provider.py` | none |
| `GOOGLE_API_KEY` | `src/providers/gemini_provider.py` | none — returns `UPSTREAM_UNAVAILABLE` |
| `AGNES_API_KEY` (or `AGNESAI_API_KEY`) | `src/providers/agnes_provider.py` | none — returns `UPSTREAM_UNAVAILABLE` |
| `OLLAMA_HOST` | `src/providers/ollama_provider.py` | `http://127.0.0.1:11434` |
| `HOST`, `PORT`, `ADMIN_UI_PORT` | `run.cmd` only (not read by Python code) | `127.0.0.1`, `8000`, `7011` |

An `.env.example` file exists in the repository root as a template for
these variables; this session could not read its exact contents (blocked
by a local permission rule), so its content is not reproduced here — the
table above is derived from the code that actually consumes each variable,
which is the authoritative source regardless. `run.cmd` loads a `.env`
file into the environment if one is present, but does not require one —
variables already set in the environment work the same way. `.env` and
`data/app.db` are both listed in `.gitignore`.

Config files:
- `pyproject.toml` — project metadata, dependencies, and
  `[tool.pytest.ini_options]` (`pythonpath = ["."]`, `testpaths = ["tests"]`).
- `.streamlit/config.toml` — `[theme] base = "dark"` for the admin UI.
- `requirements.txt` — generated from `uv.lock` via
  `uv export --format requirements.txt --no-dev`; not hand-edited, and does
  not include the `pytest` dev dependency.

## Repo map

```
src/api/         FastAPI app (app.py), admin routes (admin_routes.py), dependency wiring (deps.py)
src/auth/        key hashing/verification, tenant-key resolution, admin-token check
src/tenants/     tenant/key admin operations (service.py), dev seed script (seed_dev.py)
src/quota/       rate-limit/budget enforcement (limiter.py), CLI (cli.py)
src/providers/   one adapter module per upstream (ollama, agnes, openai-compatible, gemini) plus a registry
src/usage/       usage-event recording and report building
src/ui/          Streamlit admin UI (single file, app.py)
src/db.py        SQLAlchemy schema (all tables) and engine/session setup
src/schemas.py   Pydantic request/response models
tests/           pytest suite (29 tests) and shared fixtures (conftest.py)
docs/            documentation (this repo's docs/ directory)
data/            SQLite database file at runtime (git-ignored; only .gitkeep is tracked)
.streamlit/      Streamlit configuration
```

## Running tests

```
uv run pytest
```
29 tests across 5 files, verified passing at the time of writing. Tests
use an in-memory SQLite database and a fake provider dispatcher
(`tests/conftest.py`) — no test calls a real Ollama/Agnes/OpenAI/Gemini
endpoint.

## Known limitations

Each item below is verifiable directly in the code, not inferred from
external context:

- **Not safe with more than one process.** `src/quota/limiter.py`'s module
  docstring and inline comments state that rate-limit and budget checks
  read then write SQLite with no cross-process lock; running multiple
  API processes lets a tenant briefly exceed its limits. `run.cmd` starts
  exactly one API process.
- **No streaming.** `POST /v1/chat` returns one JSON body
  (`ChatResponse` in `src/schemas.py`); there is no streaming/SSE response
  path anywhere in `src/api/app.py`.
- **No database migration tool.** `src/db.py::init_db` calls
  `Base.metadata.create_all()`, which only creates missing tables — it does
  not alter existing ones. A schema change requires deleting
  `data/app.db` in development (see `src/db.py`'s `init_db` docstring).
- **`prompt_logs` table is defined but never written.** `src/db.py`
  defines the `PromptLog` model and a `Tenant.store_prompts` flag, but no
  code anywhere constructs a `PromptLog` row — the table is unconditionally
  empty regardless of that flag's value.
- **No route to list all tenants or to reactivate a suspended one.**
  `src/api/admin_routes.py` defines exactly six routes: create tenant,
  create key, update limits, suspend, view usage, revoke key. There is no
  list-tenants route and no unsuspend route.
- **No application logging.** No module in `src/` imports Python's
  `logging`. Output is whatever `uvicorn` and `streamlit` write to the
  console they were started in, plus `print()` output from the two CLI
  scripts (`seed_dev.py`, `quota/cli.py`).
- **Two different error response shapes.** Most errors are
  `{"error": "<CODE>"}`, produced by the exception handlers in
  `src/api/app.py`. The 404s in `src/api/admin_routes.py` raise a plain
  FastAPI `HTTPException`, which renders as `{"detail": "..."}` instead.
- **No CI, no Dockerfile, no linter or type checker configured.** No
  `.github/` workflow files exist in this repository; no `Dockerfile` or
  `docker-compose` file exists; `pyproject.toml`'s `dev` dependency group
  contains only `pytest`.

## Documentation

| Doc | Covers |
|---|---|
| `docs/ARCHITECTURE.md` | Request flow, main types, external systems |
| `docs/TECHNICAL.md` | Stack choices, invariants, error handling, persistence |
| `docs/RUNBOOK.md` | Start/stop, error strings and what they mean, log locations |
| `docs/CONTRIBUTING.md` | How to run tests; what is and isn't established about workflow |
| `docs/API.md` | Full endpoint reference |
| `docs/TENANCY.md` | Isolation rules |
| `docs/LIMITS.md` | Rate limit / budget mechanics |
| `docs/THREAT_NOTES.md` | Security-relevant design decisions |

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
