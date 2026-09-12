"""FastAPI HTTP surface: GET /v1/tools, POST /v1/call, POST /v1/loop.

Binds to 127.0.0.1 only (see run.cmd) -- a local dev/demo surface for the
Streamlit UI, not meant to be reachable over the network.

Run: `python -m uvicorn src.tools.api:app --host 127.0.0.1 --port 8765`
(from the project root; see run.cmd).

Next: ui.py, the only client of this API in this repo.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from .builtins import register_builtins
from .loop import run as loop_run
from .parse import ToolCall
from .providers import get_provider
from .registry import Registry
from .sandbox import execute_with_retry

app = FastAPI(title="Tool-Calling Framework API")

# One Registry, shared by every request for the life of the process --
# populated once at import time, never mutated per-request (see
# Registry's own docstring for why that's safe without locking).
_registry = Registry()
register_builtins(_registry)


class CallRequest(BaseModel):
    name: str
    args: dict[str, Any]
    run_id: str


class LoopRequest(BaseModel):
    messages: list[dict[str, Any]]
    run_id: str | None = None
    max_tool_iters: int = 4
    provider: str = "ollama"


@app.get("/v1/tools")
def list_tools() -> list[dict[str, Any]]:
    """Generic {name, description, parameters} view -- see Registry.list_schemas."""
    return _registry.list_schemas()


@app.post("/v1/call")
def call_tool(req: CallRequest) -> dict[str, Any]:
    """One manual call, bypassing the model entirely. Never raises -- see sandbox.execute."""
    result = execute_with_retry(_registry, ToolCall(tool=req.name, args=req.args), run_id=req.run_id)
    return result.model_dump()


@app.post("/v1/loop")
def run_loop(req: LoopRequest) -> dict[str, Any]:
    provider = get_provider(req.provider)
    return loop_run(
        req.messages,
        registry=_registry,
        provider=provider,
        run_id=req.run_id,
        max_tool_iters=req.max_tool_iters,
    )
