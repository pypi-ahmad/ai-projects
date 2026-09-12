# Guardrails middleware

A Python library and local HTTP service that filters text going into and coming out of an LLM
call: PII redaction, prompt-injection pattern matching, and an optional local-model classifier.
It does not call an LLM provider itself; callers wrap their own provider call with it.

## Requirements

Taken from `pyproject.toml` and `.python-version`:

- Python `>=3.13` (`.python-version` pins the dev environment to `3.13`)
- [`uv`](https://docs.astral.sh/uv/) as the package/environment manager; the repo has no
  `requirements.txt`-based `pip install` workflow as its source of truth (see below)
- Windows: `run.cmd` is a `.cmd` batch file, so the one-command setup is Windows-only. The
  underlying `uv`/`pytest`/`uvicorn`/`streamlit` commands themselves are cross-platform; nothing
  in the source imports a Windows-only module. Not verified on macOS/Linux.

Main dependencies (`pyproject.toml`): `fastapi>=0.141.1`, `pydantic>=2.13.5`, `pyyaml>=6.0.3`,
`streamlit>=1.63.0`, `uvicorn[standard]>=0.52.4`. Dev-only: `ruff`, `ty`, `pytest`, `httpx2`
(`[dependency-groups]`).

## Setup and run

```powershell
uv sync --group dev
```

Installs the project and its dev tools into `.venv` (created by `uv` if missing).

Run the HTTP API (binds `127.0.0.1` only):

```powershell
uv run uvicorn guardrails.api:app --host 127.0.0.1 --port 8000
```

Run the Streamlit UI (port and dark theme come from `.streamlit/config.toml`, not a flag):

```powershell
uv run streamlit run src/guardrails/ui.py
```

Or start both at once, each in its own window:

```powershell
run.cmd
```

`run.cmd`'s contents, verbatim: `uv sync --group dev`, then `uv run uvicorn guardrails.api:app
--host 127.0.0.1 --port 8000` and `uv run streamlit run src/guardrails/ui.py`, each via `start`.

## Configuration

### Environment variables

Confirmed by `grep`ing `os.getenv` in `src/guardrails/`:

| Variable | Read by | Effect |
|---|---|---|
| `GUARDRAILS_PII_CONFIG` | `pii.py` (`load_pii_config`) | overrides the path to the PII config YAML |
| `GUARDRAILS_RULES_CONFIG` | `rules.py` (`load_rules_config`) | overrides the path to the rules config YAML |
| `GUARDRAILS_CLASSIFIER_CONFIG` | `providers.py` (`load_classifier_config`) | overrides the path to the classifier config YAML |
| `GUARDRAILS_LOG_FINDINGS` | `api.py` | `1`/`true`/`yes` (case-insensitive) enables the JSONL findings log; anything else (including unset) leaves it off |

`.env.example` (present in the repo, not readable by this documentation pass due to local
permission settings on `.env*` files; content not independently re-verified here) also lists
`GUARDRAILS_FAIL_MODE`. **That variable is not read by any code in `src/guardrails/`**; `grep`
for it finds no `os.getenv` call. `Guard`'s `fail_mode` is a constructor argument only
(`guardrails/pipeline.py`, default `"closed"`). This looks like a leftover from an earlier
version of the pipeline; treat `.env.example`'s claim about it as unverified/stale.

### Config files

| File | Consumed by | Purpose |
|---|---|---|
| `config/pii.yaml` | `pii.load_pii_config` | per-PII-type on/off switches |
| `config/rules.yaml` | `rules.load_rules_config` | per-category enabled/severity for input/output rule checks |
| `config/classifier.yaml` | `providers.load_classifier_config` | optional LLM-classifier and embedding-lane settings, both off by default |
| `config/blocklists/*.txt` | `rules.py` (`_load_blocklists`) | phrase/regex lists: `injection.txt`, `role_play.txt` (input), `leak_phrases.txt`, `denied_topics.txt` (output, empty by default) |
| `.streamlit/config.toml` | Streamlit itself | `server.port = 7014`, `theme.base = "dark"` |

None of these three `load_*_config` functions read their file automatically; a caller must
call them and pass the result into `detect()`/the relevant `Detector` explicitly (see
`docs/PII.md`, `docs/DETECTORS.md`). `src/guardrails/api.py` and `src/guardrails/ui.py` both
construct detectors with **no** config argument, so they run on the in-code defaults
(`DEFAULT_PII_CONFIG`, `DEFAULT_RULES_CONFIG`, `DEFAULT_CLASSIFIER_CONFIG`), not on whatever is
in the YAML files, unless something explicitly loads and passes it; as of this reading, neither
`api.py` nor `ui.py` does.

## Repo map

```
src/guardrails/    the package: pipeline, detectors, providers, api, ui (see docs/ARCHITECTURE.md)
tests/             pytest suite, one file per source module + tests/fixtures/
config/            YAML configs and blocklist text files consumed by the package
docs/              this documentation set, plus API.md/DETECTORS.md/PII.md/POLICIES.md/
                   THREAT_NOTES.md/PHASES.md and per-phase build notes
.streamlit/        Streamlit server config (port, theme)
run.cmd            Windows launcher: sync deps, start API + UI
requirements.txt   pinned `uv export` output (not the source of truth; regenerate, don't hand-edit)
```

## Running tests

```powershell
uv run pytest
```

`pyproject.toml`'s `[tool.pytest.ini_options]` sets `testpaths = ["tests"]`. As of this writing,
`uv run pytest` reports 88 passed. Lint and type checks (also configured in `pyproject.toml`,
also dev-group tools, not "tests" in the pytest sense but part of the same verified workflow):

```powershell
uv run ruff check .
uv run ruff format --check .
uv run ty check src/
```

## Known limitations

Visible directly in code/comments:

- `src/guardrails/policies.py`'s own docstring: "Stub for now... Wiring an actual `Policy` into
  `GuardrailsPipeline` ... is future-phase work." The `strict`/`observe` policy names exist as a
  `Literal` type but are not read by `pii.py`, `rules.py`, or `providers.py` to change behavior ;
  each module's severity/threshold comes from its own YAML config, independent of the active
  `Policy` value. (The docstring also refers to a `GuardrailsPipeline` class that does not exist
  in the current `pipeline.py`; `Guard`/`Pipeline` are the current names.)
- `src/guardrails/detectors.py` is only imported by `tests/test_detectors.py`; it is not
  imported by `api.py`, `ui.py`, `pipeline.py`, or `__init__.py`, and is not part of the
  package's public API (`__all__` in `guardrails/__init__.py`). It exists and is tested, but the
  running application does not use it.
- Detection is regex/heuristic/small-local-model based throughout (`pii.py`, `rules.py`,
  `providers.py`). Expect false positives and false negatives; see `docs/PII.md`'s
  "Known false-positive risks" and `docs/THREAT_NOTES.md`. **This is not a compliance
  certification** (GDPR, HIPAA, PCI-DSS, or otherwise); it is a best-effort filtering layer.
- The FastAPI app has no authentication and is documented (in its own docstring) as
  `127.0.0.1`-only; it is not hardened for exposure beyond localhost.
- `.streamlit/config.toml` sets `server.port` and `theme.base` only; it does not set
  `server.address`. Unlike the FastAPI app, nothing in this repo restricts the Streamlit UI to
  localhost. Observed directly while verifying this repo: running the UI without an explicit
  address printed both a "Network URL" and an "External URL" with real, non-localhost
  interface addresses, meaning by default it listens beyond `127.0.0.1`. The UI has no
  authentication either.
- Not a git repository as checked out (no `.git` directory found); there is no branch history,
  commit log, or CI to cross-reference for this documentation pass.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
