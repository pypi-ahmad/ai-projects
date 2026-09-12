"""FastAPI app: POST /v1/chat, GET /v1/models, GET /v1/usage, GET /health,
plus the admin routes (src/api/admin_routes.py). This is the process
entrypoint uvicorn loads (`uvicorn src.api.app:app`); open
src/api/deps.py next to see what each `Depends(...)` below resolves to.

Route handlers are plain `def`, not `async def` -- everything they call
(SQLAlchemy's sync Session, the sync provider SDKs) is blocking, and
Starlette runs sync path operations in a threadpool automatically so they
never block the event loop.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.api.admin_routes import router as admin_router
from src.api.deps import get_context, get_dispatcher, get_session
from src.auth.context import RequestContext
from src.auth.errors import AuthError
from src.db import AuditEvent, PlanLimits, UsageEvent, engine, init_db
from src.providers.errors import ProviderError
from src.providers.registry import MODEL_PROVIDERS, Dispatcher
from src.quota.errors import QuotaError, RateLimitError
from src.quota.limiter import check_quota
from src.schemas import ChatMessage, ChatRequest, ChatResponse, ModelsOut, UsageOut, UsageReport
from src.usage.service import build_usage_report, record_usage


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(engine)
    yield


app = FastAPI(title="Multi-Tenant LLM API", lifespan=lifespan)
app.include_router(admin_router)


@app.exception_handler(AuthError)
def _handle_auth_error(request: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content={"error": exc.code})


@app.exception_handler(QuotaError)
def _handle_quota_error(request: Request, exc: QuotaError) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimitError) else {}
    return JSONResponse(status_code=exc.http_status, content={"error": exc.code}, headers=headers)


@app.exception_handler(ProviderError)
def _handle_provider_error(request: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content={"error": exc.code})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models", response_model=ModelsOut)
def list_models(
    session: Session = Depends(get_session),
    ctx: RequestContext = Depends(get_context),
) -> ModelsOut:
    limits = session.get(PlanLimits, ctx.tenant_id)
    return ModelsOut(models=limits.allowed_models)


@app.get("/v1/usage", response_model=UsageReport)
def get_usage(
    session: Session = Depends(get_session),
    ctx: RequestContext = Depends(get_context),
) -> UsageReport:
    """This tenant's own usage only -- tenant_id comes from ctx (the
    authenticated key), never from a query param (see docs/TENANCY.md)."""
    return build_usage_report(session, ctx.tenant_id)


@app.post("/v1/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    session: Session = Depends(get_session),
    ctx: RequestContext = Depends(get_context),
    dispatcher: Dispatcher = Depends(get_dispatcher),
) -> ChatResponse:
    limits = session.get(PlanLimits, ctx.tenant_id)

    model = payload.model or limits.allowed_models[0]
    provider = MODEL_PROVIDERS.get(model)

    check_quota(
        session,
        ctx.tenant_id,
        model=model,
        provider=provider,
        estimated_tokens=_estimate_tokens(payload.messages, payload.max_tokens),
        requested_max_tokens=payload.max_tokens,
    )

    raw_messages = [m.model_dump() for m in payload.messages]
    started = time.monotonic()
    try:
        result = dispatcher(provider, model, raw_messages, payload.max_tokens)
    except ProviderError as exc:
        # Caught only to record the failed call (0 tokens -- counts toward
        # rpd, not the token budget) before letting the same exception
        # reach the ProviderError handler below, which builds the response.
        _record(session, ctx, model, provider, started, 0, 0, status="error", error_code=exc.code)
        raise

    event = _record(session, ctx, model, provider, started, result.in_tokens, result.out_tokens, status="ok")

    return ChatResponse(
        request_id=event.id,
        model=model,
        provider=provider,
        message=ChatMessage(role="assistant", content=result.text),
        usage=UsageOut(in_tokens=result.in_tokens, out_tokens=result.out_tokens),
    )


def _estimate_tokens(messages: list[ChatMessage], max_tokens: int | None) -> int:
    """No tokenizer -- ~4 chars/token for the prompt, plus the client's
    requested completion length *if they bounded it*. If they didn't, we
    have no honest upper bound to guess with -- inventing one (e.g. the
    plan's per-request cap) would falsely reject plenty of small requests
    for a tenant with a modest budget who simply never sends max_tokens.
    The actual completion size is what record_usage() writes after the
    call, and an unexpectedly large one is caught by the *next* request's
    check, per docs/LIMITS.md "Accounting order" -- not by a speculative
    estimate here.
    # ponytail: swap for a real tokenizer if the char/4 prompt estimate
    # over/under-shoots enough in practice to matter."""
    prompt_chars = sum(len(m.content) for m in messages)
    return (prompt_chars // 4) + (max_tokens or 0)


def _record(
    session: Session,
    ctx: RequestContext,
    model: str,
    provider: str,
    started: float,
    in_tokens: int,
    out_tokens: int,
    *,
    status: str,
    error_code: str | None = None,
) -> UsageEvent:
    event = record_usage(
        session,
        tenant_id=ctx.tenant_id,
        key_id=ctx.key_id,
        model=model,
        provider=provider,
        in_tokens=in_tokens,
        out_tokens=out_tokens,
        cost_est=0.0,
        latency_ms=int((time.monotonic() - started) * 1000),
        status=status,
        error_code=error_code,
    )
    session.add(
        AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=ctx.tenant_id,
            actor=f"key:{ctx.key_id}",
            action="chat",
            detail=f"model={model} provider={provider} status={status}",
        )
    )
    session.commit()
    return event
