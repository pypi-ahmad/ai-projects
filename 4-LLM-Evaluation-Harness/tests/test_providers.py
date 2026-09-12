from types import SimpleNamespace

import ollama
import openai
import pytest
from google.genai import errors as genai_errors

from src.providers import agnes_provider, gemini_provider, ollama_provider, openai_provider
from src.providers import retry as retry_module
from src.providers.base import ProviderConfigError
from src.providers.openai_compat_client import is_5xx as openai_is_5xx


def test_ollama_is_5xx():
    assert ollama_provider.is_5xx(ollama.ResponseError("boom", 500))
    assert not ollama_provider.is_5xx(ollama.ResponseError("bad request", 404))
    assert not ollama_provider.is_5xx(ValueError("unrelated"))


def test_openai_compat_is_5xx():
    server_error = openai.APIStatusError.__new__(openai.APIStatusError)
    server_error.status_code = 500
    client_error = openai.APIStatusError.__new__(openai.APIStatusError)
    client_error.status_code = 400

    assert openai_is_5xx(server_error)
    assert not openai_is_5xx(client_error)
    assert not openai_is_5xx(ValueError("unrelated"))


def test_gemini_is_5xx():
    assert gemini_provider.is_5xx(genai_errors.ServerError(500, {}))
    assert not gemini_provider.is_5xx(genai_errors.ClientError(400, {}))
    assert not gemini_provider.is_5xx(ValueError("unrelated"))


def test_agnes_missing_key_raises_typed_error(monkeypatch):
    monkeypatch.setattr(
        agnes_provider, "load_settings", lambda: SimpleNamespace(agnes_api_key=None)
    )
    with pytest.raises(ProviderConfigError):
        agnes_provider.make_provider()


def test_openai_missing_key_raises_typed_error(monkeypatch):
    monkeypatch.setattr(
        openai_provider,
        "load_settings",
        lambda: SimpleNamespace(openai_api_key=None, openai_base_url=None),
    )
    with pytest.raises(ProviderConfigError):
        openai_provider.make_provider()


def test_gemini_missing_key_raises_typed_error(monkeypatch):
    monkeypatch.setattr(
        gemini_provider, "load_settings", lambda: SimpleNamespace(google_api_key=None)
    )
    with pytest.raises(ProviderConfigError):
        gemini_provider.make_provider()


class _RecordingOllamaClient:
    def __init__(self, host=None):
        self.received = None

    def chat(self, *, model, messages, think=None):
        self.received = messages
        self.received_think = think
        return SimpleNamespace(message=SimpleNamespace(content="ok"))


def test_ollama_provider_omits_system_message_when_absent(monkeypatch):
    monkeypatch.setattr(ollama_provider.ollama, "Client", _RecordingOllamaClient)
    provider = ollama_provider.OllamaProvider()

    provider.complete(system=None, user="hi", model="granite4.1:3b")

    assert provider._client.received == [{"role": "user", "content": "hi"}]


def test_ollama_provider_includes_system_message_when_present(monkeypatch):
    monkeypatch.setattr(ollama_provider.ollama, "Client", _RecordingOllamaClient)
    provider = ollama_provider.OllamaProvider()

    provider.complete(system="be nice", user="hi", model="granite4.1:3b")

    assert provider._client.received[0] == {"role": "system", "content": "be nice"}


class _FlakyOllamaClient:
    def __init__(self, host=None):
        self.calls = 0

    def chat(self, *, model, messages, think=None):
        self.calls += 1
        if self.calls <= 2:
            raise ollama.ResponseError("server error", 500)
        return SimpleNamespace(message=SimpleNamespace(content="ok"))


def test_ollama_provider_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr(ollama_provider.ollama, "Client", _FlakyOllamaClient)
    monkeypatch.setattr(retry_module.time, "sleep", lambda _: None)
    provider = ollama_provider.OllamaProvider()

    text = provider.complete(system=None, user="hi", model="granite4.1:3b")

    assert text == "ok"
    assert provider._client.calls == 3


class _AlwaysNotFoundOllamaClient:
    def __init__(self, host=None):
        self.calls = 0

    def chat(self, *, model, messages, think=None):
        self.calls += 1
        raise ollama.ResponseError("not found", 404)


def test_ollama_provider_raises_immediately_on_non_5xx(monkeypatch):
    monkeypatch.setattr(ollama_provider.ollama, "Client", _AlwaysNotFoundOllamaClient)
    provider = ollama_provider.OllamaProvider()

    with pytest.raises(ollama.ResponseError):
        provider.complete(system=None, user="hi", model="granite4.1:3b")

    assert provider._client.calls == 1


def test_ollama_provider_passes_think_through_to_client(monkeypatch):
    monkeypatch.setattr(ollama_provider.ollama, "Client", _RecordingOllamaClient)
    provider = ollama_provider.OllamaProvider()

    provider.complete(system=None, user="hi", model="granite4.1:3b", think=False)

    assert provider._client.received_think is False


class _UnloadRecordingClient:
    def __init__(self, host=None):
        self.generate_calls: list[dict] = []
        self.should_fail = False

    def generate(self, *, model, prompt, keep_alive):
        if self.should_fail:
            raise RuntimeError("connection refused")
        self.generate_calls.append({"model": model, "prompt": prompt, "keep_alive": keep_alive})


def test_ollama_provider_unload_calls_generate_with_keep_alive_zero(monkeypatch):
    monkeypatch.setattr(ollama_provider.ollama, "Client", _UnloadRecordingClient)
    provider = ollama_provider.OllamaProvider()

    provider.unload("granite4.1:3b")

    assert provider._client.generate_calls == [
        {"model": "granite4.1:3b", "prompt": "", "keep_alive": 0}
    ]


def test_ollama_provider_unload_is_best_effort(monkeypatch):
    monkeypatch.setattr(ollama_provider.ollama, "Client", _UnloadRecordingClient)
    provider = ollama_provider.OllamaProvider()
    provider._client.should_fail = True

    provider.unload("granite4.1:3b")  # must not raise
