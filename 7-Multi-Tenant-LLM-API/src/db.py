"""SQLAlchemy schema and engine/session helpers.

Schema lives in one module because every table below shares foreign keys
with `tenants` and is small enough (6 tables) that splitting it across the
domain packages (`src/auth`, `src/tenants`, ...) would only add indirection.
This module must not contain business logic (quota math, key hashing,
auth checks) -- that lives in the owning domain package instead:
`src/auth`, `src/tenants`, `src/quota`, `src/usage`. Open one of those next
to see how these tables are actually used.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy import JSON, ForeignKey, create_engine
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "app.db"


def _utcnow() -> dt.datetime:
    # Written tz-aware, but SQLite drops tzinfo on read-back -- every
    # column using this default comes back naive on a fresh query. Treat
    # any such value as UTC; src/quota/limiter.py re-attaches tzinfo
    # before doing datetime arithmetic on one, and does so precisely
    # because this was hit as a live bug once (naive/aware subtraction
    # raises TypeError).
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(default="active")  # active | suspended
    store_prompts: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    prefix: Mapped[str] = mapped_column(index=True)  # first 8 chars of raw key, public
    key_hash: Mapped[str]
    name: Mapped[str]
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(default=None)


class PlanLimits(Base):
    __tablename__ = "plan_limits"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    rpm: Mapped[int]
    rpd: Mapped[int]
    max_tokens_per_req: Mapped[int]
    token_budget_month: Mapped[int]
    budget_reset_day: Mapped[int]
    allowed_models: Mapped[list[str]] = mapped_column(JSON)
    allowed_providers: Mapped[list[str]] = mapped_column(JSON)


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    key_id: Mapped[str] = mapped_column(ForeignKey("api_keys.id"))
    ts: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    model: Mapped[str]
    provider: Mapped[str]
    in_tokens: Mapped[int]
    out_tokens: Mapped[int]
    cost_est: Mapped[float]
    latency_ms: Mapped[int]
    status: Mapped[str]
    error_code: Mapped[str | None] = mapped_column(default=None)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(primary_key=True)
    # Nullable unlike every other tenant_id in this file -- the schema
    # allows an audit event with no single owning tenant. Every current
    # writer (src/tenants/seed_dev.py, src/api/app.py, admin_routes.py)
    # still passes one; this column being optional isn't exercised yet.
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), default=None)
    actor: Mapped[str]
    action: Mapped[str]
    detail: Mapped[str | None] = mapped_column(default=None)
    ts: Mapped[dt.datetime] = mapped_column(default=_utcnow)


class PromptLog(Base):
    """Only written when the owning tenant's `store_prompts` flag is true.

    Body encryption is not implemented yet (no key-management infra exists
    in this phase) -- see docs/THREAT_NOTES.md. Default off means this table
    stays empty for every tenant until that flag and the writer exist.
    """

    __tablename__ = "prompt_logs"

    id: Mapped[str] = mapped_column(primary_key=True)
    usage_event_id: Mapped[str] = mapped_column(ForeignKey("usage_events.id"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    prompt: Mapped[str]
    response: Mapped[str]
    ts: Mapped[dt.datetime] = mapped_column(default=_utcnow)


def make_engine(database: str | Path = DB_PATH) -> Engine:
    if database == ":memory:":
        # A sqlite ":memory:" DB is per-connection -- with the default
        # per-thread pool, a FastAPI route running in Starlette's
        # threadpool would see a different, empty database than the one
        # test setup created on the main thread. StaticPool shares a
        # single connection across every thread, which is exactly what an
        # in-memory test DB needs.
        return create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    url = URL.create(drivername="sqlite", database=str(database))
    return create_engine(url)


def init_db(engine: Engine) -> None:
    """Create any missing tables. Idempotent -- safe to call on every run.

    See docs/ARCHITECTURE.md "Migrations" for why this replaces Alembic for
    now.
    """
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


engine = make_engine()
SessionLocal = make_session_factory(engine)
