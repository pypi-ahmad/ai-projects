"""Writing usage records (the "after upstream: record actual tokens" step).

Deliberately separate from src/quota -- this only ever inserts a row.
Quota checks read usage_events back out (src/quota/limiter.py); recording
always happens regardless of whether the resulting cumulative usage ends up
over budget (see docs/LIMITS.md "Accounting order").

record_usage() is called only from src/api/app.py::chat (on both success
and provider failure). build_usage_report() backs both GET /v1/usage and
GET /admin/tenants/{id}/usage (src/api/admin_routes.py) -- the two differ
only in whether tenant_id came from the resolved key or a path parameter.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import UsageEvent
from src.quota.limiter import remaining_quota
from src.schemas import QuotaStatusOut, UsageEventOut, UsageReport


def record_usage(
    session: Session,
    *,
    tenant_id: str,
    key_id: str,
    model: str,
    provider: str,
    in_tokens: int,
    out_tokens: int,
    cost_est: float,
    latency_ms: int,
    status: str,
    error_code: str | None = None,
) -> UsageEvent:
    event = UsageEvent(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        key_id=key_id,
        model=model,
        provider=provider,
        in_tokens=in_tokens,
        out_tokens=out_tokens,
        cost_est=cost_est,
        latency_ms=latency_ms,
        status=status,
        error_code=error_code,
    )
    session.add(event)
    session.flush()
    return event


def build_usage_report(session: Session, tenant_id: str) -> UsageReport:
    """Quota status + last 50 events for one tenant -- shared by the
    tenant-facing GET /v1/usage and the admin GET /admin/tenants/{id}/usage,
    which differ only in where tenant_id comes from (resolved key vs. path
    param, the latter behind X-Admin-Token)."""
    quota_status = remaining_quota(session, tenant_id)
    events = (
        session.execute(
            select(UsageEvent)
            .where(UsageEvent.tenant_id == tenant_id)
            .order_by(UsageEvent.ts.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return UsageReport(
        quota=QuotaStatusOut.model_validate(quota_status, from_attributes=True),
        recent_events=[UsageEventOut.model_validate(e) for e in events],
    )
