import json

import httpx2 as httpx
import pytest

from stream.providers.gemini import GeminiAdapter
from stream.providers.ollama import OllamaAdapter
from stream.providers.openai_compat import OpenAICompatAdapter


def _ndjson_transport(lines: list[dict]) -> httpx.MockTransport:
    body = ("\n".join(json.dumps(line) for line in lines) + "\n").encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "application/x-ndjson"})

    return httpx.MockTransport(handler)


def _sse_transport(data_lines: list[str]) -> httpx.MockTransport:
    body = "".join(f"data: {line}\n\n" for line in data_lines).encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler)


async def test_ollama_adapter_yields_content_and_final_usage_only() -> None:
    lines = [
        {"message": {"role": "assistant", "content": "pon"}, "done": False},
        {"message": {"role": "assistant", "content": "g"}, "done": False},
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 5,
            "eval_count": 2,
        },
    ]
    adapter = OllamaAdapter(
        "qwen3.5:0.8b", [{"role": "user", "content": "hi"}], transport=_ndjson_transport(lines)
    )
    it = adapter.__aiter__()

    assert await it.__anext__() == "pon"
    assert adapter.usage is None
    assert await it.__anext__() == "g"
    assert adapter.usage is None
    with pytest.raises(StopAsyncIteration):
        await it.__anext__()
    assert adapter.usage == {"prompt_tokens": 5, "completion_tokens": 2}


async def test_openai_compat_adapter_yields_deltas_and_final_usage_only() -> None:
    data_lines = [
        json.dumps({"choices": [{"delta": {"role": "assistant", "content": ""}}]}),
        json.dumps({"choices": [{"delta": {"content": "pong"}}]}),
        json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        json.dumps({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}),
        "[DONE]",
    ]
    adapter = OpenAICompatAdapter(
        "https://example.com/v1",
        "sk-test",
        "gpt-5.6-luna",
        [{"role": "user", "content": "hi"}],
        transport=_sse_transport(data_lines),
    )
    it = adapter.__aiter__()

    assert await it.__anext__() == "pong"
    assert adapter.usage is None
    with pytest.raises(StopAsyncIteration):
        await it.__anext__()
    assert adapter.usage == {"prompt_tokens": 3, "completion_tokens": 1}


def test_gemini_body_translates_messages_and_splits_system_instruction() -> None:
    adapter = GeminiAdapter(
        "gemini-3.5-flash-lite",
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        api_key="test-key",
    )

    body = adapter._body()

    assert body["system_instruction"] == {"parts": [{"text": "be terse"}]}
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "hi"}]},
        {"role": "model", "parts": [{"text": "hello"}]},
    ]


async def test_gemini_adapter_yields_text_and_final_usage_only() -> None:
    objs = [
        {"candidates": [{"content": {"parts": [{"text": "pon"}]}}]},
        {
            "candidates": [{"content": {"parts": [{"text": "g"}]}}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
        },
    ]
    adapter = GeminiAdapter(
        "gemini-3.5-flash-lite",
        [{"role": "user", "content": "hi"}],
        api_key="test-key",
        transport=_sse_transport([json.dumps(o) for o in objs]),
    )
    it = adapter.__aiter__()

    assert await it.__anext__() == "pon"
    assert adapter.usage is None
    assert await it.__anext__() == "g"
    with pytest.raises(StopAsyncIteration):
        await it.__anext__()
    assert adapter.usage == {"promptTokenCount": 3, "candidatesTokenCount": 1}
