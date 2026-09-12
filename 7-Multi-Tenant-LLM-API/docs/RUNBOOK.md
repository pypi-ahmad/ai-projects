# Runbook

## Start

Windows:
```
run.cmd
```
Runs `uv sync --quiet`, loads `.env` into the environment if that file
exists, then starts two processes, each in its own console window (via
`start "name" ...`): the API on `127.0.0.1:8000` and the Streamlit admin
UI on `:7011`. Override with `set HOST=`, `set PORT=`,
`set ADMIN_UI_PORT=` before running.

Any OS:
```
uv run uvicorn src.api.app:app --host 127.0.0.1 --port 8000
uv run streamlit run src/ui/app.py --server.port 7011
```
These are the exact commands `run.cmd` runs; run them in two terminals.

`ADMIN_TOKEN` must be set in the environment before starting, or every
`/admin/...` request returns `{"error": "invalid_admin_token"}` regardless
of what token is sent (`src/auth/admin.py::verify_admin` rejects when the
configured token is empty, not just when it mismatches).

## Stop

No stop script exists in this repository. `run.cmd` starts both processes
detached (Windows `start`), so stopping means closing each console window,
or, from another terminal, finding and killing the two processes (for
example by the ports they hold, `8000` and `7011` by default). Running the
manual `uv run ...` commands directly in a terminal instead lets you stop
each with Ctrl+C.

## Logs

No log file. No module under `src/` imports Python's `logging`. Output is:
- `uvicorn`'s own request/startup log lines, to the console window it runs in.
- `streamlit`'s own log lines, to its console window.
- `print()` output from `src/tenants/seed_dev.py` and `src/quota/cli.py`
  when run directly, to whichever terminal ran them.

## Errors and what they mean

Every code below is a literal string from the source, not paraphrased.

| Response | Where raised | Meaning |
|---|---|---|
| `{"error": "missing_credentials"}`, 401 | `src/auth/resolve.py` | No `Authorization` or `X-Api-Key` header on a tenant route. |
| `{"error": "invalid_key"}`, 401 | `src/auth/resolve.py` | No active key's hash matched; covers both an unrecognized key and a wrong secret for a real prefix. |
| `{"error": "key_revoked"}`, 401 | `src/auth/resolve.py` | The key matched, but its `revoked_at` is set. |
| `{"error": "tenant_suspended"}`, 403 | `src/auth/resolve.py`, `src/quota/limiter.py` | The key is valid but the owning tenant's `status` is `suspended`. |
| `{"error": "invalid_admin_token"}`, 401 | `src/auth/admin.py` | `X-Admin-Token` missing, wrong, or `ADMIN_TOKEN` is unset/empty in the server's environment. |
| `{"error": "MODEL_NOT_ALLOWED"}`, 403 | `src/quota/limiter.py` | Requested (or default) model isn't in the tenant's `plan_limits.allowed_models`. |
| `{"error": "PROVIDER_NOT_ALLOWED"}`, 403 | `src/quota/limiter.py` | The model resolves to a provider not in `plan_limits.allowed_providers`; also the result when a model isn't in `src/providers/registry.py::MODEL_PROVIDERS` at all, since that resolves to no provider. |
| `{"error": "MAX_TOKENS_PER_REQUEST"}`, 400 | `src/quota/limiter.py` | Client's `max_tokens` exceeds `plan_limits.max_tokens_per_req`. Only checked if the client sent `max_tokens`. |
| `{"error": "RATE_RPM"}` / `"RATE_RPD"`, 429, with a `Retry-After` header | `src/quota/limiter.py` | Requests-per-minute or requests-per-day limit reached. |
| `{"error": "BUDGET_MONTH"}`, 429, with a `Retry-After` header | `src/quota/limiter.py` | Monthly token budget already used, plus this request's estimate, exceeds `token_budget_month`. |
| `{"error": "UPSTREAM_UNAVAILABLE"}`, 503 | `src/providers/*.py` | Missing platform API key for the resolved provider, or the provider (Ollama, most likely) is unreachable. Never a bare 500 for this case. |
| `{"detail": "tenant not found"}`, 404 | `src/api/admin_routes.py` | Admin route's `tenant_id` path segment doesn't match any tenant. Note the key is `detail`, not `error`; this is FastAPI's default `HTTPException` body, unlike every other error in this API. |
| `{"detail": "key not found for this tenant"}`, 404 | `src/api/admin_routes.py` | The revoke-key route's `key_id` either doesn't exist or belongs to a different tenant than the `tenant_id` in the path. |

Other failure not represented as a JSON error:

- `sqlalchemy.exc.OperationalError: no such table: ...`; happens if
  `data/app.db` predates a schema change in `src/db.py`. `init_db()`
  (`Base.metadata.create_all()`) only adds missing tables; it does not
  alter existing ones (see `docs/TECHNICAL.md` "Persistence"). Delete
  `data/app.db` and restart to recreate it from the current schema; this
  destroys all data in that file.
- A bind failure on startup (`uvicorn` exits with an address/socket
  error) means the configured `PORT` (default `8000`) or `ADMIN_UI_PORT`
  (default `7011`) is already in use or blocked by something else on the
  machine. Set `PORT=`/`ADMIN_UI_PORT=` to a different value and retry.
