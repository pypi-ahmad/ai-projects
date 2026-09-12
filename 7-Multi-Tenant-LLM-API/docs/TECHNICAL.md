# Technical notes

## Stack

| Piece | Library | Why (only stated where the code itself makes it explicit) |
|---|---|---|
| Web framework | FastAPI (`fastapi`) | Not explained in code comments; used for both the tenant and admin HTTP surface. |
| ASGI server | `uvicorn[standard]` | Started by `run.cmd` and documented directly in `src/api/app.py`'s module docstring: route handlers are plain `def`, not `async def`, because everything they call (SQLAlchemy's sync `Session`, the sync provider SDKs) is blocking, and Starlette runs sync path operations in a threadpool automatically so they don't block the event loop. |
| ORM / DB | SQLAlchemy 2.0, SQLite | `src/db.py`'s docstring states the six ORM models are kept in one module because they share foreign keys and are few enough that splitting them would only add indirection. SQLite specifically: one file, no server process, per `DB_PATH` in the same module. |
| Key hashing | `argon2-cffi` (Argon2id) | `src/auth/keys.py`'s module docstring: "Argon2id via argon2-cffi (OWASP-recommended, argon2-cffi's PasswordHasher default)". |
| Admin UI | Streamlit | `src/ui/app.py`'s docstring: "a thin HTTP client of this project's own admin API... It never touches the DB directly"; the stated reason is that this makes it structurally impossible for the UI to read anything a route doesn't already expose (in particular, prompt/response text, which no route exposes at all). |
| Dependency/env management | `uv` (`uv.lock`, `pyproject.toml`) | `run.cmd` comments state the project uses `uv`, not `pip`, throughout. |
| Provider SDKs | `ollama`, `openai`, `google-genai` | One per upstream; see `docs/ARCHITECTURE.md` "External systems". Agnes AI reuses the `openai` SDK because its endpoint is OpenAI-compatible (stated in `src/providers/agnes_provider.py`'s docstring), rather than because the code needs a second HTTP client library. |

## Invariants

These are stated directly in code (docstrings/comments), not inferred:

- **`tenant_id` is resolved from the authenticated key, never from request
  input.** `src/auth/context.py`'s docstring: handlers must read
  `tenant_id`/`key_id` from `RequestContext`, never from the request body.
  `src/auth/resolve.py::authenticate()` is the only function that produces
  a `RequestContext`, and it takes headers, not a tenant_id argument.
- **Admin auth and tenant-key auth are separate code paths with no
  overlap.** `src/auth/admin.py`'s docstring: "a valid tenant key must
  never satisfy admin auth, so there is no shared code path that could
  blur the two." `verify_admin()` only ever reads the `X-Admin-Token`
  header; `authenticate()` only ever reads `Authorization`/`X-Api-Key`.
- **Quota check order is fixed**, per `src/quota/limiter.py::check_quota`:
  tenant active -> model allowed -> provider allowed -> rpm -> rpd ->
  `max_tokens_per_req` (only if the client sent `max_tokens`) -> monthly
  token budget. The function raises on the first failing check.
- **rpm/rpd/budget are computed from `usage_events`, not a separate
  counter.** `src/quota/limiter.py`'s module docstring gives the reason:
  `usage_events` is already written after every completed call and already
  persists to SQLite, so a restart doesn't reset the day/month counters,
  with no extra state to keep in sync. A `# ponytail:` comment in the same
  file flags the tradeoff: a full scan of one tenant's `usage_events` on
  every check.
- **An over-budget response is still returned once it has started.**
  `src/quota/limiter.py`'s docstring: "if the actual token count from a
  completed call pushes the tenant over budget, that response is still
  returned in full... the *next* call's `check_quota` reads that updated
  sum and is the one that gets rejected." There is no truncation and no
  separate "over budget" flag; this behavior falls out of recording usage
  unconditionally after every call.
- **A request that is rejected by quota never reaches a provider and is
  never recorded.** `record_usage()` (`src/usage/service.py`) is only
  called from `src/api/app.py::chat`, after `check_quota` has already
  passed.

## Error handling

Three exception hierarchies, one per concern, each instance carrying a
`code: str` and `http_status: int`:

- `AuthError` and subclasses (`src/auth/errors.py`):
  `missing_credentials`, `invalid_key`, `key_revoked`, `tenant_suspended`,
  `invalid_admin_token`.
- `QuotaError` and subclasses (`src/quota/errors.py`):
  `MODEL_NOT_ALLOWED`, `PROVIDER_NOT_ALLOWED`, `MAX_TOKENS_PER_REQUEST`,
  and the `RateLimitError` subclasses `RATE_RPM`, `RATE_RPD`,
  `BUDGET_MONTH` (these three also carry a `retry_after: int`).
- `ProviderError` and its one subclass `UpstreamUnavailableError`
  (`src/providers/errors.py`); code `UPSTREAM_UNAVAILABLE`.

`src/api/app.py` registers one `@app.exception_handler` per base class
(`AuthError`, `QuotaError`, `ProviderError`), each returning
`JSONResponse({"error": exc.code}, status_code=exc.http_status)`; the
`QuotaError` handler additionally sets a `Retry-After` header when the
exception is a `RateLimitError`. `src/api/admin_routes.py`'s 404s do not
go through this system; they raise FastAPI's own `HTTPException`
directly, which produces `{"detail": "..."}` instead of `{"error": ...}`.
This is a real inconsistency in the current code, not a documentation gap.

Provider adapters check for a missing API key before constructing any SDK
client (`src/providers/openai_style.py`, `gemini_provider.py`) so a
missing key is a deterministic `UpstreamUnavailableError` rather than
whatever exception the SDK itself would raise. The Ollama adapter instead
catches `ConnectionError` around the actual `client.chat()` call
(`src/providers/ollama_provider.py`) because there is no "key" to check in
advance; an unreachable host is only known once the request is attempted.

## Persistence

Single SQLite file at `data/app.db` (`src/db.py::DB_PATH`, resolved
relative to the repository root; the parent directory is created if
missing). Schema is created by `Base.metadata.create_all()`
(`src/db.py::init_db`), called at process startup by the API's FastAPI
`lifespan` handler, by `src/tenants/seed_dev.py`, and by `src/quota/cli.py`
; it is idempotent (only creates missing tables) and is called
unconditionally on every run rather than gated behind a migration step.

Tests use `sqlite:///:memory:` through the same `make_engine()` function,
with `StaticPool` and `check_same_thread=False`. `src/db.py` documents why:
an in-memory SQLite database is per-connection, and without `StaticPool` a
request handled in Starlette's threadpool would see a different, empty
database than the one the test set up on the main thread.
