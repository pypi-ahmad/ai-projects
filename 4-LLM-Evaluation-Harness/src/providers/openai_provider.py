"""Generic OpenAI-compatible provider: gpt-5.6-luna / gpt-5.6-terra, medium
reasoning effort, against an arbitrary OpenAI-compatible endpoint.
"""

from src.config import OPENAI_COMPAT_MODELS, load_settings
from src.providers.base import ProviderConfigError, ProviderSpec
from src.providers.openai_compat_client import OpenAICompatibleProvider

DEFAULT_MODEL = OPENAI_COMPAT_MODELS[0]
ALLOWED_MODELS = OPENAI_COMPAT_MODELS
REASONING_EFFORT = "medium"


def make_provider() -> OpenAICompatibleProvider:
    settings = load_settings()
    if not settings.openai_api_key or not settings.openai_base_url:
        raise ProviderConfigError(
            "OPENAI_API_KEY and OPENAI_BASE_URL must both be set for the "
            "openai_compatible provider. Add them to your .env, or choose a "
            "different --provider."
        )
    return OpenAICompatibleProvider(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        reasoning_effort=REASONING_EFFORT,
    )


SPEC = ProviderSpec(
    factory=make_provider, default_model=DEFAULT_MODEL, allowed_models=ALLOWED_MODELS
)
