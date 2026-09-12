"""Seed a "dev" tenant with default plan limits and print one raw API key.

Usage: uv run python -m src.tenants.seed_dev

The raw key is printed exactly once, here, and never stored -- only its
Argon2id hash is persisted (see src/auth/keys.py). Re-running is safe: it
reuses the existing "dev" tenant (if present) and issues a fresh key.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from src.db import AuditEvent, SessionLocal, Tenant, engine, init_db
from src.tenants.service import create_api_key, create_tenant

DEV_TENANT_NAME = "dev"


def main() -> None:
    init_db(engine)
    with SessionLocal() as session:
        tenant = session.execute(
            select(Tenant).where(Tenant.name == DEV_TENANT_NAME)
        ).scalar_one_or_none()
        created_tenant = tenant is None

        if tenant is None:
            tenant = create_tenant(session, DEV_TENANT_NAME)
            session.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant.id,
                    actor="seed_dev",
                    action="create_tenant",
                    detail=f"seeded dev tenant {tenant.id}",
                )
            )

        created_key = create_api_key(session, tenant.id, name="dev-seed-key")
        session.add(
            AuditEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                actor="seed_dev",
                action="create_key",
                detail=f"issued key {created_key.id} (prefix {created_key.prefix})",
            )
        )
        session.commit()
        tenant_id = tenant.id

    if created_tenant:
        print(f"Created tenant 'dev' ({tenant_id})")
    else:
        print(f"Tenant 'dev' already exists ({tenant_id})")
    print(f"Raw API key (shown once, not recoverable): {created_key.raw_key}")


if __name__ == "__main__":
    main()
