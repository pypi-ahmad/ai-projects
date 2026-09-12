"""Print remaining quota for a tenant.

Usage: uv run python -m src.quota.cli <tenant_name>
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from src.db import SessionLocal, Tenant, engine, init_db
from src.quota.limiter import remaining_quota


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: uv run python -m src.quota.cli <tenant_name>", file=sys.stderr)
        raise SystemExit(2)

    tenant_name = sys.argv[1]
    init_db(engine)
    with SessionLocal() as session:
        tenant = session.execute(
            select(Tenant).where(Tenant.name == tenant_name)
        ).scalar_one_or_none()
        if tenant is None:
            print(f"No tenant named {tenant_name!r}", file=sys.stderr)
            raise SystemExit(1)

        status = remaining_quota(session, tenant.id)

        print(f"Tenant: {tenant.name} ({tenant.id})")
        print(f"RPM:    {status.rpm_used}/{status.rpm_limit} used this minute")
        print(f"RPD:    {status.rpd_used}/{status.rpd_limit} used today (UTC)")
        print(
            f"Budget: {status.month_tokens_used}/{status.month_tokens_limit} tokens "
            f"(period since {status.period_start.isoformat()}, "
            f"resets {status.next_reset.isoformat()})"
        )


if __name__ == "__main__":
    main()
