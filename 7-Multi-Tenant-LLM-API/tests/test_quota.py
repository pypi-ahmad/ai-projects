"""rpm=1 hit twice -> second 429; budget already at 100/100 -> reject.
Plus the other checks in check_quota's list get one test each.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from src.auth.errors import TenantSuspendedError
from src.db import PlanLimits, Tenant, init_db, make_engine, make_session_factory
from src.quota.errors import (
    BudgetMonthExceededError,
    MaxTokensPerRequestExceededError,
    ModelNotAllowedError,
    RpmExceededError,
)
from src.quota.limiter import check_quota, remaining_quota
from src.tenants.service import create_api_key
from src.usage.service import record_usage

DEFAULT_LIMITS = {
    "rpm": 60,
    "rpd": 5000,
    "max_tokens_per_req": 4096,
    "token_budget_month": 1_000_000,
    "budget_reset_day": 1,
    "allowed_models": ["granite4.1:3b"],
    "allowed_providers": ["ollama"],
}


def _session() -> Session:
    engine = make_engine(":memory:")
    init_db(engine)
    return make_session_factory(engine)()


def _tenant_with_limits(session: Session, status: str = "active", **overrides) -> Tenant:
    tenant = Tenant(id=str(uuid.uuid4()), name=f"t-{uuid.uuid4().hex[:8]}", status=status)
    session.add(tenant)
    session.flush()
    limits = {**DEFAULT_LIMITS, **overrides}
    session.add(PlanLimits(tenant_id=tenant.id, **limits))
    session.commit()
    return tenant


def _record(session: Session, tenant: Tenant, in_tokens: int = 1, out_tokens: int = 1) -> None:
    key = create_api_key(session, tenant.id, "test-key")
    session.commit()
    record_usage(
        session,
        tenant_id=tenant.id,
        key_id=key.id,
        model="granite4.1:3b",
        provider="ollama",
        in_tokens=in_tokens,
        out_tokens=out_tokens,
        cost_est=0.0,
        latency_ms=10,
        status="ok",
    )
    session.commit()


def _check(session: Session, tenant: Tenant, **kwargs) -> None:
    check_quota(
        session,
        tenant.id,
        model=kwargs.pop("model", "granite4.1:3b"),
        provider=kwargs.pop("provider", "ollama"),
        estimated_tokens=kwargs.pop("estimated_tokens", 1),
        **kwargs,
    )


def test_rpm_one_second_request_blocked() -> None:
    session = _session()
    tenant = _tenant_with_limits(session, rpm=1)

    _check(session, tenant)  # 1st request: allowed
    _record(session, tenant)  # simulates it completing

    with pytest.raises(RpmExceededError) as exc_info:
        _check(session, tenant)  # 2nd request within the same minute: blocked

    assert exc_info.value.code == "RATE_RPM"
    assert exc_info.value.retry_after > 0


def test_budget_already_at_limit_blocked() -> None:
    session = _session()
    tenant = _tenant_with_limits(session, token_budget_month=100)
    _record(session, tenant, in_tokens=60, out_tokens=40)  # 100 tokens used already

    with pytest.raises(BudgetMonthExceededError) as exc_info:
        _check(session, tenant, estimated_tokens=1)

    assert exc_info.value.code == "BUDGET_MONTH"


def test_model_not_allowed_blocked() -> None:
    session = _session()
    tenant = _tenant_with_limits(session)

    with pytest.raises(ModelNotAllowedError):
        _check(session, tenant, model="some-other-model")


def test_max_tokens_per_req_exceeded_blocked() -> None:
    session = _session()
    tenant = _tenant_with_limits(session, max_tokens_per_req=100)

    with pytest.raises(MaxTokensPerRequestExceededError):
        _check(session, tenant, requested_max_tokens=101)


def test_suspended_tenant_blocked() -> None:
    session = _session()
    tenant = _tenant_with_limits(session, status="suspended")

    with pytest.raises(TenantSuspendedError):
        _check(session, tenant)


def test_remaining_quota_reflects_recorded_usage() -> None:
    session = _session()
    tenant = _tenant_with_limits(session, rpm=10, token_budget_month=1000)
    _record(session, tenant, in_tokens=30, out_tokens=20)

    status = remaining_quota(session, tenant.id)

    assert status.rpm_used == 1
    assert status.rpm_limit == 10
    assert status.month_tokens_used == 50
    assert status.month_tokens_limit == 1000
