"""Demo provider adapters + TracedClient. See docs/ARCHITECTURE.md.

Only Ollama is implemented. Agnes AI, an OpenAI-compatible endpoint, and
Gemini are documented as planned but not built - adding them requires
verifying each SDK's current API before writing client code.
"""

from obs.providers.base import CompletionResult, ProviderAdapter
from obs.providers.client import TracedClient, TracedCompletion, default_adapters
from obs.providers.ollama import OllamaAdapter

__all__ = [
    "CompletionResult",
    "OllamaAdapter",
    "ProviderAdapter",
    "TracedClient",
    "TracedCompletion",
    "default_adapters",
]
