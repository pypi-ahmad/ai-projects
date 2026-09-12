# API

Implemented in `src/api/app.py` (tenant-facing) and
`src/api/admin_routes.py` (admin).

¹ `Authorization: Bearer <raw key>` or `X-Api-Key: <raw key>`; resolved via
`src/auth/resolve.py::authenticate()` to a `RequestContext(tenant_id,
key_id)`.
² `X-Admin-Token: <ADMIN_TOKEN>`; resolved via `src/auth/admin.py::verify_admin()`.
Never a tenant key; a valid tenant key does not satisfy admin auth.

| Method | Path | Auth | Purpose | Status |
|---|---|---|---|---|
| GET | `/health` | none | Liveness check | **implemented** |
| POST | `/v1/chat` | tenant key¹ | Chat completion, routed to the tenant's resolved provider/model | **implemented** |
| GET | `/v1/models` | tenant key¹ | List models the calling tenant is allowed to use | **implemented** |
| GET | `/v1/usage` | tenant key¹ | This tenant's own quota status + recent usage events; no `tenant_id` param exists, scope comes only from the resolved key | **implemented** |
| POST | `/admin/tenants` | admin token² | Create a tenant (starts on default plan limits) | **implemented** |
| POST | `/admin/tenants/{tenant_id}/keys` | admin token² | Issue a new tenant API key (raw value returned once) | **implemented** |
| POST | `/admin/tenants/{tenant_id}/limits` | admin token² | Replace a tenant's plan limits (rpm, rpd, budget, allowed models/providers) | **implemented** |
| POST | `/admin/tenants/{tenant_id}/suspend` | admin token² | Suspend a tenant (no unsuspend route exists) | **implemented** |
| GET | `/admin/tenants/{tenant_id}/usage` | admin token² | Usage report for one tenant | **implemented** |
| POST | `/admin/tenants/{tenant_id}/keys/{key_id}/revoke` | admin token² | Revoke a tenant key | **implemented** |
| GET | `/admin/tenants/{tenant_id}` | admin token² | Get tenant details | planned |

All `/admin/tenants/{tenant_id}/...` routes 404 (`{"detail": "tenant not found"}`)
for an unknown `tenant_id`; the revoke route also 404s if `key_id` doesn't
belong to `tenant_id`, so a mismatched path can't touch another tenant's key.

## POST /v1/chat

Request:
```json
{"messages": [{"role": "user", "content": "hello"}], "model": "optional", "max_tokens": 100}
```
`model` defaults to the tenant's first `allowed_models` entry if omitted
(see `docs/ARCHITECTURE.md`'s "no `default_model` column" note). Rejected
with `MODEL_NOT_ALLOWED` (403) if not in the tenant's `allowed_models`. Any
other field (e.g. a client-supplied `tenant_id`) is silently ignored; the
schema doesn't define it, and tenant_id always comes from the resolved key
regardless of the body (see `docs/TENANCY.md`).

Edge case: if a tenant's `allowed_models` names a model that isn't in
`src/providers/registry.py::MODEL_PROVIDERS` (a plan misconfiguration;
that registry is the fixed spec catalog, not admin-editable), `chat()`
resolves `provider = None`, and `check_quota` rejects with
`PROVIDER_NOT_ALLOWED` (403), not `MODEL_NOT_ALLOWED`; the model-allowed
check passes (it *is* in the tenant's list), the provider-allowed check is
what actually catches it.

Response:
```json
{
  "request_id": "...",
  "model": "granite4.1:3b",
  "provider": "ollama",
  "message": {"role": "assistant", "content": "..."},
  "usage": {"in_tokens": 9, "out_tokens": 10}
}
```
`request_id` is the id of the `usage_events` row this call wrote; not a
separate concept.

Errors are `{"error": "<CODE>"}` with the status the code implies (see
`src/auth/errors.py`, `src/quota/errors.py`, `src/providers/errors.py`):
`missing_credentials`/`invalid_key`/`key_revoked` (401), `tenant_suspended`/
`MODEL_NOT_ALLOWED`/`PROVIDER_NOT_ALLOWED` (403), `MAX_TOKENS_PER_REQUEST`
(400), `RATE_RPM`/`RATE_RPD`/`BUDGET_MONTH` (429, with a `Retry-After`
header), `UPSTREAM_UNAVAILABLE` (503; missing platform key or an
unreachable provider, never a bare 500).

Provider dispatch (`src/providers/registry.py::dispatch`) is injected via
FastAPI `Depends` specifically so tests substitute a fake upstream instead
of calling Ollama/Agnes/OpenAI/Gemini for real; see `tests/test_api.py`.

## Admin routes

Every `/admin/...` route requires `X-Admin-Token` (`src/api/deps.py::require_admin`);
a valid tenant key never satisfies it. A missing/wrong token gets
`{"error": "invalid_admin_token"}`, 401 (`InvalidAdminTokenError`,
`src/auth/errors.py`); the same shape as the tenant-key errors above,
just a different code. `POST /admin/tenants/{id}/limits`
takes the full `PlanLimitsUpdate` shape (all fields required; it replaces
the row, not a partial patch):
```json
{"rpm": 60, "rpd": 5000, "max_tokens_per_req": 4096, "token_budget_month": 1000000,
 "budget_reset_day": 1, "allowed_models": ["granite4.1:3b"], "allowed_providers": ["ollama"]}
```
See `docs/RUNBOOK.md` for full curl examples of every admin route.
