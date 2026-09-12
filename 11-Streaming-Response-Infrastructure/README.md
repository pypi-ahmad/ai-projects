# stream

A FastAPI service that streams LLM chat responses over Server-Sent Events,
with backpressure between the model call and the client, resumable
reconnects via `Last-Event-ID`, and time-to-first-token measurement. It
wraps four provider backends (a local Ollama install, a generic
OpenAI-compatible endpoint, Agnes AI, and Gemini) behind one contract, plus
a Streamlit consumer, a static HTML `EventSource` demo, and a CLI TTFT
benchmark.

## Requirements

- Python 3.13 (`.python-version` pins `3.13`; `pyproject.toml` requires
  `>=3.13`).
- [uv](https://docs.astral.sh/uv/); every documented command in this repo
  is a `uv` command. `pyproject.toml`'s `[build-system]` requires
  `uv_build>=0.12.13,<0.13.0`. No pip/venv-based setup is documented or
  verified in this repo, even though a pinned `requirements.txt` is
  provided (see below).
- Native Windows: `run.cmd` is a Windows batch file and is the only launch
  script in the repo. The underlying commands it runs (`uv sync`, `uv run
  uvicorn ...`) are themselves OS-agnostic, but there is no `.sh`
  equivalent; running this on Linux/macOS means invoking those `uv`
  commands directly, unverified here.
- Optional, only if you use the Ollama provider: a running Ollama server.
  The code's default target is `http://127.0.0.1:11434`
  (`stream/providers/ollama.py`); no other Ollama setup is documented here.

## Setup and run

```
uv sync --all-groups
run.cmd
```

`run.cmd` runs `uv sync --all-groups` again, then starts the API with
`uv run uvicorn stream.api:app --host 127.0.0.1 --port 8000`. It also
prints, but does not launch, two more entry points:

```
uv run streamlit run src/stream/ui.py
```

(the Streamlit consumer; port and theme come from `.streamlit/config.toml`,
verified to default to `7015`/dark with no CLI flags; see docs/RUNBOOK.md)
and the static demo at `http://127.0.0.1:8000/client.html`, served by the
FastAPI app itself once it's running.

```
uv run python -m stream.bench --provider fake --n 20
uv run python -m stream.bench --provider ollama --model qwen3.5:0.8b
```

is the CLI TTFT benchmark (`src/stream/bench.py`); `--provider fake` needs
no network.

Full endpoint contract: [docs/API.md](docs/API.md).

## Configuration

No `.env` or `.env.example` file exists in this repo. Configuration is
read directly from process environment variables, referenced by name in
`src/stream/config.py`:

| Variable | Used for | Required for |
|---|---|---|
| `OPENAI_API_KEY` | Bearer auth | the `openai_compatible` provider |
| `OPENAI_BASE_URL` | base URL | the `openai_compatible` provider |
| `AGNESAI_API_KEY` | Bearer auth | the `agnes` provider (fixed base URL `https://apihub.agnes-ai.com/v1`, hardcoded in `config.py`) |
| `GOOGLE_API_KEY` | `?key=` query param | the `gemini` provider |

The `ollama` provider needs no key (local, default
`http://127.0.0.1:11434`). A variable's presence is checked live at
`POST /v1/stream/start` request time (`os.environ`, `src/stream/api.py`) ;
it is not read from a `.env` file or any config file, since none exists.

`.streamlit/config.toml` sets Streamlit's `server.port` (`7015`) and
`theme.base` (`dark`); the only non-code configuration file in the repo.

## Repo map

```
src/stream/            FastAPI app, session/SSE core, provider adapters, CLI
  api.py                 the FastAPI app: routes, session registry, jsonl logging
  session.py              StreamSession, Event, backpressure pump
  sse.py                  SSE wire-format encoding
  config.py               provider allowlist, env var names, verification state
  bench.py                TTFT benchmark CLI (python -m stream.bench)
  ui.py                   Streamlit consumer
  providers/              one adapter module per backend, plus base.py/fake.py
src/ui/client.html      static browser EventSource demo, served at /client.html
tests/                  pytest suite (see below)
docs/                   API.md, ARCHITECTURE.md, METRICS.md, RUNBOOK.md, SSE.md,
                         TECHNICAL.md, CONTRIBUTING.md
.streamlit/config.toml  Streamlit port + theme
PHASES.md               a running build log of this project, phase by phase
requirements.txt        pinned export of the main dependency set (uv export)
run.cmd                 sync + start the API; prints the other two entry points
```

## Tests

```
uv run pytest -q
```

39 tests across 8 files in `tests/` (`test_api.py`, `test_backpressure.py`,
`test_bench.py`, `test_fake_adapter.py`, `test_provider_adapters.py`,
`test_session.py`, `test_sse.py`, `test_start_and_metrics.py`). All run
offline; provider adapter tests use `httpx2.MockTransport`, none require a
live Ollama instance, a GPU, or any real API key. `pytest-asyncio` is
configured in `pyproject.toml` (`asyncio_mode = "auto"`); no other pytest
plugins or markers are configured.

## Known limitations

Stated directly in code and comments, not inferred:

- **In-memory, single-process state.** `stream.api._sessions` and every
  session's replay buffer live in one process's RAM (`src/stream/api.py`,
  `src/stream/session.py`). Restarting the process loses every session,
  including anything a client could otherwise resume via `Last-Event-ID`.
  Running more than one worker process would split sessions across
  processes that don't share this state.
- **No session-registry reaping.** A finished session stays in
  `_sessions` until the process restarts; only its *events* are bounded
  (`max_events=256`, `ttl_s=300` in `StreamSession.__init__`), not the
  session entry itself.
- **A reconnect gap is not reported as an error.** If a `Last-Event-ID`
  reconnect asks for events older than what's still buffered, `stream.api`
  silently replays whatever is left rather than signaling the gap
  (`src/stream/session.py`'s `replay()` docstring: "Evicted ids are just
  absent").
- **Gemini is built but not verified.** `stream.config.PROVIDERS["gemini"]
  .enabled` is `False`; the stated reason in that file is that this
  environment's `GOOGLE_API_KEY` was rejected by the API
  (`400 API_KEY_INVALID`), so streaming was never confirmed end to end.
- **Token counts are not LLM token counts.** `tokens` in `logs/streams.jsonl`
  and `GET /v1/metrics` is a count of `token` SSE events emitted, i.e.
  provider chunk count; documented as such in `docs/METRICS.md` and in
  `StreamSession`'s own code.
- **`requirements.txt` is a generated artifact, not the source of truth.**
  It's produced by `uv export --no-hashes --no-dev`; dependency changes
  should go through `pyproject.toml`/`uv`, and this file can go stale if
  it isn't regenerated after such a change (nothing in the repo automates
  that regeneration).

See [docs/TECHNICAL.md](docs/TECHNICAL.md) for invariants and error
handling, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the request
flow.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
