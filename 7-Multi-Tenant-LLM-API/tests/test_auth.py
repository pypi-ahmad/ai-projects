"""Valid key, revoked, wrong key, admin token, body tenant_id ignored."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from src.auth.admin import verify_admin
from src.auth.errors import (
    InvalidAdminTokenError,
    InvalidKeyError,
    KeyRevokedError,
    MissingCredentialsError,
    TenantSuspendedError,
)
from src.auth.resolve import authenticate
from src.db import ApiKey, Tenant, init_db, make_engine, make_session_factory
from src.tenants.service import create_api_key


def _session() -> Session:
    engine = make_engine(":memory:")
    init_db(engine)
    return make_session_factory(engine)()


def _tenant(session: Session, name: str, status: str = "active") -> Tenant:
    tenant = Tenant(id=str(uuid.uuid4()), name=name, status=status)
    session.add(tenant)
    session.flush()
    return tenant


def test_valid_key_resolves_tenant_and_key() -> None:
    session = _session()
    tenant = _tenant(session, "acme")
    created = create_api_key(session, tenant.id, "primary")
    session.commit()

    ctx = authenticate(session, {"Authorization": f"Bearer {created.raw_key}"})

    assert ctx.tenant_id == tenant.id
    assert ctx.key_id == created.id


def test_valid_key_via_x_api_key_header() -> None:
    session = _session()
    tenant = _tenant(session, "acme")
    created = create_api_key(session, tenant.id, "primary")
    session.commit()

    ctx = authenticate(session, {"X-Api-Key": created.raw_key})

    assert ctx.tenant_id == tenant.id


def test_wrong_key_rejected() -> None:
    session = _session()
    tenant = _tenant(session, "acme")
    create_api_key(session, tenant.id, "primary")
    session.commit()

    with pytest.raises(InvalidKeyError):
        authenticate(session, {"Authorization": "Bearer totally-wrong-secret-value"})


def test_missing_credentials_rejected() -> None:
    with pytest.raises(MissingCredentialsError):
        authenticate(_session(), {})


def test_revoked_key_rejected() -> None:
    session = _session()
    tenant = _tenant(session, "acme")
    created = create_api_key(session, tenant.id, "primary")
    row = session.get(ApiKey, created.id)
    row.revoked_at = datetime.now(UTC)
    session.commit()

    with pytest.raises(KeyRevokedError):
        authenticate(session, {"Authorization": f"Bearer {created.raw_key}"})


def test_suspended_tenant_rejected() -> None:
    session = _session()
    tenant = _tenant(session, "acme", status="suspended")
    created = create_api_key(session, tenant.id, "primary")
    session.commit()

    with pytest.raises(TenantSuspendedError):
        authenticate(session, {"Authorization": f"Bearer {created.raw_key}"})


def test_admin_token_valid() -> None:
    verify_admin({"X-Admin-Token": "secret123"}, admin_token="secret123")


def test_admin_token_invalid() -> None:
    with pytest.raises(InvalidAdminTokenError):
        verify_admin({"X-Admin-Token": "wrong"}, admin_token="secret123")


def test_admin_rejects_tenant_key_header() -> None:
    """A valid-looking Authorization header must not satisfy admin auth --
    only X-Admin-Token does."""
    with pytest.raises(InvalidAdminTokenError):
        verify_admin({"Authorization": "Bearer some-tenant-key"}, admin_token="secret123")


def test_body_tenant_id_ignored() -> None:
    """authenticate() never reads a request body; tenant_id comes only from
    the resolved key. A client passing a different tenant_id in its body
    has no effect on the resolved context."""
    session = _session()
    tenant = _tenant(session, "acme")
    other_tenant = _tenant(session, "other")
    created = create_api_key(session, tenant.id, "primary")
    session.commit()

    body = {"tenant_id": other_tenant.id, "prompt": "hello"}
    ctx = authenticate(session, {"Authorization": f"Bearer {created.raw_key}"})

    assert ctx.tenant_id == tenant.id
    assert ctx.tenant_id != body["tenant_id"]
