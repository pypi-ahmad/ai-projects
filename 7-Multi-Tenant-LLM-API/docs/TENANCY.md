# Tenancy & Isolation Rules

## The core rule

**`tenant_id` is never accepted from client input.** Not the JSON body, not
a query parameter, not a header the client sets directly. It is resolved
exactly one way: `src/auth/resolve.py::authenticate()` looks up the raw key
(from `Authorization: Bearer <key>` or `X-Api-Key`) against `api_keys` and
returns a `RequestContext(tenant_id, key_id)` for the key it matched.

Any endpoint handler that reads `tenant_id` from the request instead of from
the `RequestContext` the FastAPI dependency `src/api/deps.py::get_context`
attaches is a bug, full stop — it lets a tenant impersonate another by
guessing or supplying a different id. `tests/test_auth.py::test_body_tenant_id_ignored`
and `tests/test_isolation.py::test_tenant_a_cannot_set_tenant_id_b_in_body`
assert this directly: a body carrying another tenant's id has no effect on
the resolved context.

## Why

If `tenant_id` came from request input, a tenant could pass a different
tenant's id and read or affect that tenant's data with its own valid key.
Deriving it solely from server-side key lookup makes cross-tenant access
require a stolen key, not a guessed id.

## What is isolated per tenant_id

- API keys (`api_keys`) — a key belongs to exactly one tenant
- Usage records (`usage_events`) — every row scoped to the owning tenant
- Quota / rate-limit state (`plan_limits`) — `src/quota/limiter.py` computes
  rpm/rpd/budget by querying `usage_events` for that tenant_id, not a
  separate counter table (see `docs/LIMITS.md`) — never shared across tenants
- Any future per-tenant config (allowed models, default provider, etc.)

## What is NOT tenant data

- Platform provider credentials (`AGNES_API_KEY`/`AGNESAI_API_KEY`,
  `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `OLLAMA_HOST`) — shared gateway
  config, set once in the environment, never scoped per tenant, never
  returned in any tenant-facing response.
- The admin token (`ADMIN_TOKEN`) — a separate, non-tenant credential for
  the admin-only routes in `src/api/admin_routes.py` (create tenant, issue
  key, update limits, suspend, view usage, revoke key). Admin endpoints are
  the only place `tenant_id` may legitimately appear as a path parameter,
  because the caller is administering the system, not acting as that tenant.

## Enforcement points

- `src/auth/resolve.py::authenticate()` — resolves
  `RequestContext(tenant_id, key_id)` from the key; raises
  `MissingCredentialsError` / `InvalidKeyError` / `KeyRevokedError` /
  `TenantSuspendedError` (`src/auth/errors.py`) otherwise. Never accepts
  `tenant_id` as an argument.
- `src/auth/admin.py::verify_admin()` — admin auth is
  `X-Admin-Token == $ADMIN_TOKEN`, a completely separate check from tenant
  keys; a valid tenant key never satisfies it (see
  `tests/test_auth.py::test_admin_rejects_tenant_key_header`).
- `src/quota/limiter.py::check_quota()` — every rpm/rpd/budget query is
  scoped to the resolved `tenant_id`; nothing here takes a tenant_id from
  request input either.
- `src/usage/service.py::record_usage()` — every write is stamped with the
  resolved `tenant_id`.
- Admin routes (`src/api/admin_routes.py`) require `ADMIN_TOKEN`, not a
  tenant key, and are the only place a `tenant_id` path parameter is
  legitimate — enforced with a 404 (not silent success) when `tenant_id`
  (or a nested `key_id`) doesn't actually match, see `docs/API.md`.
