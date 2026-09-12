# Technical reference

## Stack

- Python 3.11+ (`pyproject.toml` `requires-python = ">=3.11"`).
- `uv` for environment and dependency management — `run.cmd` calls `uv venv` / `uv sync`; `requirements.txt` pins the same versions for a `pip install -r requirements.txt` fallback.
- `pydantic>=2.0` for every typed model (`GatewayRequest`, `RouteDecision`, `GatewayResponse`, etc. in `src/gateway/models.py`) — validation happens once at construction, not scattered through call sites.
- `PyYAML` for `config/*.yaml`. There is no schema-validation layer; malformed YAML surfaces as a raw parser exception at load time (`load_tiers()`, `load_prices()`, `FeatureExtractor.__init__`).
- `tiktoken` (`cl100k_base` encoding) for deterministic token counting — used both for complexity scoring (`src/gateway/features.py`) and as the token-count fallback when a provider does not report usage (`src/route/executor.py::_approx`).
- `streamlit>=1.35` for the UI (`src/ui/app.py`) — the only third-party UI dependency; no separate frontend build step.
- Provider HTTP calls use `urllib.request` from the standard library, not `requests`/`httpx` — no extra HTTP dependency, but also no connection pooling and no automatic retry beyond the one manual 5xx retry each adapter implements.
- No ORM or database. The only persistence is one JSONL file per UTC day under `logs/usage/`.
- No lint/type-check tool is configured in `pyproject.toml` (no `ruff`, `mypy`, or `ty` section) — style enforcement is manual.

## Invariants

- **Promotion is one-directional.** `config/tiers.yaml` `fallbacks:` lists only point upward (lite→mid, mid→heavy, heavy→none). This is a configuration convention, not a code-enforced constraint — `route()` follows whatever `fallbacks:` says, so an edit that pointed a tier downward would not be rejected.
- **Hard routing rules live in code, not config** (`src/route/router.py::_skip_reason`): `complexity_label == "hard" and need_json` excludes lite targets; `flags.has_image` excludes any target with `vision_ok: false`. Both checks run per-target regardless of what `allowed_when` says in `tiers.yaml`.
- **Complexity scoring is deterministic and offline.** `FeatureExtractor.extract()` makes no network or LLM calls — the score is a fixed weighted sum of keyword hits, a token-count bucket, and three boolean flags (`src/gateway/features.py`). `config/features.yaml` documents that `feature_weights` should sum to 1.0, but nothing enforces this at load time.
- **Provider adapters must convert every failure to `ProviderError`** (or its subclass `MissingKeyError`). `src/route/executor.py`'s fallback loop only catches `ProviderError`; an adapter that let a different exception escape would crash the request instead of advancing the fallback chain. Each adapter (`ollama.py`, `openai_compat.py`, `gemini.py`) ends its retry loop with a blanket `except Exception as exc: raise ProviderError(str(exc))`.
- **One retry, 5xx only, within a single target.** Each adapter retries its own HTTP call once when the response is an `HTTPError` with `code >= 500` (`for attempt in range(2)` in each `complete()`). 4xx errors and non-HTTP exceptions are not retried. The executor's fallback loop is separate: it never retries a target, it moves to the next one in the chain.
- **A missing key or unreachable host is not an error.** `default_available()` (`src/providers/availability.py`) returns `False` rather than raising, so an unconfigured provider is silently excluded from candidate targets (`ReasonCode.SKIPPED_UNAVAILABLE`), never a crash.

## Error handling

- `RouteDecision.status` has three states: `"ok"`, `"unsupported"` (image request, no vision-capable target configured anywhere), `"unavailable"` (every target skipped — e.g. no API keys set and Ollama unreachable).
- `execute()` only calls providers when `decision.status == "ok"`; otherwise it returns `GatewayResponse(ok=False, error=f"routing: {decision.status}")` without touching the network.
- Inside `execute()`, a target counts as failed (and the loop advances to the next one) for: `ProviderError` from the adapter, an empty/whitespace-only response, or — when `need_json=True` — a response that fails `json.loads`. Every attempt, success or failure, is recorded in `GatewayResponse.attempts` as an `AttemptRecord`.
- If every target in the chain fails, `execute()` returns `GatewayResponse(ok=False, error="all targets exhausted")` with the full attempt history attached — nothing is raised to the caller.

## Persistence

- The only durable state is `logs/usage/YYYYMMDD.jsonl` (UTC day boundary), one JSON object per request, appended by `log_event()` (`src/cost/ledger.py`). The directory is created on first write; the files are gitignored (`logs/usage/*.jsonl` in `.gitignore`).
- Config (`config/tiers.yaml`, `config/prices.yaml`, `config/features.yaml`) is read from disk on every CLI invocation. The Streamlit app caches it once per process via `@st.cache_resource` (`src/ui/app.py::_load_configs`) — editing a config file has no effect until the Streamlit process is restarted.
- There is no database, no request history beyond the JSONL logs, and no state carried between requests — each `python -m src.gateway` invocation is a fresh process.
