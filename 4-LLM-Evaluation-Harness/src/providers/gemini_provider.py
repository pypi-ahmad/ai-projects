"""Google Gemini provider via the google-genai SDK."""

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from src.config import GEMINI_MODELS, load_settings
from src.providers.base import ProviderConfigError, ProviderSpec
from src.providers.retry import call_with_retries

DEFAULT_MODEL = GEMINI_MODELS[0]
ALLOWED_MODELS = GEMINI_MODELS


def is_5xx(exc: Exception) -> bool:
    return isinstance(exc, genai_errors.ServerError)


class GeminiProvider:
    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    def complete(
        self, *, system: str | None, user: str, model: str, think: bool | None = None
    ) -> str:
        # `think` accepted only for interface uniformity -- no equivalent control
        # is wired up for Gemini here.
        config = types.GenerateContentConfig(system_instruction=system) if system else None

        def _call() -> str:
            response = self._client.models.generate_content(
                model=model, contents=user, config=config
            )
            return response.text or ""

        return call_with_retries(_call, is_retryable=is_5xx)


def make_provider() -> GeminiProvider:
    settings = load_settings()
    if not settings.google_api_key:
        raise ProviderConfigError(
            "GOOGLE_API_KEY is not set. Add it to your .env, or choose a different --provider."
        )
    return GeminiProvider(settings.google_api_key)


SPEC = ProviderSpec(
    factory=make_provider, default_model=DEFAULT_MODEL, allowed_models=ALLOWED_MODELS
)
