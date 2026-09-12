"""Google Gemini provider via the google-genai SDK."""

from google import genai
from google.genai import types

from self_correcting_rag.config import GEMINI_MODELS, load_settings
from self_correcting_rag.llm.base import ProviderConfigError, ProviderSpec

DEFAULT_MODEL = GEMINI_MODELS[0]
ALLOWED_MODELS = GEMINI_MODELS


class GeminiProvider:
    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    def complete(self, *, system: str, user: str, model: str) -> str:
        response = self._client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        return response.text or ""


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
