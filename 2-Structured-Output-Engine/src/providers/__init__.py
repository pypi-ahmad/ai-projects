"""Public surface of the providers package. Every adapter implements the
`Provider` protocol defined in base.py — read that file first for the
shared `complete()`/`ProviderError` contract before an individual adapter."""

from .agnes_provider import AgnesProvider
from .base import Provider, ProviderError, ProviderResponse
from .gemini_provider import GeminiProvider
from .ollama_provider import OllamaProvider
from .openai_compatible import OpenAICompatibleProvider

__all__ = [
    "Provider",
    "ProviderResponse",
    "ProviderError",
    "OllamaProvider",
    "AgnesProvider",
    "OpenAICompatibleProvider",
    "GeminiProvider",
]
