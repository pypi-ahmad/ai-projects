# LLM observability stack

Records traces (prompts, tokens, latency, cost) for LLM calls and evaluates
anomaly-detection rules against them. Storage is SQLite plus daily JSONL
files on the local filesystem; a FastAPI service exposes reads/writes over
HTTP, and a Streamlit app is a thin HTTP client of that service. It is a
single-process, single-machine tool; not a distributed metrics warehouse.
It does not call any LLM provider itself, except for one optional demo path
that calls a local Ollama server.

This repository is not a git repository (no `.git/`, no CI configuration,
no `Dockerfile`).

## Requirements

- Python `>=3.13` (`pyproject.toml`); this environment has `3.14.7` pinned
  in `.python-version`.
- [`uv`](https://docs.astral.sh/uv/) for dependency management; the project
  is built with `uv_build` (`pyproject.toml`).
- `run.cmd` is a Windows batch script (uses `start`, `cmd /k`). The
  underlying Python commands it runs (`uv run python -m obs.api`,
  `uv run streamlit run ...`) have no Windows-specific code that this
  inventory found and should work on other OSes when run directly; only the
  launcher script itself is Windows-only.
- Optional: a local [Ollama](https://ollama.com) server on
  `http://localhost:11434` for the demo-completion path
  (`src/obs/providers/ollama.py`).

## Setup

```
uv sync --all-groups
```

## Running

```
run.cmd
```

Reads `run.cmd` verbatim: runs `uv sync --all-groups`, then opens two
separate console windows; one running `uv run python -m obs.api` (FastAPI,
binds `127.0.0.1:8000`), one running
`uv run streamlit run src\obs\ui\app.py --server.port 7017` (binds
`127.0.0.1:7017`). Closing a window stops that service; there is no
supervisor restarting either one.

To run the two services directly instead of via `run.cmd`:

```
uv run python -m obs.api --host 127.0.0.1 --port 8000
uv run streamlit run src/obs/ui/app.py --server.port 7017
```

Optional, before or after starting the services; seed 30 synthetic traces
so the UI/API have something to show:

```
uv run python scripts/seed_demo_data.py
```

Other entry points that exist in the tree:

```
uv run python -m obs.export --day today --summary
uv run python -m obs.alerts.eval --once
```

## Configuration

Environment variables actually read by the code (found via `os.environ`
usage in `src/`; none are read in `scripts/`):

| Variable | Read in | Effect |
|---|---|---|
| `OBS_ADMIN_TOKEN` | `src/obs/api/auth.py`, `src/obs/ui/api_client.py` | If set, POST endpoints require a matching `X-Admin-Token` header. If unset, POST endpoints are open. |
| `OBS_STORE_PROMPTS` | `src/obs/trace/tracer.py`, `src/obs/ui/app.py` | If set to `true` (case-insensitive), full prompt text is stored in a span's `attrs["full_prompt"]`, in addition to the hash+preview that's always stored. Otherwise only the hash+preview is kept. |
| `OBS_API_BASE_URL` | `src/obs/ui/api_client.py` | Base URL the Streamlit UI uses to reach the API. Default `http://127.0.0.1:8000`. |

Config files read by the code:

- `config/alerts.yaml`; alert rule thresholds (`src/obs/alerts/config.py`).
  If missing, code falls back to built-in defaults.
- `config/prices.yaml`; per-model USD/1000-token rates
  (`src/obs/metrics/pricing.py`). If missing, every model is treated as
  unpriced.
- `.streamlit/config.toml`; currently just `[theme]\nbase = "dark"`.

Whether a `.env` or `.env.example` file exists in this repo is **unknown** ;
both names are blocked from being read or listed by this environment's own
permission rules, so this document cannot confirm or deny their presence or
contents.

## Repo map

```
src/obs/
  trace/       Tracer, Span/Trace/Usage/SpanContext models, redaction, exporter hooks
  export/      SQLite + JSONL writers, get_trace/query readers, python -m obs.export CLI
  metrics/     config/prices.yaml loader, cost estimation
  alerts/      rolling-window stats, rule checks, cooldown, python -m obs.alerts.eval CLI
  providers/   TracedClient + provider adapter protocol; only Ollama is implemented
  api/         FastAPI app (python -m obs.api)
  ui/          Streamlit app + its HTTP client of the API
config/        alerts.yaml, prices.yaml
scripts/       seed_demo_data.py
data/          obs.db (SQLite) and traces/YYYYMMDD.jsonl - created at runtime, gitignored
docs/          this repo's other documentation
tests/         pytest suite (see below)
obs_legacy/    an earlier, superseded package - not imported by src/obs or scripts/;
               only tests/test_redact.py and tests/test_storage.py still exercise it
```

## Tests

```
uv run pytest -q
```

39 tests pass as of this writing. Two of the eight test files
(`tests/test_redact.py`, `tests/test_storage.py`) import from `obs_legacy`,
not from `src/obs`; they test the superseded package, not the one the rest
of this repo runs. `uv run ruff check .`, `uv run ruff format --check .`,
and `uv run ty check .` are also used in this repo (see `pyproject.toml`
for the configured rule set).

## Ingesting a trace from another project

`POST /v1/ingest` accepts a prebuilt `Trace` JSON; the same shape
`src/obs/trace/models.py` produces locally (see `docs/SCHEMA.md`); so
another repo can ship traces here without importing this package. Verified
against the running API:

```bash
curl -X POST http://127.0.0.1:8000/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "trace_id": "ext-0001",
    "attrs": {"route": "/my-service/summarize"},
    "spans": [
      {
        "ctx": {"trace_id": "ext-0001", "span_id": "span-0001", "parent_id": null},
        "name": "generate",
        "kind": "client",
        "provider": "openai-compatible",
        "model": "some-model",
        "ts": "2026-01-01T12:00:00+00:00",
        "start_ns": 0,
        "end_ns": 850000000,
        "latency_ms": 850.0,
        "status": "ok",
        "usage": {"in_tokens": 120, "out_tokens": 64, "ttft_ms": 210.0},
        "attrs": {}
      }
    ]
  }'
```

`trace_id` must not already exist; ingesting a duplicate returns `409`.
Add `-H "X-Admin-Token: <value>"` if `OBS_ADMIN_TOKEN` is configured.

## Known limitations

Visible directly in the code/config, not aspirational:

- Only the Ollama provider adapter is implemented
  (`src/obs/providers/__init__.py` states this explicitly); an Agnes AI,
  an OpenAI-compatible, and a Gemini adapter are documented as intended but
  not built.
- The alert evaluator (`obs.alerts.eval`) is a single `--once` pass with no
  built-in scheduler/daemon; running it continuously means invoking it
  externally on a timer.
- Alerts can be acknowledged (`acked=true`) but not un-acknowledged - there
  is no reverse operation in `src/obs/alerts/store.py`.
- `config/prices.yaml` prices only the 8 local Ollama model names it lists;
  every other model name is reported `"UNPRICED"` rather than estimated.
- `obs_legacy/` is dead code from an earlier phase, kept only because two
  tests still import it; nothing else in the tree references it.
- No license file was found in this repo.

## Docs

- `docs/ARCHITECTURE.md`; data flow and module map
- `docs/TECHNICAL.md`; stack choices, invariants, error handling, persistence
- `docs/SCHEMA.md`; Trace/Span/Usage/Alert field reference
- `docs/ALERTS.md`; alert rules and cooldown behavior
- `docs/PRIVACY.md`; what's stored raw vs. hashed
- `docs/API.md`; FastAPI endpoint reference
- `docs/RUNBOOK.md`; starting/stopping the services, common failures

No `docs/CONTRIBUTING.md`: this repo has no `.git/`, no CI configuration,
and no existing branch/PR/test-gate conventions to document, so there is
nothing verifiable to write there.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
