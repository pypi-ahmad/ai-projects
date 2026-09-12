"""POST /v1/chat, GET /v1/models, GET /v1/usage, GET /health -- with a fake
upstream (no real Ollama/Agnes/OpenAI/Gemini call ever happens in these
tests). Real auth (`src/auth/resolve.py`) and real quota
(`src/quota/limiter.py`) run for real against an in-memory per-test DB.

Shared setup (fake DB + client + fixtures) lives in conftest.py.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from conftest import DEFAULT_LIMITS, auth_header, client_for, new_engine_with_tenant
from src.db import PlanLimits, Tenant, UsageEvent, make_engine, make_session_factory
from src.providers.base import ProviderResult
from src.providers.errors import UpstreamUnavailableError
from src.quota.limiter import remaining_quota
from src.tenants.service import create_api_key


def test_health_needs_no_auth() -> None:
    client = client_for(make_engine(":memory:"))
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_success_writes_usage() -> None:
    engine, tenant, raw_key = new_engine_with_tenant()
    client = client_for(engine, fake_result=ProviderResult(text="hello there", in_tokens=10, out_tokens=20))

    resp = client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(raw_key),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "granite4.1:3b"  # defaulted from the tenant's plan
    assert body["provider"] == "ollama"
    assert body["message"]["content"] == "hello there"
    assert body["usage"] == {"in_tokens": 10, "out_tokens": 20}
    assert body["request_id"]

    session = make_session_factory(engine)()
    events = session.execute(select(UsageEvent).where(UsageEvent.tenant_id == tenant.id)).scalars().all()
    assert len(events) == 1
    assert (events[0].in_tokens, events[0].out_tokens, events[0].status) == (10, 20, "ok")


def test_chat_rejects_model_not_in_allowed_models() -> None:
    engine, _tenant, raw_key = new_engine_with_tenant()
    client = client_for(engine)

    resp = client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "model": "not-a-real-model"},
        headers=auth_header(raw_key),
    )

    assert resp.status_code == 403
    assert resp.json() == {"error": "MODEL_NOT_ALLOWED"}


def test_upstream_failure_missing_key_is_503_not_500() -> None:
    engine, _tenant, raw_key = new_engine_with_tenant()
    client = client_for(engine, fake_error=UpstreamUnavailableError("missing platform key"))

    resp = client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(raw_key),
    )

    assert resp.status_code == 503
    assert resp.json() == {"error": "UPSTREAM_UNAVAILABLE"}


def test_upstream_failure_increments_rpd_not_token_budget() -> None:
    engine, tenant, raw_key = new_engine_with_tenant(token_budget_month=1000)
    client = client_for(engine, fake_error=UpstreamUnavailableError("missing platform key"))

    client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(raw_key),
    )

    session = make_session_factory(engine)()
    events = session.execute(select(UsageEvent).where(UsageEvent.tenant_id == tenant.id)).scalars().all()
    assert len(events) == 1
    assert (events[0].in_tokens, events[0].out_tokens, events[0].status) == (0, 0, "error")

    status = remaining_quota(session, tenant.id)
    assert status.rpd_used == 1  # the failed request still counted as a request
    assert status.month_tokens_used == 0  # but contributed no tokens


def test_other_tenant_cannot_read_this_tenants_usage() -> None:
    engine, tenant_a, key_a = new_engine_with_tenant()
    session = make_session_factory(engine)()
    tenant_b = Tenant(id=str(uuid.uuid4()), name="tenant-b", status="active")
    session.add(tenant_b)
    session.flush()
    session.add(PlanLimits(tenant_id=tenant_b.id, **DEFAULT_LIMITS))
    key_b = create_api_key(session, tenant_b.id, "b-key")
    session.commit()

    client = client_for(engine, fake_result=ProviderResult(text="hi", in_tokens=1, out_tokens=1))
    client.post("/v1/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers=auth_header(key_a))

    resp = client.get("/v1/usage", headers=auth_header(key_b.raw_key))

    assert resp.status_code == 200
    assert resp.json()["recent_events"] == []  # tenant A's event is invisible to tenant B


def test_models_lists_this_tenants_allowed_models() -> None:
    engine, _tenant, raw_key = new_engine_with_tenant(allowed_models=["granite4.1:3b", "qwen3.5:2b"])
    client = client_for(engine)

    resp = client.get("/v1/models", headers=auth_header(raw_key))

    assert resp.status_code == 200
    assert resp.json() == {"models": ["granite4.1:3b", "qwen3.5:2b"]}
