"""Provider name -> ProviderSpec, so callers (agent loop, Streamlit) can enumerate
and select providers uniformly.

`PROVIDERS[name].factory()` can raise llm.base.ProviderConfigError if that provider's
required env var(s) are unset -- callers are expected to catch it, not let it crash.
"""

from self_correcting_rag.llm import (
    agnes_provider,
    gemini_provider,
    ollama_provider,
    openai_provider,
)
from self_correcting_rag.llm.base import ProviderSpec

PROVIDERS: dict[str, ProviderSpec] = {
    "ollama": ollama_provider.SPEC,
    "agnes": agnes_provider.SPEC,
    "openai_compatible": openai_provider.SPEC,
    "gemini": gemini_provider.SPEC,
}
