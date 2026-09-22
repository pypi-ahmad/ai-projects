"""Tests for src.llm's `_invoke_structured` diagnostic mapping and the
secret-redaction guarantees in src/diagnostics.py's allowlist. Exercises
success, refusal, content-filter, HTTP-error, and transport-error paths
through a mocked OpenAI HTTP transport (`httpx.MockTransport`), asserting
that provider text/headers/secrets never leak into a `PageDiagnostic` or a
raised `ExtractionCallError`.

Next: src/llm.py's `_invoke_structured`.
"""

import json
from types import SimpleNamespace

import httpx
from openai import OpenAI
import pytest

from src import usage
from src.diagnostics import ExtractionCallError, PageDiagnostic
from src.llm import _image_message, _invoke_structured
from src.layout import ParsePage, ParseResult


def call_response(body, *, status=200, headers=None, transport_error=False):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        if transport_error:
            raise httpx.ReadTimeout("private document and credentials", request=request)
        return httpx.Response(status, json=body, headers=headers or {"x-request-id": "req-123"})

    client = OpenAI(api_key="test-not-a-real-key", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    llm = SimpleNamespace(root_client=client, model_name="gpt-6-sol", reasoning_effort="medium")
    return llm, requests


def completion(finish="stop", content=None, refusal=None):
    return {"id": "test", "object": "chat.completion", "created": 1, "model": "gpt-6-sol",
            "choices": [{"index": 0, "finish_reason": finish, "message": {
                "role": "assistant", "content": content if content is not None else json.dumps({
                    "page": 1, "width_px": 100, "height_px": 200, "blocks": []}), "refusal": refusal}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
                      "prompt_tokens_details": {"cached_tokens": 30, "cache_write_tokens": 20}}}


def invoke(llm, diagnostics, entries=None):
    return _invoke_structured(llm, ParsePage, [_image_message("prompt", "TEST", "image/png")],
                              call_name="test", diagnostics=diagnostics, usage_entries=entries)


def test_live_evaluator_disables_retries_on_actual_client(monkeypatch):
    from scripts import evaluate_prompts

    llm, requests = call_response({"error": {"message": "private", "type": "rate_limit"}}, status=429)
    llm.root_client = llm.root_client.with_options(max_retries=2)
    monkeypatch.setattr(evaluate_prompts, "_build_llm", lambda: llm)
    try:
        outcome = evaluate_prompts.run_page(dict(page=1, doc_sha256="test", width=100,
                                                height=100, base64="TEST", mime="image/png"), "prompt")
    finally:
        llm.root_client.close()
    assert llm.root_client.max_retries == 0
    assert len(requests) == 1
    assert outcome["status"] == "http_error"
    assert outcome["diagnostics"]["http_status"] == 429


def test_sol_pricing_keeps_requested_model_when_provider_returns_alias():
    body = completion()
    body["model"] = "provider-alias"
    llm, requests = call_response(body)
    diagnostics, entries = [], []
    try:
        invoke(llm, diagnostics, entries)
    finally:
        llm.root_client.close()
    assert requests[0]["model"] == "gpt-6-sol"
    assert diagnostics[0].requested_model == "gpt-6-sol"
    assert diagnostics[0].model == "provider-alias"
    assert entries[0]["model"] == "gpt-6-sol"
    assert usage.session_cost_usd(entries) == pytest.approx(0.000356)


def test_create_retains_strict_schema_messages_settings_and_usage():
    llm, requests = call_response(completion())
    diagnostics, entries = [], []
    try:
        page = invoke(llm, diagnostics, entries)
    finally:
        llm.root_client.close()
    assert page.page == 1
    assert len(requests) == 1
    request = requests[0]
    assert "temperature" not in request and request["reasoning_effort"] == "medium"
    assert request["messages"][0]["content"][1]["image_url"]["url"] == "data:image/png;base64,TEST"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["response_format"]["json_schema"]["schema"] == ParsePage.model_json_schema()
    assert diagnostics[0].request_id == "req-123"
    assert diagnostics[0].outcome == "parsed"
    assert usage.totals(entries) == {
        "input_tokens": 100, "output_tokens": 20,
        "cached_tokens": 30, "cache_write_tokens": 20,
    }
    assert diagnostics[0].cache_write_tokens == 20


@pytest.mark.parametrize("finish,content,refusal,expected", [
    ("content_filter", None, None, "content_filtered"),
    ("stop", None, "private refusal text", "refused"),
    ("length", None, None, "incomplete"),
    ("tool_calls", None, None, "incomplete"),
    ("stop", "private invalid JSON", None, "invalid_response"),
    ("stop", '{"private_field":"private value"}', None, "invalid_response"),
])
def test_unsuccessful_output_never_becomes_valid_extraction(finish, content, refusal, expected):
    llm, requests = call_response(completion(finish, content, refusal))
    diagnostics, entries = [], []
    try:
        with pytest.raises(ExtractionCallError) as error:
            invoke(llm, diagnostics, entries)
    finally:
        llm.root_client.close()
    assert len(requests) == 1
    assert diagnostics[0].outcome == expected
    assert "private" not in str(error.value) + diagnostics[0].model_dump_json()
    assert usage.totals(entries)["input_tokens"] == 100


@pytest.mark.parametrize("status,code,expected", [(400,"content_filter","content_filtered"),
    (400,"invalid_schema","http_error"), (401,"invalid_api_key","http_error"), (429,"rate_limit","http_error")])
def test_http_errors_are_safe_and_not_retried(status, code, expected):
    body = {"error": {"code": code, "message": "private secret", "inner_error": {
        "content_filter_results": {"sexual": {"filtered": code == "content_filter", "severity": "high", "text": "private"}}}}}
    llm, requests = call_response(body, status=status)
    diagnostics, entries = [], []
    try:
        with pytest.raises(ExtractionCallError):
            invoke(llm, diagnostics, entries)
    finally:
        llm.root_client.close()
    d = diagnostics[0]
    assert len(requests) == 1 and d.outcome == expected
    assert d.http_status == status and not d.usage_known
    assert "private" not in d.model_dump_json()


def test_metadata_allowlist_removes_secret_values_snippets_and_arbitrary_headers(monkeypatch):
    monkeypatch.setenv("TEST_DIAGNOSTIC_SECRET", "private-secret-value")
    body = completion("content_filter")
    body["model"] = "private-secret-value"
    body["choices"][0]["content_filter_results"] = {
        "sexual": {"filtered": True, "severity": "high", "text": "private page content"},
        "private category": {"filtered": True},
        "hate": {"severity": "private details"},
    }
    body["prompt_filter_results"] = [{"content_filter_results": {"violence": {"filtered": False,"severity":"safe"}}}]
    llm, _ = call_response(body, headers={"x-request-id": "private-secret-value", "authorization": "private"})
    diagnostics, entries = [], []
    try:
        with pytest.raises(ExtractionCallError):
            invoke(llm, diagnostics, entries)
    finally:
        llm.root_client.close()
    d = diagnostics[0]
    assert d.model is None and d.request_id is None
    assert [f.category for f in d.filters] == ["violence", "sexual"]
    assert "private" not in d.model_dump_json()


def test_timeout_is_safe_and_missing_usage_stays_unknown():
    llm, requests = call_response({}, transport_error=True)
    diagnostics, entries = [], []
    try:
        with pytest.raises(ExtractionCallError) as error:
            invoke(llm, diagnostics, entries)
    finally:
        llm.root_client.close()
    assert diagnostics[0].outcome == "transport_error" and len(requests) == 1
    assert not entries[0]["usage_known"]
    assert "private" not in str(error.value)


def test_missing_annotations_and_usage_and_old_result_compatibility():
    body = completion("content_filter")
    body.pop("usage")
    llm, _ = call_response(body)
    diagnostics, entries = [], []
    try:
        with pytest.raises(ExtractionCallError):
            invoke(llm, diagnostics, entries)
    finally:
        llm.root_client.close()
    assert not diagnostics[0].usage_known and diagnostics[0].filters == []
    assert ParseResult.model_validate({"doc_sha": "old", "pages": []}).page_diagnostics == []


def test_resolution_evaluator_sends_actual_output_cap_and_medium_reasoning(monkeypatch):
    from scripts import evaluate_prompts
    llm, requests = call_response(completion())
    llm.reasoning_effort = "high"
    monkeypatch.setattr(evaluate_prompts, "_build_llm", lambda: llm)
    try:
        result = evaluate_prompts.run_page(dict(page=1, doc_sha256="test", width=100, height=100,
                                                base64="TEST", mime="image/png"), "prompt",
                                           max_completion_tokens=8192, reasoning_effort="medium")
    finally:
        llm.root_client.close()
    assert result["status"] == "parsed" and len(requests) == 1
    assert requests[0]["max_completion_tokens"] == 8192
    assert requests[0]["reasoning_effort"] == "medium"
    assert llm.root_client.max_retries == 0


def test_raw_client_cannot_bypass_single_model_guard():
    from src.llm import ExtractConfigError
    llm, requests = call_response(completion())
    llm.model_name = "other-model"
    try:
        with pytest.raises(ExtractConfigError, match="Unsupported model"):
            invoke(llm, [])
    finally:
        llm.root_client.close()
    assert requests == []
