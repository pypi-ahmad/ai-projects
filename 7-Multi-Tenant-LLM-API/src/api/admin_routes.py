"""Admin routes -- every route here requires X-Admin-Token
(src/api/deps.py::require_admin), never a tenant key. Included into the app
in src/api/app.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_session, require_admin
from src.db import AuditEvent, Tenant
from src.schemas import (
    ApiKeyCreated,
    ApiKeyCreateRequest,
    ApiKeyOut,
    PlanLimitsOut,
    PlanLimitsUpdate,
    TenantCreate,
    TenantOut,
    UsageReport,
)
from src.tenants.service import create_api_key, create_tenant, revoke_key, suspend_tenant, update_plan_limits
from src.usage.service import build_usage_report

router = APIRouter(prefix="/admin/tenants", dependencies=[Depends(require_admin)])


def _get_tenant_or_404(session: Session, tenant_id: str) -> Tenant:
    # Deliberately FastAPI's own HTTPException here, not one of this
    # app's AuthError/QuotaError/ProviderError types -- the body comes back
    # as {"detail": ...}, not this API's usual {"error": "<CODE>"} shape.
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return tenant


def _audit(session: Session, tenant_id: str, action: str, detail: str) -> None:
    session.add(
        AuditEvent(id=str(uuid.uuid4()), tenant_id=tenant_id, actor="admin", action=action, detail=detail)
    )


@router.post("", response_model=TenantOut)
def create_tenant_route(payload: TenantCreate, session: Session = Depends(get_session)) -> TenantOut:
    tenant = create_tenant(session, payload.name)
    _audit(session, tenant.id, "create_tenant", payload.name)
    session.commit()
    return TenantOut.model_validate(tenant, from_attributes=True)


@router.post("/{tenant_id}/keys", response_model=ApiKeyCreated)
def create_key_route(
    tenant_id: str, payload: ApiKeyCreateRequest, session: Session = Depends(get_session)
) -> ApiKeyCreated:
    _get_tenant_or_404(session, tenant_id)
    created = create_api_key(session, tenant_id, payload.name)
    _audit(session, tenant_id, "create_key", f"issued key {created.id} (prefix {created.prefix})")
    session.commit()
    return created


@router.post("/{tenant_id}/limits", response_model=PlanLimitsOut)
def update_limits_route(
    tenant_id: str, payload: PlanLimitsUpdate, session: Session = Depends(get_session)
) -> PlanLimitsOut:
    _get_tenant_or_404(session, tenant_id)
    limits = update_plan_limits(session, tenant_id, **payload.model_dump())
    _audit(session, tenant_id, "update_limits", str(payload.model_dump()))
    session.commit()
    return PlanLimitsOut.model_validate(limits, from_attributes=True)


@router.post("/{tenant_id}/suspend", response_model=TenantOut)
def suspend_route(tenant_id: str, session: Session = Depends(get_session)) -> TenantOut:
    _get_tenant_or_404(session, tenant_id)
    tenant = suspend_tenant(session, tenant_id)
    _audit(session, tenant_id, "suspend_tenant", "")
    session.commit()
    return TenantOut.model_validate(tenant, from_attributes=True)


@router.get("/{tenant_id}/usage", response_model=UsageReport)
def usage_route(tenant_id: str, session: Session = Depends(get_session)) -> UsageReport:
    _get_tenant_or_404(session, tenant_id)
    return build_usage_report(session, tenant_id)


@router.post("/{tenant_id}/keys/{key_id}/revoke", response_model=ApiKeyOut)
def revoke_key_route(tenant_id: str, key_id: str, session: Session = Depends(get_session)) -> ApiKeyOut:
    _get_tenant_or_404(session, tenant_id)
    # revoke_key() returns None both when key_id doesn't exist and when it
    # belongs to a different tenant -- same 404 either way, so this path
    # can't be used to probe whether a key_id exists under another tenant.
    key = revoke_key(session, tenant_id, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="key not found for this tenant")
    _audit(session, tenant_id, "revoke_key", key_id)
    session.commit()
    return ApiKeyOut.model_validate(key, from_attributes=True)
