# Contributing

This repository has a test suite and a `dev` dependency group
(`pyproject.toml`), so it is meant to be developed in. There is no CI
configuration (no `.github/` directory) and no branch or PR policy
documented anywhere in the repository — do not assume one; ask before
following a workflow this file doesn't state.

## Environment

```
uv sync
```
Installs the default dependency group plus `dev` (`pytest`). The project
uses `uv` exclusively — there is no evidence in the repo of a `pip`-based
install path being the primary one (`run.cmd`'s own comments say so
explicitly).

## Tests

```
uv run pytest
```
Configuration is in `pyproject.toml`'s `[tool.pytest.ini_options]`
(`pythonpath = ["."]`, `testpaths = ["tests"]`). 29 tests across
`tests/test_api.py`, `tests/test_auth.py`, `tests/test_isolation.py`,
`tests/test_quota.py`, `tests/test_tenancy_isolation.py`, all passing at
the time of writing. Shared fixtures and helpers are in `tests/conftest.py`
— an in-memory SQLite database per test and a fake provider dispatcher, so
no test reaches a real Ollama/Agnes/OpenAI/Gemini endpoint or the real
`data/app.db`.

There is no CI workflow that runs this automatically on push or PR; running
it is a manual step.

## Code style

No linter or type checker is configured in this repository —
`pyproject.toml`'s `dev` dependency group contains only `pytest`. There is
no `ruff`, `mypy`, `ty`, or similar tool listed as a dependency, and no
config section for one. Match the existing code's style (module-level
docstring explaining the non-obvious design choice, small single-purpose
functions, exceptions carrying a `code`/`http_status` pair per domain) by
reading nearby files rather than a written style guide, since none exists.

## What is not established

The repository does not state, anywhere: a branching model, commit message
convention, PR review requirement, versioning scheme, or release process.
Do not invent one when contributing — if a process decision is needed,
ask.
