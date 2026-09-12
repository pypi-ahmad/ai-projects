"""Provider adapters against mocked HTTP (httpx.MockTransport) — no live
API keys or servers needed. Run: uv run python tests/test_providers.py
"""

import contextlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx

from providers import AgnesProvider, GeminiProvider, OllamaProvider, OpenAICompatibleProvider
from providers.base import ProviderError

SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
MESSAGES = [{"role": "user", "content": "Extract the name: Ada"}]


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def sequenced(*responses):
    """Returns a new response from `responses` on each call, in order."""
    calls: list[httpx.Request] = []
    it = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return next(it)

    handler.calls = calls
    return handler


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content)


@contextlib.contextmanager
def without_env(*names: str):
    """Hide env vars for the duration of the block, regardless of what the
    real machine has set (this dev environment has real OPENAI_API_KEY /
    OPENAI_BASE_URL / GOOGLE_API_KEY configured) — "missing" tests must not
    depend on the ambient environment happening to lack them."""
    with mock.patch.dict(os.environ, {}, clear=False):
        for name in names:
            os.environ.pop(name, None)
        yield


class OllamaProviderTests(unittest.TestCase):
    def route(self, *, version="0.34.0", chat_status=200, chat_body=None, tags=None, sent=None):
        chat_body = chat_body or {"message": {"content": '{"name": "Ada"}'}, "model": "granite4.1:3b"}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/version":
                return httpx.Response(200, json={"version": version})
            if request.url.path == "/api/chat":
                if sent is not None:
                    sent["body"] = body_of(request)
                return httpx.Response(chat_status, json=chat_body)
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": tags or []})
            if request.url.path == "/api/generate":
                return httpx.Response(200, json={"done": True})
            raise AssertionError(f"unexpected path {request.url.path}")

        return handler

    def test_uses_format_when_server_supports_json_schema(self):
        sent = {}
        handler = self.route(version="0.34.0", sent=sent)
        provider = OllamaProvider("granite4.1:3b", client=client_for(handler))

        response = provider.complete(MESSAGES, json_schema=SCHEMA)

        self.assertEqual(response.text, '{"name": "Ada"}')
        self.assertEqual(response.model, "granite4.1:3b")
        self.assertEqual(sent["body"]["format"], SCHEMA)
        self.assertEqual(sent["body"]["messages"], MESSAGES)
        self.assertTrue(provider.supports_json_schema())

    def test_embeds_schema_in_prompt_when_server_is_old(self):
        sent = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/version":
                return httpx.Response(200, json={"version": "0.4.2"})
            if request.url.path == "/api/chat":
                sent["body"] = body_of(request)
                return httpx.Response(200, json={"message": {"content": "{}"}, "model": "granite4.1:3b"})
            raise AssertionError(request.url.path)

        provider = OllamaProvider("granite4.1:3b", client=client_for(handler))
        provider.complete(MESSAGES, json_schema=SCHEMA)

        self.assertFalse(provider.supports_json_schema())
        self.assertNotIn("format", sent["body"])
        self.assertEqual(sent["body"]["messages"][0]["role"], "system")
        self.assertIn(json.dumps(SCHEMA), sent["body"]["messages"][0]["content"])
        self.assertEqual(sent["body"]["messages"][1], MESSAGES[0])

    def test_installed_models_filtered_to_allowlist(self):
        handler = self.route(tags=[{"model": "granite4.1:3b"}, {"model": "not-on-allowlist:1b"}])
        provider = OllamaProvider("granite4.1:3b", client=client_for(handler))

        self.assertEqual(provider.installed_models(), {"granite4.1:3b"})

    def test_unload_sends_keep_alive_zero(self):
        sent = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/generate":
                sent["body"] = body_of(request)
                return httpx.Response(200, json={"done": True})
            raise AssertionError(request.url.path)

        provider = OllamaProvider("granite4.1:3b", client=client_for(handler))
        provider.unload()

        self.assertEqual(sent["body"], {"model": "granite4.1:3b", "keep_alive": 0})

    def test_404_raises_not_found(self):
        handler = self.route(chat_status=404, chat_body={"error": "model not found"})
        provider = OllamaProvider("granite4.1:3b", client=client_for(handler))

        with self.assertRaises(ProviderError) as ctx:
            provider.complete(MESSAGES)
        self.assertEqual(ctx.exception.code, "not_found")

    def test_5xx_then_success_retries_once(self):
        handler = sequenced(
            httpx.Response(500, json={"error": "boom"}),
            httpx.Response(200, json={"message": {"content": "ok"}, "model": "granite4.1:3b"}),
        )
        provider = OllamaProvider("granite4.1:3b", client=client_for(handler))
        provider._supports_json_schema = True  # skip the /api/version call for this test

        response = provider.complete(MESSAGES)

        self.assertEqual(response.text, "ok")
        self.assertEqual(len(handler.calls), 2)

    def test_5xx_twice_raises_http_error(self):
        handler = sequenced(
            httpx.Response(500, json={"error": "boom"}),
            httpx.Response(500, json={"error": "boom again"}),
        )
        provider = OllamaProvider("granite4.1:3b", client=client_for(handler))
        provider._supports_json_schema = True

        with self.assertRaises(ProviderError) as ctx:
            provider.complete(MESSAGES)
        self.assertEqual(ctx.exception.code, "http_error")
        self.assertEqual(len(handler.calls), 2)

    def test_timeout_is_not_retried(self):
        def handler(request: httpx.Request) -> httpx.Response:
            handler.calls += 1
            raise httpx.TimeoutException("timed out", request=request)

        handler.calls = 0
        provider = OllamaProvider("granite4.1:3b", client=client_for(handler))
        provider._supports_json_schema = True

        with self.assertRaises(ProviderError) as ctx:
            provider.complete(MESSAGES)
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertEqual(handler.calls, 1)


