"""Per-tenant quota enforcement: rpm, rpd, max_tokens_per_req, monthly
token budget -- checked in that order before an upstream call, per
docs/LIMITS.md.

Design choice: rpm/rpd/budget are all computed by counting/summing
`usage_events` rows in the relevant time window, not a separate in-memory
or counter-table structure. `usage_events` is already written after every
completed call (`src/usage/service.py::record_usage`) and already persists
to SQLite, so this gets "restart doesn't reset the day/month budget" for
free, for all three limits, with no extra state to keep in sync or flush.
At this project's scale (single Windows process, one tenant's own events
filtered by its indexed `tenant_id`) the query cost is negligible.
# ponytail: full table scan of one tenant's usage_events per check; add an
# index on (tenant_id, ts) if a tenant's event history ever grows large
# enough for this to show up in profiling.

"actual exceeds budget -> allow this response, reject the next" needs no
special code: `record_usage` always writes the real totals regardless of
whether they push the tenant over budget, and the *next* call's budget
check reads that updated sum and rejects. No cap/truncation logic exists
in v1 (no streaming either), by design.

`check_quota` is called only from src/api/app.py::chat, before dispatching
to a provider. Not safe across multiple processes -- see docs/LIMITS.md
"Not safe for multiple processes" for why (no cross-request lock between
the read here and the write in record_usage).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.errors import TenantSuspendedError
from src.db import PlanLimits, Tenant, UsageEvent
from src.quota.errors import (
    BudgetMonthExceededError,
    MaxTokensPerRequestExceededError,
    ModelNotAllowedError,
    ProviderNotAllowedError,
    RpdExceededError,
    RpmExceededError,
)


def check_quota(
    session: Session,
    tenant_id: str,
    *,
    model: str,
    provider: str,
    estimated_tokens: int,
    requested_max_tokens: int | None = None,
    now: datetime | None = None,
) -> None:
    """Raises on the first check that fails; returns None if the request
    may proceed. Order matches docs/LIMITS.md."""
    now = now or datetime.now(UTC)

    tenant = session.get(Tenant, tenant_id)
    if tenant.status != "active":
        raise TenantSuspendedError()

    limits = session.get(PlanLimits, tenant_id)

    if model not in limits.allowed_models:
        raise ModelNotAllowedError()
    if provider not in limits.allowed_providers:
        raise ProviderNotAllowedError()

    if _count_since(session, tenant_id, now - timedelta(seconds=60), now) >= limits.rpm:
        raise RpmExceededError(retry_after=_rpm_retry_after(session, tenant_id, now))

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if _count_since(session, tenant_id, day_start, now) >= limits.rpd:
        next_day = day_start + timedelta(days=1)
        raise RpdExceededError(retry_after=_seconds_until(now, next_day))

    if requested_max_tokens is not None and requested_max_tokens > limits.max_tokens_per_req:
        raise MaxTokensPerRequestExceededError()

    period_start = _budget_period_start(now, limits.budget_reset_day)
    used = _sum_tokens_since(session, tenant_id, period_start)
    if used + estimated_tokens > limits.token_budget_month:
        next_period = _next_budget_period_start(now, limits.budget_reset_day)
        raise BudgetMonthExceededError(retry_after=_seconds_until(now, next_period))


@dataclass
class QuotaStatus:
    tenant_id: str
    rpm_used: int
    rpm_limit: int
    rpd_used: int
    rpd_limit: int
    month_tokens_used: int
    month_tokens_limit: int
    period_start: datetime
    next_reset: datetime


def remaining_quota(session: Session, tenant_id: str, *, now: datetime | None = None) -> QuotaStatus:
    """Current usage vs. limits -- used by `src/quota/cli.py` and safe to
    call for any tenant regardless of whether they've made a request yet."""
    now = now or datetime.now(UTC)
    limits = session.get(PlanLimits, tenant_id)

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    period_start = _budget_period_start(now, limits.budget_reset_day)

    return QuotaStatus(
        tenant_id=tenant_id,
        rpm_used=_count_since(session, tenant_id, now - timedelta(seconds=60), now),
        rpm_limit=limits.rpm,
        rpd_used=_count_since(session, tenant_id, day_start, now),
        rpd_limit=limits.rpd,
        month_tokens_used=_sum_tokens_since(session, tenant_id, period_start),
        month_tokens_limit=limits.token_budget_month,
        period_start=period_start,
        next_reset=_next_budget_period_start(now, limits.budget_reset_day),
    )


def _count_since(session: Session, tenant_id: str, since: datetime, now: datetime) -> int:
    return session.execute(
        select(func.count())
        .select_from(UsageEvent)
        .where(UsageEvent.tenant_id == tenant_id, UsageEvent.ts >= since, UsageEvent.ts <= now)
    ).scalar_one()


def _sum_tokens_since(session: Session, tenant_id: str, since: datetime) -> int:
    total = session.execute(
        select(func.coalesce(func.sum(UsageEvent.in_tokens + UsageEvent.out_tokens), 0)).where(
            UsageEvent.tenant_id == tenant_id, UsageEvent.ts >= since
        )
    ).scalar_one()
    return int(total)


def _rpm_retry_after(session: Session, tenant_id: str, now: datetime) -> int:
    """Seconds until the oldest request in the current 60s window ages out
    and one more request is allowed."""
    earliest = session.execute(
        select(func.min(UsageEvent.ts)).where(
            UsageEvent.tenant_id == tenant_id, UsageEvent.ts >= now - timedelta(seconds=60)
        )
    ).scalar_one()
    if earliest is None:
        return 60
    if earliest.tzinfo is None:
        # SQLite drops tzinfo on round-trip; everything stored is UTC.
        earliest = earliest.replace(tzinfo=UTC)
    return _seconds_until(now, earliest + timedelta(seconds=60))


def _seconds_until(now: datetime, later: datetime) -> int:
    remaining = (later - now).total_seconds()
    return max(1, int(remaining) + 1)


def _clamp_day(year: int, month: int, day: int) -> int:
    return min(day, calendar.monthrange(year, month)[1])


def _budget_period_start(now: datetime, reset_day: int) -> datetime:
    day = _clamp_day(now.year, now.month, reset_day)
    candidate = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    if now < candidate:
        year, month = now.year, now.month - 1
        if month == 0:
            month, year = 12, year - 1
        day = _clamp_day(year, month, reset_day)
        candidate = now.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
    return candidate


def _next_budget_period_start(now: datetime, reset_day: int) -> datetime:
    start = _budget_period_start(now, reset_day)
    year, month = start.year, start.month + 1
    if month == 13:
        month, year = 1, year + 1
    day = _clamp_day(year, month, reset_day)
    return start.replace(year=year, month=month, day=day)
