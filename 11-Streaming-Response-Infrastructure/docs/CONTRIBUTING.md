# Contributing

This repo has an active test suite and a running development log
(`PHASES.md`), so it is meant to be developed in — but there is no CI
configuration (no `.github/workflows`), no `Makefile`, no pre-commit config,
and (as of this tree) no commit history yet (`git log` on `master` reports
no commits). The expectations below are only what the repo itself
establishes; anything else is unknown.

## Environment

```
uv sync --all-groups
```

Installs both the main dependency group and `dev` (`pytest`,
`pytest-asyncio`, declared in `pyproject.toml`). No other setup step is
documented in the repo.

## Before proposing a change

```
uv run pytest -q
```

Run the full suite (39 tests as of this tree). Nothing in the repo enforces
this automatically — there is no CI to run it for you.

## Conventions observed in the existing code (not enforced by tooling)

- `src/` layout, package name `stream` (`pyproject.toml`).
- Provider adapters live in `src/stream/providers/`, one file per backend,
  each exposing an async iterator of plain `str` chunks and a `.usage`
  attribute populated only from the provider's own data — see
  `docs/ARCHITECTURE.md` and the adapter modules themselves for the exact
  shape.
- Tests are offline: adapter tests use `httpx2.MockTransport`
  (`tests/test_provider_adapters.py`); nothing in the suite requires a
  live Ollama instance, a GPU, or a real API key.
- No linter or formatter config (no `ruff`, `black`, or similar) appears in
  `pyproject.toml` or the repo root.

## Not established anywhere in this repo

- Branching model, commit message convention, or PR process — unknown.
- Code owners — unknown.
- Release/versioning process — `pyproject.toml` has `version = "0.1.0"`
  and nothing else references or bumps it.
