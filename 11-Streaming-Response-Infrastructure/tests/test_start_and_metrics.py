import json

import httpx2 as httpx
from fastapi.testclient import TestClient

from stream.api import _LOG_PATH, _produce, app
from stream.providers.ollama import OllamaAdapter
from stream.session import StreamSession


def test_start_stream_503_for_unknown_provider() -> None:
    with TestClient(app) as client:
        resp = client.post("/v1/stream/start", json={"provider": "nope"})

    assert resp.status_code == 503
    assert resp.json()["error"] == "provider_unavailable"


def test_start_stream_503_for_unverified_provider() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/v1/stream/start",
            json={"provider": "gemini", "model": "gemini-3.5-flash-lite", "messages": []},
        )

    assert resp.status_code == 503


def test_start_stream_503_for_disallowed_model() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/v1/stream/start", json={"provider": "ollama", "model": "not-allowed", "messages": []}
        )

    assert resp.status_code == 503


def test_start_stream_503_when_required_key_missing(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/stream/start",
            json={"provider": "openai_compatible", "model": "gpt-5.6-luna", "messages": []},
        )

    assert resp.status_code == 503
    assert "OPENAI_API_KEY" in resp.json()["detail"]


def test_metrics_endpoint_reports_ttft_tokens_done_reason() -> None:
    with TestClient(app) as client:
        start = client.post("/v1/stream/start")
        session_id = start.json()["session_id"]
        client.get(start.json()["sse_url"])  # run the fake stream to completion

        resp = client.get(f"/v1/metrics/{session_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ttft_ms"] is not None
    assert body["tokens"] == 5
    assert body["done_reason"] == "complete"


def test_metrics_endpoint_404_for_unknown_session() -> None:
    with TestClient(app) as client:
        resp = client.get("/v1/metrics/does-not-exist")

    assert resp.status_code == 404


def test_reconnect_after_done_with_nothing_new_returns_204() -> None:
    with TestClient(app) as client:
        start = client.post("/v1/stream/start")
        sse_url = start.json()["sse_url"]
        full = client.get(sse_url)  # run to completion
        last_id = max(
            int(line.removeprefix("id: "))
            for line in full.text.split("\n")
            if line.startswith("id: ")
        )

        again = client.get(sse_url, headers={"Last-Event-ID": str(last_id)})

    assert again.status_code == 204


def test_streams_log_gets_a_row_with_the_expected_fields() -> None:
    with TestClient(app) as client:
        start = client.post(
            "/v1/stream/start", json={"provider": "fake", "model": "fake", "messages": []}
        )
        session_id = start.json()["session_id"]
        client.get(start.json()["sse_url"])  # run to completion so _produce logs it

    rows = [json.loads(line) for line in _LOG_PATH.read_text(encoding="utf-8").splitlines()]
    row = next(r for r in rows if r["session_id"] == session_id)
    assert row["provider"] == "fake"
    assert row["model"] == "fake"
    assert row["tokens"] == 5
    assert row["ok"] is True
    assert row["dropped"] == 0
    assert row["reconnects"] == 0


async def test_produce_marks_session_failed_on_adapter_error_not_a_hang() -> None:
    session = StreamSession(id="x")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    bad_adapter = OllamaAdapter("m", [], transport=httpx.MockTransport(handler))

    await _produce(session, bad_adapter, "ollama", "m")

    assert session.metrics().done_reason == "provider_error"
