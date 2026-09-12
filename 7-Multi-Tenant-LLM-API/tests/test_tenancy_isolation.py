"""Two tenants, usage_events for each, cross-tenant fetch must return empty.

Each test gets its own in-memory SQLite DB (make_engine(":memory:")) so
tests never touch data/app.db and never see each other's rows.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import ApiKey, Tenant, UsageEvent, init_db, make_engine, make_session_factory


def _session() -> Session:
    engine = make_engine(":memory:")
    init_db(engine)
    return make_session_factory(engine)()


def _tenant(session: Session, name: str) -> Tenant:
    tenant = Tenant(id=str(uuid.uuid4()), name=name, status="active")
    session.add(tenant)
    session.flush()
    return tenant


def _key(session: Session, tenant: Tenant, prefix: str) -> ApiKey:
    key = ApiKey(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        prefix=prefix,
        key_hash="not-a-real-hash",
        name="test-key",
    )
    session.add(key)
    session.flush()
    return key


def _usage(session: Session, tenant: Tenant, key: ApiKey) -> UsageEvent:
    event = UsageEvent(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        key_id=key.id,
        model="granite4.1:3b",
        provider="ollama",
        in_tokens=10,
        out_tokens=20,
        cost_est=0.0,
        latency_ms=100,
        status="ok",
    )
    session.add(event)
    session.flush()
    return event


def test_usage_query_scoped_to_owning_tenant() -> None:
    session = _session()
    tenant_a = _tenant(session, "tenant-a")
    tenant_b = _tenant(session, "tenant-b")
    key_a = _key(session, tenant_a, "prefixaa")
    key_b = _key(session, tenant_b, "prefixbb")
    _usage(session, tenant_a, key_a)
    _usage(session, tenant_a, key_a)
    _usage(session, tenant_b, key_b)
    session.commit()

    rows_a = session.execute(
        select(UsageEvent).where(UsageEvent.tenant_id == tenant_a.id)
    ).scalars().all()
    rows_b = session.execute(
        select(UsageEvent).where(UsageEvent.tenant_id == tenant_b.id)
    ).scalars().all()

    assert len(rows_a) == 2
    assert all(row.tenant_id == tenant_a.id for row in rows_a)
    assert len(rows_b) == 1
    assert all(row.tenant_id == tenant_b.id for row in rows_b)


def test_cross_tenant_fetch_returns_empty() -> None:
    session = _session()
    tenant_a = _tenant(session, "tenant-a")
    tenant_b = _tenant(session, "tenant-b")
    key_b = _key(session, tenant_b, "prefixbb")
    _usage(session, tenant_b, key_b)
    session.commit()

    # tenant A's id combined with tenant B's key id -- isolation is enforced
    # on tenant_id, so this must return nothing even though key_b exists.
    rows = session.execute(
        select(UsageEvent).where(
            UsageEvent.tenant_id == tenant_a.id,
            UsageEvent.key_id == key_b.id,
        )
    ).scalars().all()

    assert rows == []
