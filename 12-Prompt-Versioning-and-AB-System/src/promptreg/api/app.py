"""FastAPI app — bind 127.0.0.1 only (see `__main__.py`).

Write routes (publish, pointer, rollback, experiment create/start/stop,
outcome track) require `X-Admin-Token`. `resolve`, `complete`, and the
version list (a read) are open — fine for a localhost-only deployment.

Storage paths and the admin token come from env vars, read once at
startup (`lifespan`), so tests can point each run at its own tmp dir:
`PROMPTREG_DB_PATH`, `PROMPTREG_PROMPTS_DIR`, `PROMPTREG_OUTCOMES_JSONL`,
`PROMPTREG_ADMIN_TOKEN` (generated and printed once if unset).
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from promptreg.api.schemas import (
    CompleteRequest,
    CompleteResponse,
    CreateExperimentRequest,
    PublishVersionRequest,
    ResolveRequest,
    ResolveResponse,
    SetPointerRequest,
    TrackRequest,
)
from promptreg.execute.completer import execute
from promptreg.execute.render import TemplateRenderError, render
from promptreg.outcomes.models import OutcomeEvent
from promptreg.outcomes.storage import OutcomeStore
from promptreg.registry.models import Env, Pointer, Version
from promptreg.registry.storage import IntegrityError, Registry
from promptreg.split.models import Experiment
from promptreg.split.storage import ExperimentStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_path = os.environ.get("PROMPTREG_DB_PATH", "data/registry.db")
    prompts_dir = os.environ.get("PROMPTREG_PROMPTS_DIR", "data/prompts")
    outcomes_jsonl = os.environ.get("PROMPTREG_OUTCOMES_JSONL", "data/outcomes.jsonl")

    app.state.registry = Registry(db_path, prompts_dir)
    app.state.experiments = ExperimentStore(db_path)
    app.state.outcomes = OutcomeStore(db_path, outcomes_jsonl)

    configured_token = os.environ.get("PROMPTREG_ADMIN_TOKEN")
    app.state.admin_token = configured_token or secrets.token_urlsafe(24)
    if not configured_token:
        print(  # noqa: T201 -- the whole point is telling the operator this run's token
            f"No PROMPTREG_ADMIN_TOKEN set - generated admin token for this run: "
            f"{app.state.admin_token}"
        )
    yield


app = FastAPI(title="promptreg", lifespan=lifespan)


def get_registry(request: Request) -> Registry:
    return request.app.state.registry


def get_experiments(request: Request) -> ExperimentStore:
    return request.app.state.experiments


def get_outcomes(request: Request) -> OutcomeStore:
    return request.app.state.outcomes


async def require_admin_token(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    if x_admin_token != request.app.state.admin_token:
        raise HTTPException(status_code=401, detail="missing or invalid X-Admin-Token")


AdminDep = Depends(require_admin_token)
RegistryDep = Annotated[Registry, Depends(get_registry)]
ExperimentsDep = Annotated[ExperimentStore, Depends(get_experiments)]
OutcomesDep = Annotated[OutcomeStore, Depends(get_outcomes)]


@app.exception_handler(KeyError)
async def _key_error_handler(_request: Request, exc: KeyError) -> JSONResponse:
    detail = exc.args[0] if exc.args else "not found"
    return JSONResponse(status_code=404, content={"detail": detail})


@app.exception_handler(ValueError)
async def _value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
async def _integrity_error_handler(_request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.exception_handler(TemplateRenderError)
async def _render_error_handler(_request: Request, exc: TemplateRenderError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.post(
    "/v1/prompts/{name}/versions", response_model=Version, status_code=201, dependencies=[AdminDep]
)
def publish_version(name: str, req: PublishVersionRequest, registry: RegistryDep) -> Version:
    return registry.publish(
        name,
        req.body,
        req.config,
        req.changelog,
        req.author,
        description=req.description,
        label=req.label,
    )


@app.get("/v1/prompts/{name}/versions", response_model=list[Version])
def list_versions(name: str, registry: RegistryDep) -> list[Version]:
    return registry.list_versions(name)


@app.put("/v1/prompts/{name}/pointer/{env}", response_model=Pointer, dependencies=[AdminDep])
def set_pointer(name: str, env: Env, req: SetPointerRequest, registry: RegistryDep) -> Pointer:
    return registry.set_pointer(name, env, req.version)


@app.post("/v1/prompts/{name}/rollback/{env}", response_model=Pointer, dependencies=[AdminDep])
def rollback(name: str, env: Env, registry: RegistryDep) -> Pointer:
    return registry.rollback(name, env)


@app.post("/v1/experiments", response_model=Experiment, status_code=201, dependencies=[AdminDep])
def create_experiment(req: CreateExperimentRequest, experiments: ExperimentsDep) -> Experiment:
    return experiments.create_experiment(
        req.name,
        req.prompt_name,
        req.arms,
        sticky_salt=req.sticky_salt,
        start_at=req.start_at,
        end_at=req.end_at,
    )


@app.post(
    "/v1/experiments/{experiment_id}/start", response_model=Experiment, dependencies=[AdminDep]
)
def start_experiment(experiment_id: int, experiments: ExperimentsDep) -> Experiment:
    return experiments.set_status(experiment_id, "running")


@app.post(
    "/v1/experiments/{experiment_id}/stop", response_model=Experiment, dependencies=[AdminDep]
)
def stop_experiment(experiment_id: int, experiments: ExperimentsDep) -> Experiment:
    return experiments.set_status(experiment_id, "stopped")


@app.post("/v1/resolve", response_model=ResolveResponse)
def resolve(
    req: ResolveRequest, registry: RegistryDep, experiments: ExperimentsDep
) -> ResolveResponse:
    resolution = experiments.resolve(registry, req.prompt_name, req.user_key, req.env)
    version = registry.get(req.prompt_name, resolution.version)
    return ResolveResponse(
        version=resolution.version,
        arm=resolution.arm,
        experiment_id=resolution.experiment_id,
        reason=resolution.reason,
        body=version.body or "",
        config=version.config,
    )


@app.post("/v1/complete", response_model=CompleteResponse)
def complete(
    req: CompleteRequest, registry: RegistryDep, experiments: ExperimentsDep, outcomes: OutcomesDep
) -> CompleteResponse:
    resolution = experiments.resolve(registry, req.prompt_name, req.user_key, req.env)
    version = registry.get(req.prompt_name, resolution.version)
    rendered = render(version.body or "", req.variables)
    result = execute(rendered, version.config)
    event = outcomes.record(
        req.user_key,
        req.prompt_name,
        resolution.version,
        resolution.arm,
        resolution.experiment_id,
        result,
    )
    return CompleteResponse(
        request_id=event.request_id,
        version=resolution.version,
        arm=resolution.arm,
        experiment_id=resolution.experiment_id,
        reason=resolution.reason,
        rendered=rendered,
        dry=result.dry,
        output=result.output,
        ok=result.ok,
        latency_ms=result.latency_ms,
    )


@app.post("/v1/outcomes", response_model=OutcomeEvent, dependencies=[AdminDep])
def track_outcome(req: TrackRequest, outcomes: OutcomesDep) -> OutcomeEvent:
    return outcomes.track(req.request_id, req.metrics)
