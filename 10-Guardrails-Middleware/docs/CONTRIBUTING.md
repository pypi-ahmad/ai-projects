# Contributing

This repo has a dev dependency group, a test suite, and lint/type-check configuration, so it is
included here; but there is no CI configuration (no `.github/` directory) and, as checked out,
no `.git` directory either. There is nothing in the tree to document for branching, commit
conventions, or a PR process; don't infer one.

## Dev setup

```powershell
uv sync --group dev
```

## Before proposing a change

Run the same checks configured in `pyproject.toml`:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src/
```

`[tool.ruff.lint] select = ["ALL"]` with an explicit `ignore` list, plus per-file overrides for
`tests/**` and `src/guardrails/rules.py` (see `pyproject.toml`); `ruff check .` enforces the
same rule set a change will be judged against.

## Scope notes visible in the code

- `src/guardrails/detectors.py` is not imported anywhere outside its own test file
  (`tests/test_detectors.py`). If you're extending injection detection, check whether that
  belongs in `detectors.py` or in `rules.py`'s blocklist files; both exist and overlap; nothing
  in the repo resolves that overlap (see `docs/PHASES.md`).
- `src/guardrails/policies.py`'s `Policy` names (`strict`/`standard`/`observe`) are not wired
  into `pii.py`/`rules.py`/`providers.py`'s severity decisions. A change that assumes selecting a
  `Policy` changes detector behavior beyond `Pipeline`'s own block-gating would be adding new
  behavior, not fixing a bug.
