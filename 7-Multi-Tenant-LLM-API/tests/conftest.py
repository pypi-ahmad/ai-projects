"""Shared test helpers: an in-memory per-test DB + FastAPI TestClient with
a fake provider dispatcher, so tests never touch a real upstream or the
real data/app.db. Imported directly by sibling test files (pytest puts
this directory on sys.path via its conftest/rootdir discovery).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.app import app
from src.api.deps import get_dispatcher, get_session
from src.db import PlanLimits, Tenant, init_db, make_engine, make_session_factory
from src.providers.base import ProviderResult
from src.tenants.service import create_api_key

DEFAULT_LIMITS = {
    "rpm": 60,
    "rpd": 5000,
    "max_tokens_per_req": 4096,
    "token_budget_month": 1_000_000,
    "budget_reset_day": 1,
    "allowed_models": ["granite4.1:3b"],
    "allowed_providers": ["ollama"],
}

TEST_ADMIN_TOKEN = "test-admin-token"


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", TEST_ADMIN_TOKEN)


def new_engine_with_tenant(**limit_overrides: object):
    engine = make_engine(":memory:")
    init_db(engine)
    session = make_session_factory(engine)()
    tenant = Tenant(id=str(uuid.uuid4()), name=f"t-{uuid.uuid4().hex[:8]}", status="active")
    session.add(tenant)
    session.flush()
    session.add(PlanLimits(tenant_id=tenant.id, **{**DEFAULT_LIMITS, **limit_overrides}))
    created_key = create_api_key(session, tenant.id, "test-key")
    session.commit()
    session.close()
    return engine, tenant, created_key.raw_key


def client_for(
    engine, fake_result: ProviderResult | None = None, fake_error: Exception | None = None
) -> TestClient:
    session_factory = make_session_factory(engine)

    def _get_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def _dispatcher(provider, model, messages, max_tokens):
        if fake_error is not None:
            raise fake_error
        return fake_result or ProviderResult(text="hi", in_tokens=5, out_tokens=7)

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_dispatcher] = lambda: _dispatcher
    return TestClient(app)


def auth_header(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def admin_header() -> dict[str, str]:
    return {"X-Admin-Token": TEST_ADMIN_TOKEN}
