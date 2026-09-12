"""Thin HTTP client for the Streamlit UI to call the FastAPI backend.

Real HTTP, not a Python import of obs.api/obs.export - run.cmd starts the
API and the UI as two separate processes, so this is the only way across.
Base URL: OBS_API_BASE_URL env var, default http://127.0.0.1:8000. Write
calls attach X-Admin-Token automatically if OBS_ADMIN_TOKEN is set, so the
UI keeps working once an admin token is configured. Next file to read:
app.py (the only caller).
"""

from __future__ import annotations

import os
from typing import Any

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TIMEOUT_S = 10
DEMO_TIMEOUT_S = 120  # a live Ollama call can take a while


def _base_url() -> str:
    return os.environ.get("OBS_API_BASE_URL", DEFAULT_BASE_URL)


def _write_headers() -> dict[str, str]:
    token = os.environ.get("OBS_ADMIN_TOKEN")
    return {"X-Admin-Token": token} if token else {}


def get_trace(trace_id: str) -> dict[str, Any] | None:
    resp = requests.get(f"{_base_url()}/v1/traces/{trace_id}", timeout=TIMEOUT_S)
    if resp.status_code == requests.codes.not_found:
        return None
    resp.raise_for_status()
    return resp.json()


def list_traces(
    *,
    model: str | None = None,
    since: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    params = {k: v for k, v in {"model": model, "since": since, "status": status}.items() if v}
    resp = requests.get(f"{_base_url()}/v1/traces", params=params, timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def list_alerts() -> list[dict[str, Any]]:
    resp = requests.get(f"{_base_url()}/v1/alerts", timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def ack_alert(alert_id: str) -> dict[str, Any]:
    resp = requests.post(
        f"{_base_url()}/v1/alerts/{alert_id}/ack", headers=_write_headers(), timeout=TIMEOUT_S
    )
    resp.raise_for_status()
    return resp.json()


def demo_complete(messages: list[dict[str, str]], *, provider: str, model: str) -> dict[str, Any]:
    resp = requests.post(
        f"{_base_url()}/v1/demo/complete",
        json={"messages": messages, "provider": provider, "model": model},
        headers=_write_headers(),
        timeout=DEMO_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()
