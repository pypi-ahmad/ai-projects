"""Provider abstraction: a uniform `complete()` interface over Ollama, Agnes AI,
OpenAI-compatible, and Gemini backends. See base.py for the `Provider` protocol
and registry.py for how a provider name resolves to one.
"""

from src.providers.base import Provider, ProviderConfigError, ProviderSpec
from src.providers.registry import PROVIDERS

__all__ = ["PROVIDERS", "Provider", "ProviderConfigError", "ProviderSpec"]
