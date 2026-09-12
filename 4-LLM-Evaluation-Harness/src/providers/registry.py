"""Provider name -> ProviderSpec, so callers (CLI, runner, later Streamlit)
can enumerate and select providers uniformly.
"""

from src.providers import agnes_provider, gemini_provider, ollama_provider, openai_provider
from src.providers.base import ProviderSpec

PROVIDERS: dict[str, ProviderSpec] = {
    "ollama": ollama_provider.SPEC,
    "agnes": agnes_provider.SPEC,
    "openai_compatible": openai_provider.SPEC,
    "gemini": gemini_provider.SPEC,
}
