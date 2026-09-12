# Tool-calling framework

A local framework for registering typed Python functions as "tools," letting
an LLM call them by name with JSON arguments, and running those calls through
a validating, permission-checked, timeout-bound sandbox. It includes a
provider layer for four LLM backends (Ollama, an OpenAI-compatible endpoint,
Agnes AI, Gemini), a FastAPI HTTP surface, and a Streamlit UI for browsing
tools, making manual calls, and chatting through the tool-calling loop.

## Requirements

- Python 3.13. `.python-version` at the repo root pins `3.13`; `run.cmd`
  requests the more specific `3.13.15` when creating the virtual environment.
  This session verified `3.13.15` running.
- [`uv`](https://docs.astral.sh/uv/) — every setup/run command in this repo
  (`run.cmd` included) uses `uv venv` / `uv pip install` / `uv run`. There is
  no documented plain-`pip` path, though `requirements.txt` is in standard
  pip-compatible format.
- Dependencies, pinned exactly in `requirements.txt`:
  `pydantic==2.13.5`, `pytest==9.1.1`, `requests==2.34.2`,
  `google-genai==2.23.0`, `fastapi==0.141.1`, `uvicorn==0.52.4`,
  `streamlit==1.63.0`.
- Windows. The only setup/run script in the repo, `run.cmd`, is a Windows
  batch file with no Unix equivalent checked in. The Python source under
  `src/tools/` has no OS-specific code that this review found, but only the
  Windows path has been exercised in this repo.

## Setup and run

Everything below was run against this repo to confirm it works as
documented.

```
run.cmd
```

From the repo root. Creates `.venv` with `uv venv --python 3.13.15 .venv` if
it doesn't exist, installs `requirements.txt` with `uv pip install`, then
opens two new console windows: one running the API
(`uv run --python .venv python -m uvicorn src.tools.api:app --host 127.0.0.1 --port 8765`)
and one running the Streamlit UI (`uv run --python .venv streamlit run src\tools\ui.py`).
Close those windows to stop them — `run.cmd` has no separate stop command.

Individual pieces, run directly (all from the repo root):

```
uv run --python .venv python -m src.tools.loop --text "What is 17*19? Write the result to a note." --provider ollama
```
Runs the tool-calling loop once from the command line, no API/UI needed.
`--provider` accepts `ollama` (default), `openai`, `agnes`, or `gemini`;
`--model` overrides the provider's default model; `--max-tool-iters`
defaults to 4.

```
uv run --python .venv python -m uvicorn src.tools.api:app --host 127.0.0.1 --port 8765
```
Starts only the API.

```
uv run --python .venv streamlit run src/tools/ui.py
```
Starts only the UI. It calls the API at `http://127.0.0.1:8765` (hardcoded
in `src/tools/ui.py`), so the API must already be running.

```
uv run --python .venv python scripts/seed_demo.py
```
Calls `calc` then `write_note` against the running API and prints the
result and the sandbox path of the note it wrote. Requires the API to be
running first (prints an error naming the unreachable URL and exits 1 if
not).

## Configuration

No `.env` file or `.env.example` exists in this repo. Configuration is read
directly from process environment variables and one TOML file; there is no
`.env`-loading code (no `python-dotenv` or similar in `requirements.txt`).

Environment variables read by `src/tools/providers.py`:

| Variable | Read by | Required for |
|---|---|---|
| `OLLAMA_HOST` | `OllamaProvider` | Optional — defaults to `http://localhost:11434` if unset |
| `OPENAI_BASE_URL` | `OpenAICompatibleProvider` | Required to use `--provider openai` |
| `OPENAI_API_KEY` | `OpenAICompatibleProvider` | Required to use `--provider openai` |
| `AGNESAI_API_KEY` | `AgnesProvider` | Required to use `--provider agnes` |
| `GOOGLE_API_KEY` | `GeminiProvider` | Required to use `--provider gemini` |

A missing required variable raises `RuntimeError("missing environment
variable: <name>")` when that provider is constructed (`_require_env` in
`providers.py`). `ollama` is the default provider and only needs
`OLLAMA_HOST`, which itself is optional.

Config files:

- `.streamlit/config.toml` — Streamlit `[server]` (`port = 7018`) and
  `[theme]` (a fixed dark theme; no light variant is defined, so the app
  cannot be switched to light mode from the UI).
- `pytest.ini` — `pythonpath = src`, `testpaths = tests`.

## Repo map

```
src/tools/       Python package (import name: tools, via pytest's pythonpath=src)
  schema.py      ToolSpec, ToolPermissions, ToolArgs (pydantic base with extra="forbid")
  registry.py    Registry: register/get/list/list_schemas
  builtins.py    Five built-in tools: calc, now, json_query, write_note, read_note
  parse.py       Model-output parsing, ToolCall/ToolError/ToolResult/ParseFail types
  sandbox.py     Permission check, timeout, execute/execute_with_retry, path jail
  loop.py        Tool-calling loop (run()), JSONL logging, CLI entry point
  providers.py   Four LLM provider adapters + get_provider() factory
  api.py         FastAPI app: GET /v1/tools, POST /v1/call, POST /v1/loop
  ui.py          Streamlit app
tests/           pytest, one file per src module roughly (6 files, 21 tests)
scripts/
  seed_demo.py   calc + write_note demo script against the running API
docs/            ARCHITECTURE.md, SCHEMA.md, PERMISSIONS.md, THREAT_NOTES.md, TECHNICAL.md, RUNBOOK.md
data/
  sandbox/       Per-run tool file-write jail: data/sandbox/<run_id>/ (gitignored)
  logs/          runs.jsonl, one JSON object per loop iteration (gitignored)
.streamlit/      config.toml (port, theme)
requirements.txt, pytest.ini, .python-version, run.cmd
```

## Running tests

```
uv run --python .venv pytest
```

21 tests across 6 files in `tests/`, all currently passing. None of them
make a real network call to any LLM provider — `tests/test_loop.py` and
`tests/test_api.py` use an in-process fake provider, and `tests/test_api.py`
exercises the FastAPI app via `fastapi.testclient.TestClient` rather than a
bound socket. `tests/test_executor.py` includes a live timeout test (a
tool that sleeps past its declared `timeout_s`).

## Known limitations

These are stated directly in code or comments, not inferred:

- **Not a secure multi-tenant sandbox.** `docs/THREAT_NOTES.md` (Security
  posture) and `src/tools/api.py`'s own docstring state this: the API binds
  to `127.0.0.1` but has no authentication, so any local process can call
  any tool. Sandboxing here is aimed at model mistakes, not a hostile
  caller.
- **`fs_read` has no path jail of its own.** Only `write_note`/`read_note`
  are safe, because they happen to reuse the same `sandbox_path` guard as
  `fs_write`; a hypothetical `fs_read`-only tool that didn't call it would
  not be confined (`docs/PERMISSIONS.md`).
- **A timed-out tool call keeps running.** `src/tools/sandbox.py`'s module
  docstring: the timeout is thread-based (`ThreadPoolExecutor`) because
  Windows has no `SIGALRM`; Python has no safe way to kill a running
  thread, so `execute()` stops waiting but the call's thread keeps
  executing until it finishes on its own or the process exits.
- **JSON-in-prompt tool-call detection is a heuristic.** For `AgnesProvider`
  (no native tool-calling signal), `docs/THREAT_NOTES.md` notes that a
  plain-text answer that happens to look like `{"tool": ..., "args": ...}`
  will be misread as a tool-call attempt.
- **Two provider adapters are unverified against a live endpoint.** Per
  `src/tools/providers.py`'s own docstring: `OpenAICompatibleProvider` is
  "assumed supported" for tool-calling based on the "OpenAI-compatible"
  label, not confirmed against that specific deployment; `_to_gemini_contents`
  (Gemini) is explicitly marked "unverified against a live Gemini call."
- **The run log has no rotation.** `data/logs/runs.jsonl` is appended to on
  every loop iteration by `src/tools/loop.py`; nothing in the code trims,
  rotates, or caps it.
- **No `.env.example`.** Nothing in the repo documents the four provider
  environment variables in a copyable template file; see Configuration
  above for the full list.

`docs/CONTRIBUTING.md` was not written: this working directory is not a git
repository (`git status` fails with "not a git repository"), there is no CI
configuration (`.github/` does not exist), and no branch or PR conventions
are documented anywhere in the tree.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