class OpenAICompatibleProviderTests(unittest.TestCase):
    def test_missing_api_key_raises_before_any_http(self):
        with without_env("OPENAI_API_KEY"):
            with self.assertRaises(ProviderError) as ctx:
                OpenAICompatibleProvider("gpt-5.6-luna", api_key=None, base_url="https://api.example.com/v1")
        self.assertEqual(ctx.exception.code, "missing_api_key")

    def test_missing_base_url_raises(self):
        with without_env("OPENAI_BASE_URL"):
            with self.assertRaises(ProviderError) as ctx:
                OpenAICompatibleProvider("gpt-5.6-luna", api_key="sk-test", base_url=None)
        self.assertEqual(ctx.exception.code, "missing_base_url")

    def test_complete_sends_response_format_and_reasoning_effort(self):
        sent = {}

        def handler(request: httpx.Request) -> httpx.Response:
            sent["body"] = body_of(request)
            sent["auth"] = request.headers["authorization"]
            return httpx.Response(
                200,
                json={
                    "model": "gpt-5.6-luna",
                    "choices": [{"message": {"content": '{"name": "Ada"}'}}],
                },
            )

        provider = OpenAICompatibleProvider(
            "gpt-5.6-luna",
            api_key="sk-test",
            base_url="https://api.example.com/v1",
            client=client_for(handler),
        )
        response = provider.complete(MESSAGES, json_schema=SCHEMA)

        self.assertEqual(response.text, '{"name": "Ada"}')
        self.assertEqual(sent["auth"], "Bearer sk-test")
        self.assertEqual(sent["body"]["reasoning_effort"], "medium")
        self.assertEqual(sent["body"]["response_format"]["type"], "json_schema")
        self.assertEqual(sent["body"]["response_format"]["json_schema"]["schema"], SCHEMA)

    def test_401_raises_unauthorized(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "invalid key"})

        provider = OpenAICompatibleProvider(
            "gpt-5.6-luna", api_key="bad-key", base_url="https://api.example.com/v1", client=client_for(handler)
        )
        with self.assertRaises(ProviderError) as ctx:
            provider.complete(MESSAGES)
        self.assertEqual(ctx.exception.code, "unauthorized")


