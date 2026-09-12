from self_correcting_rag.llm.base import ProviderConfigError
from self_correcting_rag.llm.registry import PROVIDERS


def test_registry_has_four_providers():
    assert set(PROVIDERS) == {"ollama", "agnes", "openai_compatible", "gemini"}


def test_ollama_provider_constructs_without_network():
    # ollama.Client(host=...) does not connect eagerly, so this never needs a
    # running Ollama daemon or a network call.
    provider = PROVIDERS["ollama"].factory()
    assert hasattr(provider, "complete")


def test_keyed_providers_either_construct_or_raise_config_error():
    # These read real env vars, which may or may not be set on the running
    # machine -- either outcome is correct, a crash is not.
    for name in ("agnes", "openai_compatible", "gemini"):
        spec = PROVIDERS[name]
        try:
            provider = spec.factory()
            assert hasattr(provider, "complete")
        except ProviderConfigError:
            pass


def test_default_models_are_in_allowed_models():
    for spec in PROVIDERS.values():
        assert spec.default_model in spec.allowed_models
