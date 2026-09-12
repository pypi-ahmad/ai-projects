from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from promptreg.api.app import app

ADMIN_TOKEN = "test-admin-token"
ADMIN_HEADERS = {"X-Admin-Token": ADMIN_TOKEN}
STUB_CONFIG = {"model": "stub", "provider": "stub"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("PROMPTREG_DB_PATH", str(tmp_path / "registry.db"))
    monkeypatch.setenv("PROMPTREG_PROMPTS_DIR", str(tmp_path / "prompts"))
    monkeypatch.setenv("PROMPTREG_OUTCOMES_JSONL", str(tmp_path / "outcomes.jsonl"))
    monkeypatch.setenv("PROMPTREG_ADMIN_TOKEN", ADMIN_TOKEN)
    with TestClient(app) as test_client:
        yield test_client


def _publish(client: TestClient, body: str, changelog: str = "v") -> httpx.Response:
    return client.post(
        "/v1/prompts/greeting/versions",
        json={"body": body, "config": STUB_CONFIG, "changelog": changelog, "author": "ada"},
        headers=ADMIN_HEADERS,
    )


def test_publish_requires_admin_token(client: TestClient) -> None:
    resp = client.post(
        "/v1/prompts/greeting/versions",
        json={"body": "hi", "config": STUB_CONFIG, "changelog": "v1", "author": "ada"},
    )
    assert resp.status_code == 401


def test_publish_and_list_versions(client: TestClient) -> None:
    resp = _publish(client, "hi {name}")
    assert resp.status_code == 201
    assert resp.json()["version"] == 1

    resp = client.get("/v1/prompts/greeting/versions")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_pointer_and_rollback(client: TestClient) -> None:
    _publish(client, "v1 body")
    _publish(client, "v2 body")
    client.put("/v1/prompts/greeting/pointer/prod", json={"version": 1}, headers=ADMIN_HEADERS)
    client.put("/v1/prompts/greeting/pointer/prod", json={"version": 2}, headers=ADMIN_HEADERS)

    resp = client.post("/v1/prompts/greeting/rollback/prod", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["version"] == 1


def test_rollback_requires_admin_token(client: TestClient) -> None:
    _publish(client, "v1 body")
    client.put("/v1/prompts/greeting/pointer/prod", json={"version": 1}, headers=ADMIN_HEADERS)
    resp = client.post("/v1/prompts/greeting/rollback/prod")
    assert resp.status_code == 401


def test_resolve_falls_back_to_pointer(client: TestClient) -> None:
    _publish(client, "hi {name}")
    client.put("/v1/prompts/greeting/pointer/prod", json={"version": 1}, headers=ADMIN_HEADERS)

    resp = client.post(
        "/v1/resolve", json={"prompt_name": "greeting", "user_key": "u1", "env": "prod"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == 1
    assert data["arm"] is None
    assert data["body"] == "hi {name}"


def test_complete_renders_dry_and_tracks_outcome(client: TestClient) -> None:
    _publish(client, "Hello, {name}!")
    client.put("/v1/prompts/greeting/pointer/prod", json={"version": 1}, headers=ADMIN_HEADERS)

    resp = client.post(
        "/v1/complete",
        json={
            "prompt_name": "greeting",
            "user_key": "u1",
            "variables": {"name": "Ada"},
            "env": "prod",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rendered"] == "Hello, Ada!"
    assert data["dry"] is True
    request_id = data["request_id"]

    resp = client.post("/v1/outcomes", json={"request_id": request_id, "metrics": {"thumbs": 1}})
    assert resp.status_code == 401

    resp = client.post(
        "/v1/outcomes",
        json={"request_id": request_id, "metrics": {"thumbs": 1, "task_ok": True}},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["metrics"]["thumbs"] == 1


def test_complete_missing_variable_returns_400(client: TestClient) -> None:
    _publish(client, "Hello, {name}!")
    client.put("/v1/prompts/greeting/pointer/prod", json={"version": 1}, headers=ADMIN_HEADERS)

    resp = client.post(
        "/v1/complete",
        json={"prompt_name": "greeting", "user_key": "u1", "variables": {}, "env": "prod"},
    )
    assert resp.status_code == 400


def test_experiment_start_stop_and_resolve(client: TestClient) -> None:
    _publish(client, "control body")
    resp = client.post(
        "/v1/experiments",
        json={
            "name": "tone-test",
            "prompt_name": "greeting",
            "arms": [{"name": "control", "version": 1, "weight": 100}],
        },
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 201
    experiment_id = resp.json()["id"]

    resp = client.post(f"/v1/experiments/{experiment_id}/start", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"

    resp = client.post(
        "/v1/resolve", json={"prompt_name": "greeting", "user_key": "u1", "env": "prod"}
    )
    assert resp.status_code == 200
    assert resp.json()["arm"] == "control"
    assert resp.json()["experiment_id"] == experiment_id

    resp = client.post(f"/v1/experiments/{experiment_id}/stop", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
