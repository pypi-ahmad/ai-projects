"""FastAPI surface, exercised in-process via TestClient -- no real network,
no server actually bound to 127.0.0.1. /v1/loop is tested with a fake
provider (monkeypatched), same reasoning as test_loop.py: no live LLM
calls in the automated suite.
"""

from fastapi.testclient import TestClient

import tools.api as api_module
from tools.providers import ProviderReply


def _client() -> TestClient:
    return TestClient(api_module.app)


def test_list_tools_returns_builtins():
    resp = _client().get("/v1/tools")

    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    assert names == {"calc", "now", "json_query", "write_note", "read_note"}


def test_call_tool_success():
    resp = _client().post(
        "/v1/call", json={"name": "calc", "args": {"expression": "2+2"}, "run_id": "api-test"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["value"]["value"] == 4.0


def test_call_tool_unknown_name_is_200_not_found_not_500():
    resp = _client().post("/v1/call", json={"name": "nope", "args": {}, "run_id": "api-test"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"


class _FakeProvider:
    def __init__(self, replies):
        self._replies = replies
        self.calls = 0

    def chat(self, _messages, _tools):
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return reply


def test_run_loop_endpoint(monkeypatch):
    def fake_get_provider(_name):
        return _FakeProvider(
            [
                ProviderReply(
                    text=None,
                    native_tool_calls=[{"function": {"name": "calc", "arguments": {"expression": "2+2"}}}],
                ),
                ProviderReply(text="4"),
            ]
        )

    monkeypatch.setattr(api_module, "get_provider", fake_get_provider)

    resp = _client().post("/v1/loop", json={"messages": [{"role": "user", "content": "2+2?"}]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "FINAL"
    assert body["text"] == "4"