class AgnesProviderTests(unittest.TestCase):
    def test_missing_api_key_names_agnes_env_var(self):
        with without_env("AGNES_API_KEY"):
            with self.assertRaises(ProviderError) as ctx:
                AgnesProvider(api_key=None)
        self.assertEqual(ctx.exception.code, "missing_api_key")
        self.assertIn("AGNES_API_KEY", ctx.exception.message)

    def test_always_embeds_schema_never_sends_response_format(self):
        sent = {}

        def handler(request: httpx.Request) -> httpx.Response:
            sent["body"] = body_of(request)
            sent["url"] = str(request.url)
            return httpx.Response(
                200, json={"model": "agnes-2.5-flash", "choices": [{"message": {"content": "{}"}}]}
            )

        provider = AgnesProvider(api_key="agnes-key", client=client_for(handler))
        provider.complete(MESSAGES, json_schema=SCHEMA)

        self.assertTrue(sent["url"].startswith("https://apihub.agnes-ai.com/v1/"))
        self.assertNotIn("response_format", sent["body"])
        self.assertEqual(sent["body"]["messages"][0]["role"], "system")
        self.assertIn(json.dumps(SCHEMA), sent["body"]["messages"][0]["content"])


class GeminiProviderTests(unittest.TestCase):
    def test_missing_api_key_raises(self):
        with without_env("GOOGLE_API_KEY"):
            with self.assertRaises(ProviderError) as ctx:
                GeminiProvider("gemini-3.5-flash-lite", api_key=None)
        self.assertEqual(ctx.exception.code, "missing_api_key")

    def test_complete_maps_roles_and_schema_and_auth(self):
        sent = {}

        def handler(request: httpx.Request) -> httpx.Response:
            sent["body"] = body_of(request)
            sent["key_param"] = request.url.params.get("key")
            sent["path"] = request.url.path
            return httpx.Response(
                200,
                json={
                    "modelVersion": "gemini-3.5-flash-lite",
                    "candidates": [{"content": {"parts": [{"text": '{"name": "Ada"}'}]}}],
                },
            )

        provider = GeminiProvider("gemini-3.5-flash-lite", api_key="gk-test", client=client_for(handler))
        messages = [
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": "Extract the name: Ada"},
            {"role": "assistant", "content": "Sure."},
        ]
        response = provider.complete(messages, json_schema=SCHEMA)

        self.assertEqual(response.text, '{"name": "Ada"}')
        self.assertEqual(sent["key_param"], "gk-test")
        self.assertTrue(sent["path"].endswith(":generateContent"))
        self.assertEqual(sent["body"]["systemInstruction"]["parts"][0]["text"], "Be terse.")
        self.assertEqual([c["role"] for c in sent["body"]["contents"]], ["user", "model"])
        self.assertEqual(sent["body"]["generationConfig"]["responseJsonSchema"], SCHEMA)
        self.assertEqual(sent["body"]["generationConfig"]["responseMimeType"], "application/json")

    def test_unsupported_response_shape_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        provider = GeminiProvider("gemini-3.5-flash-lite", api_key="gk-test", client=client_for(handler))
        with self.assertRaises(ProviderError) as ctx:
            provider.complete(MESSAGES)
        self.assertEqual(ctx.exception.code, "unsupported_response")

    def test_404_raises_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "model not found"})

        provider = GeminiProvider("gemini-3.5-flash-lite", api_key="gk-test", client=client_for(handler))
        with self.assertRaises(ProviderError) as ctx:
            provider.complete(MESSAGES)
        self.assertEqual(ctx.exception.code, "not_found")


if __name__ == "__main__":
    unittest.main()
