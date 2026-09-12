"""Tenant/key administration operations (admin-only, per docs/ARCHITECTURE.md).

Callers commit; these only add/flush, matching the rest of the codebase's
convention (route handlers own the transaction boundary).

Called from src/api/admin_routes.py (every route) and, for create_tenant
and create_api_key, from src/tenants/seed_dev.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.auth.keys import generate_api_key, hash_key
from src.db import ApiKey, PlanLimits, Tenant
from src.schemas import ApiKeyCreated

DEFAULT_LIMITS = {
    "rpm": 60,
    "rpd": 5000,
    "max_tokens_per_req": 4096,
    "token_budget_month": 1_000_000,
    "budget_reset_day": 1,
    "allowed_models": ["granite4.1:3b"],
    "allowed_providers": ["ollama"],
}


def create_tenant(session: Session, name: str) -> Tenant:
    """New tenants start on DEFAULT_LIMITS -- immediately usable with the
    dev-friendly Ollama model, not zeroed out. Adjust via
    update_plan_limits()."""
    tenant = Tenant(id=str(uuid.uuid4()), name=name, status="active")
    session.add(tenant)
    session.flush()
    session.add(PlanLimits(tenant_id=tenant.id, **DEFAULT_LIMITS))
    return tenant


def create_api_key(session: Session, tenant_id: str, name: str) -> ApiKeyCreated:
    """Generates prefix + secret, stores only the hash, returns the raw key
    -- this is the only place the raw key is ever available."""
    raw_key, prefix = generate_api_key()
    row = ApiKey(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        prefix=prefix,
        key_hash=hash_key(raw_key),
        name=name,
    )
    session.add(row)
    session.flush()
    return ApiKeyCreated(
        id=row.id,
        tenant_id=row.tenant_id,
        prefix=row.prefix,
        name=row.name,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
        raw_key=raw_key,
    )


def update_plan_limits(session: Session, tenant_id: str, **fields: object) -> PlanLimits:
    limits = session.get(PlanLimits, tenant_id)
    for key, value in fields.items():
        setattr(limits, key, value)
    session.flush()
    return limits


def suspend_tenant(session: Session, tenant_id: str) -> Tenant:
    tenant = session.get(Tenant, tenant_id)
    tenant.status = "suspended"
    session.flush()
    return tenant


def revoke_key(session: Session, tenant_id: str, key_id: str) -> ApiKey | None:
    """None if the key doesn't exist or belongs to a different tenant --
    the route turns that into a 404 rather than silently revoking (or
    revealing) another tenant's key via a mismatched path."""
    key = session.get(ApiKey, key_id)
    if key is None or key.tenant_id != tenant_id:
        return None
    key.revoked_at = datetime.now(UTC)
    session.flush()
    return key
