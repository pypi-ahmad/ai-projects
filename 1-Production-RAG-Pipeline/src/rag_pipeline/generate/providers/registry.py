"""Provider name -> ProviderSpec, so callers (CLI, Streamlit) can enumerate
and select providers uniformly.
"""

from rag_pipeline.generate.providers import (
    agnes_provider,
    gemini_provider,
    ollama_provider,
    openai_provider,
)
from rag_pipeline.generate.providers.base import ProviderSpec

PROVIDERS: dict[str, ProviderSpec] = {
    "ollama": ollama_provider.SPEC,
    "agnes": agnes_provider.SPEC,
    "openai_compatible": openai_provider.SPEC,
    "gemini": gemini_provider.SPEC,
}
