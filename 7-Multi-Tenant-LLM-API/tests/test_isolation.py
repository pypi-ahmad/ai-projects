"""Cross-tenant isolation and key-lifecycle checks, at the HTTP layer:

- tenant A's key cannot read tenant B's usage
- tenant_id in the request body has no effect (it's resolved from the key)
- a revoked key is dead
- the monthly token budget is enforced

Shared setup (fake DB + client + fixtures) lives in conftest.py.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from conftest import DEFAULT_LIMITS, admin_header, auth_header, client_for, new_engine_with_tenant
from src.db import ApiKey, PlanLimits, Tenant, UsageEvent, make_session_factory
from src.providers.base import ProviderResult
from src.tenants.service import create_api_key
from src.usage.service import record_usage


def _second_tenant(engine, name: str, **limit_overrides: object):
    session = make_session_factory(engine)()
    tenant = Tenant(id=str(uuid.uuid4()), name=name, status="active")
    session.add(tenant)
    session.flush()
    session.add(PlanLimits(tenant_id=tenant.id, **{**DEFAULT_LIMITS, **limit_overrides}))
    created_key = create_api_key(session, tenant.id, "test-key")
    session.commit()
    session.close()
    return tenant, created_key.raw_key


def test_tenant_a_key_cannot_read_tenant_b_usage() -> None:
    engine, tenant_a, key_a = new_engine_with_tenant()
    _tenant_b, key_b = _second_tenant(engine, "tenant-b")

    client = client_for(engine, fake_result=ProviderResult(text="hi", in_tokens=3, out_tokens=4))
    client.post("/v1/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers=auth_header(key_a))

    resp = client.get("/v1/usage", headers=auth_header(key_b))

    assert resp.status_code == 200
    assert resp.json()["recent_events"] == []  # B sees none of A's usage -- only its own (empty)


def test_tenant_a_cannot_set_tenant_id_b_in_body() -> None:
    """ChatRequest has no tenant_id field at all -- one is not read from
    the body under any name. tenant_id is always the one resolved from the
    Authorization key (docs/TENANCY.md)."""
    engine, tenant_a, key_a = new_engine_with_tenant()
    tenant_b, _key_b = _second_tenant(engine, "tenant-b")

    client = client_for(engine, fake_result=ProviderResult(text="hi", in_tokens=3, out_tokens=4))
    resp = client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "tenant_id": tenant_b.id},
        headers=auth_header(key_a),
    )

    assert resp.status_code == 200

    session = make_session_factory(engine)()
    events = session.execute(select(UsageEvent)).scalars().all()
    assert len(events) == 1
    assert events[0].tenant_id == tenant_a.id  # never tenant_b.id, despite the body


def test_revoked_key_is_dead() -> None:
    engine, _tenant, raw_key = new_engine_with_tenant()
    session = make_session_factory(engine)()
    key_row = session.execute(select(ApiKey)).scalars().one()
    tenant_id, key_id = key_row.tenant_id, key_row.id
    session.close()

    client = client_for(engine)
    revoke_resp = client.post(
        f"/admin/tenants/{tenant_id}/keys/{key_id}/revoke", headers=admin_header()
    )
    assert revoke_resp.status_code == 200

    resp = client.get("/v1/models", headers=auth_header(raw_key))

    assert resp.status_code == 401
    assert resp.json() == {"error": "key_revoked"}


def test_budget_enforced() -> None:
    engine, tenant, raw_key = new_engine_with_tenant(token_budget_month=100)
    session = make_session_factory(engine)()
    key = session.execute(select(ApiKey)).scalars().one()
    record_usage(
        session,
        tenant_id=tenant.id,
        key_id=key.id,
        model="granite4.1:3b",
        provider="ollama",
        in_tokens=60,
        out_tokens=40,  # 100 tokens already used, at the 100-token cap
        cost_est=0.0,
        latency_ms=1,
        status="ok",
    )
    session.commit()

    client = client_for(engine, fake_result=ProviderResult(text="hi", in_tokens=1, out_tokens=1))
    resp = client.post(
        "/v1/chat",
        # max_tokens=1 makes the estimate nonzero (see docs/LIMITS.md --
        # an unspecified max_tokens estimates 0, by design), so usage
        # already AT the 100-token cap plus this estimate goes over it.
        json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
        headers=auth_header(raw_key),
    )

    assert resp.status_code == 429
    assert resp.json() == {"error": "BUDGET_MONTH"}
    assert "Retry-After" in resp.headers
