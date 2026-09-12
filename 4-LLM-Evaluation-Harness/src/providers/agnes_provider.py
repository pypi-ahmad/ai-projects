"""Agnes AI provider (agnes-2.5-flash), via its OpenAI-compatible Chat
Completions endpoint.
"""

from src.config import AGNES_BASE_URL, AGNES_MODEL, load_settings
from src.providers.base import ProviderConfigError, ProviderSpec
from src.providers.openai_compat_client import OpenAICompatibleProvider

DEFAULT_MODEL = AGNES_MODEL
ALLOWED_MODELS = (AGNES_MODEL,)


def make_provider() -> OpenAICompatibleProvider:
    settings = load_settings()
    if not settings.agnes_api_key:
        raise ProviderConfigError(
            "AGNES_API_KEY is not set. Add it to your .env, or choose a different --provider."
        )
    return OpenAICompatibleProvider(api_key=settings.agnes_api_key, base_url=AGNES_BASE_URL)


SPEC = ProviderSpec(
    factory=make_provider, default_model=DEFAULT_MODEL, allowed_models=ALLOWED_MODELS
)
