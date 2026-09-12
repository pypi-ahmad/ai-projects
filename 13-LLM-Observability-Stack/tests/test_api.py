import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import obs.api.app as app_module
from obs.alerts.models import Alert
from obs.alerts.store import save_alert
from obs.export.sqlite import DEFAULT_DB_PATH
from obs.metrics import clear_prices_cache
from obs.providers.base import CompletionResult
from obs.providers.client import TracedClient
from obs.trace import tracer as tracer_module
from obs.trace.models import Span, SpanContext, Trace


def _external_trace(*, route: str = "/external") -> Trace:
    """A Trace built directly from the models, as an unrelated repo would
    send it - never touches the local Tracer/exporter pipeline."""
    trace_id = uuid.uuid4().hex
    span = Span(
        ctx=SpanContext(trace_id=trace_id, span_id=uuid.uuid4().hex, parent_id=None),
        name="request",
        kind="internal",
        ts="2026-01-01T00:00:00+00:00",
        start_ns=0,
        end_ns=1_000_000,
        latency_ms=1.0,
        status="ok",
    )
    return Trace(trace_id=trace_id, spans=[span], attrs={"route": route})


class _FakeAdapter:
    def complete(self, messages: list[dict], model: str) -> CompletionResult:  # noqa: ARG002
        return CompletionResult(text="hello from fake", in_tokens=3, out_tokens=4, ttft_ms=1.0)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # chdir isolates data/obs.db and config/*.yaml without needing app.py to
    # expose a db_path override: DEFAULT_DB_PATH etc. are relative Path
    # objects resolved against cwd at each sqlite3.connect()/open() call,
    # not at the time those defaults were bound (import time) - so changing
    # cwd here redirects every later filesystem access in this test.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tracer_module, "_exporters", [])
    monkeypatch.setattr(app_module, "_client", TracedClient({"fake": _FakeAdapter()}))
    monkeypatch.delenv("OBS_ADMIN_TOKEN", raising=False)
    # chdir'ing away from the project root means config/prices.yaml won't be
    # found here - clear the cache on both sides so it doesn't leak a stale
    # (empty) price table into tests that run after these in the same process.
    clear_prices_cache()
    yield
    clear_prices_cache()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app_module.app) as c:
        yield c


def test_demo_complete_creates_a_queryable_trace(client: TestClient) -> None:
    resp = client.post(
        "/v1/demo/complete",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "provider": "fake",
            "model": "fake-model",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "hello from fake"
    assert body["in_tokens"] == 3
    trace_id = body["trace_id"]

    got = client.get(f"/v1/traces/{trace_id}")
    assert got.status_code == 200
    assert got.json()["trace_id"] == trace_id

    listed = client.get("/v1/traces", params={"model": "fake-model"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_get_trace_missing_is_404(client: TestClient) -> None:
    resp = client.get("/v1/traces/does-not-exist")
    assert resp.status_code == 404


def test_ingest_prebuilt_trace(client: TestClient) -> None:
    trace = _external_trace()

    resp = client.post("/v1/ingest", json=trace.model_dump())
    assert resp.status_code == 200
    assert resp.json() == {"trace_id": trace.trace_id, "spans": 1}

    got = client.get(f"/v1/traces/{trace.trace_id}")
    assert got.status_code == 200


def test_ingest_duplicate_trace_id_is_conflict(client: TestClient) -> None:
    payload = _external_trace().model_dump()

    first = client.post("/v1/ingest", json=payload)
    assert first.status_code == 200
    second = client.post("/v1/ingest", json=payload)
    assert second.status_code == 409


def test_alerts_list_and_ack(client: TestClient) -> None:
    alert = Alert(
        rule="error_rate",
        severity="critical",
        route="/chat",
        model="m1",
        window="last_10",
        value=0.6,
        threshold=0.2,
        trace_ids=["t1"],
    )
    save_alert(alert, db_path=DEFAULT_DB_PATH)

    listed = client.get("/v1/alerts")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["acked"] is False

    acked = client.post(f"/v1/alerts/{alert.id}/ack")
    assert acked.status_code == 200
    assert acked.json()["acked"] is True


def test_ack_missing_alert_is_404(client: TestClient) -> None:
    resp = client.post("/v1/alerts/does-not-exist/ack")
    assert resp.status_code == 404


def test_write_endpoints_require_admin_token_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OBS_ADMIN_TOKEN", "secret")

    no_token = client.post(
        "/v1/demo/complete",
        json={"messages": [{"role": "user", "content": "hi"}], "provider": "fake", "model": "m"},
    )
    assert no_token.status_code == 401

    wrong_token = client.post(
        "/v1/demo/complete",
        json={"messages": [{"role": "user", "content": "hi"}], "provider": "fake", "model": "m"},
        headers={"X-Admin-Token": "wrong"},
    )
    assert wrong_token.status_code == 401

    right_token = client.post(
        "/v1/demo/complete",
        json={"messages": [{"role": "user", "content": "hi"}], "provider": "fake", "model": "m"},
        headers={"X-Admin-Token": "secret"},
    )
    assert right_token.status_code == 200

    # reads stay open even with a token configured
    assert client.get("/v1/alerts").status_code == 200
