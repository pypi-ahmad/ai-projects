"""Pydantic request/response shapes, mirroring the tables in src/db.py --
this module must not contain business logic, only shapes and their field
constraints. Consumed by the routes in src/api/app.py and
src/api/admin_routes.py; open those next to see each schema in use.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict


class TenantCreate(BaseModel):
    name: str


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: Literal["active", "suspended"]
    store_prompts: bool
    created_at: dt.datetime


class ApiKeyOut(BaseModel):
    """Never carries key_hash or the raw key -- see ApiKeyCreated for the
    one-time exception."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    prefix: str
    name: str
    created_at: dt.datetime
    revoked_at: dt.datetime | None


class ApiKeyCreated(ApiKeyOut):
    """Returned once, at creation, with the raw key. Never persisted or
    re-served after this response."""

    raw_key: str


class ApiKeyCreateRequest(BaseModel):
    name: str = "key"


class PlanLimitsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    rpm: int
    rpd: int
    max_tokens_per_req: int
    token_budget_month: int
    budget_reset_day: int
    allowed_models: list[str]
    allowed_providers: list[str]


class PlanLimitsUpdate(BaseModel):
    rpm: int
    rpd: int
    max_tokens_per_req: int
    token_budget_month: int
    budget_reset_day: int
    allowed_models: list[str]
    allowed_providers: list[str]


class UsageEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    key_id: str
    ts: dt.datetime
    model: str
    provider: str
    in_tokens: int
    out_tokens: int
    cost_est: float
    latency_ms: int
    status: str
    error_code: str | None


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str | None
    actor: str
    action: str
    detail: str | None
    ts: dt.datetime


# --- POST /v1/chat (src/api/app.py) ---


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None
    max_tokens: int | None = None


class UsageOut(BaseModel):
    in_tokens: int
    out_tokens: int


class ChatResponse(BaseModel):
    request_id: str
    model: str
    provider: str
    message: ChatMessage
    usage: UsageOut


# --- GET /v1/models, GET /v1/usage ---


class ModelsOut(BaseModel):
    models: list[str]


class QuotaStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rpm_used: int
    rpm_limit: int
    rpd_used: int
    rpd_limit: int
    month_tokens_used: int
    month_tokens_limit: int
    period_start: dt.datetime
    next_reset: dt.datetime


class UsageReport(BaseModel):
    quota: QuotaStatusOut
    recent_events: list[UsageEventOut]
