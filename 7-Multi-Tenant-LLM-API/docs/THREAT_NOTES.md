# Threat Notes

Read before touching auth, key storage, or logging. This tracks known risk
areas specific to this gateway's design and the controls actually in place
against them (verified against code, not aspirational); not a full threat
model.

## 1. Key leak

**Risk:** a tenant API key or a platform provider key (`AGNES_API_KEY`/
`AGNESAI_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`) is exposed via logs,
error messages, DB dump, or source control, letting an attacker act as that
tenant or spend on the platform's provider accounts.

**Controls:**
- Tenant keys are hashed at rest with Argon2id (`argon2-cffi`'s
  `PasswordHasher` default; current OWASP recommendation), in
  `src/auth/keys.py`. The raw key is returned exactly once, at creation
  (or by `seed_dev`), and never stored or logged again in any form.
- Platform provider keys live only in environment variables, read at
  process start; never written to the DB, never included in any API
  response, never logged (not even partially masked; presence/absence
  only, per the platform's existing env-var handling convention).
- `data/app.db` and `.env` are git-ignored (see `.gitignore`).
- Admin token (`ADMIN_TOKEN`) follows the same rule: env-only, never
  persisted or returned by any endpoint. Compared with
  `secrets.compare_digest` (`src/auth/admin.py`), not `==`, and never
  accepted via the tenant-key headers (`Authorization`/`X-Api-Key`);
  `X-Admin-Token` only, and a valid tenant key never satisfies it.

## 2. Tenant enumeration

**Risk:** an attacker probes tenant ids or key values and learns which
exist from response differences, narrowing a brute-force or letting them
map the customer base.

**Controls:**
- Tenant ids are opaque (UUID) so they can't be guessed by counting.
- An unknown prefix and a wrong secret for a known prefix both raise the
  same `InvalidKeyError` (401, code `invalid_key`); an attacker without a
  valid secret can never distinguish "no such key" from "real key, wrong
  guess" (`src/auth/resolve.py`).
- `KeyRevokedError` (401, `key_revoked`) and `TenantSuspendedError` (403,
  `tenant_suspended`) *are* distinguished from `invalid_key`; but both are
  only reachable by supplying the exact secret of a real key (32 random
  bytes; not guessable). Revealing "this specific key you hold was revoked"
  to whoever already holds it isn't an enumeration primitive: it tells them
  nothing about any other tenant or key.
- Argon2's `verify()` (`src/auth/keys.py`) does a constant-time comparison
  of the computed hash; the prefix lookup that narrows candidates first is
  on a public, non-secret value, so it isn't a timing side-channel on the
  secret itself.
- Admin endpoints (which do take a `tenant_id` path parameter) require
  `ADMIN_TOKEN`; a public/tenant caller never reaches a code path where
  tenant ids could be enumerated.

## 3. Prompt log leakage

**Risk:** usage logging captures full prompt/response text, and that log
(or a later export/admin view) exposes tenant data; its own or, if logs
are ever mixed, another tenant's.

**Controls:**
- `usage_events` stores metadata only, always: tenant_id, provider, model,
  token counts, cost, timestamp; the table has no prompt/response text
  column at all (`record_usage`, `src/usage/service.py`).
- If content logging is ever added (debugging, abuse review), it must be
  opt-in, tenant-scoped on read, and called out explicitly in this doc
  before it ships; not a silent default.
- Streamlit admin (`src/ui`) only ever displays aggregated usage, never
  raw per-request content, so no view exists for an admin (or anyone with
  admin-UI access) to browse tenant prompt text.

## 4. Network exposure

**Risk:** the API listens on all interfaces by default, reachable from
the rest of the network (or the internet, if port-forwarded) instead of
only the machine running it.

**Controls:**
- `uvicorn`'s own default bind address is `127.0.0.1` (confirmed via
  `uv run uvicorn --help`, not assumed), and `run.cmd` sets `HOST=127.0.0.1`
  explicitly rather than relying on that default silently; so a future
  uvicorn version changing its default wouldn't change this app's exposure.
  Reaching it from another machine requires deliberately overriding `HOST`
  (or a reverse proxy), not the out-of-the-box behavior.

## 5. Multi-process rate-limit bypass

**Risk:** running more than one API process (multiple uvicorn workers or
replicas) lets a tenant exceed rpm/rpd/budget by racing concurrent
requests across processes, because quota state has no cross-process lock.

**Controls:**
- None implemented; this is a documented limitation, not a mitigated
  risk. `run.cmd` starts exactly one process. See `docs/LIMITS.md` "Not
  safe for multiple processes" for why, and what a real fix would need.

## 6. Upstream error detail leakage

**Risk:** a provider SDK's raw exception (which can carry request/response
internals) reaches the client directly, either as an ugly uncaught 500 or
by echoing exception text into the response body.

**Controls:**
- A missing platform key or an unreachable provider raises
  `UpstreamUnavailableError` (`src/providers/errors.py`), mapped by a
  FastAPI exception handler to a clean `{"error": "UPSTREAM_UNAVAILABLE"}`,
  503; never a bare 500, and never the underlying SDK exception's own
  message text in the response body.
- The key is checked before ever constructing a provider client
  (`src/providers/openai_style.py`, `gemini_provider.py`), so a missing key
  is a deterministic, network-free 503 rather than depending on exactly
  how/when the SDK's own error fires.

## What was actually done (Phase 7 audit)

Not a plan; verified against the current code and test suite:

- **Hash at rest:** tenant API keys are never stored in recoverable form.
  `src/auth/keys.py::hash_key()` runs Argon2id (`argon2-cffi`'s
  `PasswordHasher` default) before anything touches the DB; only the hash
  and an 8-char public `prefix` are persisted (`api_keys.key_hash`,
  `src/db.py`). The raw key exists only in the one response that creates
  it (`ApiKeyCreated`, `src/schemas.py`) and is never logged.
- **Isolation tests:** cross-tenant access is asserted, not just designed
  around; `tests/test_tenancy_isolation.py` (usage query scoping),
  `tests/test_auth.py` (body `tenant_id` ignored, revoked/suspended
  rejected), `tests/test_isolation.py` (tenant A cannot read B's usage,
  cannot set `tenant_id=B` in a request body, a revoked key is dead,
  budget is enforced), and `tests/test_api.py::test_other_tenant_cannot_read_this_tenants_usage`.
  29/29 pass as of this phase.
- **Default no prompt storage:** `Tenant.store_prompts` defaults to
  `False` (`src/db.py`), and no code path anywhere writes to `prompt_logs`
  regardless of that flag's value; there is no writer for it yet, so the
  table is unconditionally empty today, not just opt-in-and-off.
- **Bind localhost:** see "Network exposure" above; `127.0.0.1` is both
  uvicorn's own default and `run.cmd`'s explicit setting.

Known gap, not a control: multi-process deployment breaks rate-limit
enforcement (see "Multi-process rate-limit bypass" above); documented,
not fixed, since this project runs as one process.
