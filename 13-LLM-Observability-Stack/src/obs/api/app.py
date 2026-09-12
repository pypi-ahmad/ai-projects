"""FastAPI app. Bind 127.0.0.1 only (see __main__.py).

GET endpoints are always open. POST endpoints require X-Admin-Token only if
OBS_ADMIN_TOKEN is set (see auth.py).

Exporters are registered on startup (lifespan), not at import time, so
importing this module has no filesystem side effects.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from obs.alerts.models import Alert
from obs.alerts.store import ack_alert, get_alert, list_alerts
from obs.api.auth import require_admin_token
from obs.api.schemas import CompleteRequest, CompleteResponse, IngestResponse
from obs.export import get_trace, query, register_default_exporters
from obs.providers import TracedClient
from obs.trace import Tracer, export_trace
from obs.trace.models import Trace


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    register_default_exporters()
    yield


app = FastAPI(title="LLM Observability Stack", lifespan=lifespan)
_client = TracedClient()


@app.post(
    "/v1/demo/complete",
    response_model=CompleteResponse,
    dependencies=[Depends(require_admin_token)],
)
def demo_complete(body: CompleteRequest) -> CompleteResponse:
    messages = [m.model_dump() for m in body.messages]
    # try/except wraps the whole `with Tracer.start(...)` block, not just
    # the .complete() call: __exit__ (and export) must run and complete
    # before this converts the error into an HTTPException, so the failed
    # request is still recorded even though the client sees a 502.
    try:
        with Tracer.start("request") as root:
            root.set_trace(route="/v1/demo/complete")
            result = _client.complete(messages, body.provider, body.model)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return CompleteResponse(
        text=result.text,
        trace_id=result.trace_id,
        in_tokens=result.in_tokens,
        out_tokens=result.out_tokens,
        ttft_ms=result.ttft_ms,
    )


@app.get("/v1/traces/{trace_id}", response_model=Trace)
def get_trace_endpoint(trace_id: str) -> Trace:
    trace = get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace


@app.get("/v1/traces")
def list_traces_endpoint(
    route: Annotated[str | None, Query()] = None,
    model: Annotated[str | None, Query()] = None,
    since: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
) -> list[dict]:
    return query(route=route, model=model, since=since, status=status)


@app.get("/v1/alerts", response_model=list[Alert])
def list_alerts_endpoint() -> list[Alert]:
    return list_alerts()


@app.post(
    "/v1/alerts/{alert_id}/ack",
    response_model=Alert,
    dependencies=[Depends(require_admin_token)],
)
def ack_alert_endpoint(alert_id: str) -> Alert:
    if get_alert(alert_id) is None:
        raise HTTPException(status_code=404, detail="alert not found")
    ack_alert(alert_id)
    updated = get_alert(alert_id)
    if updated is None:  # pragma: no cover - can't happen, just acked it
        raise HTTPException(status_code=404, detail="alert not found")
    return updated


@app.post(
    "/v1/ingest",
    response_model=IngestResponse,
    dependencies=[Depends(require_admin_token)],
)
def ingest_endpoint(trace: Trace) -> IngestResponse:
    """Accept a prebuilt Trace JSON so other repos can ship traces here."""
    # Check-then-insert, not atomic - fine for a single-process local tool
    # with no concurrent writers expected, but two simultaneous ingests of
    # the same trace_id could both pass this check before either inserts.
    if get_trace(trace.trace_id) is not None:
        raise HTTPException(status_code=409, detail="trace_id already exists")
    export_trace(trace)
    return IngestResponse(trace_id=trace.trace_id, spans=len(trace.spans))
