"""Environment-driven settings and provider model constants. Values come from
process env vars (case-insensitive) or a local `.env` file (git-ignored, never
committed -- see the "Local secrets" entry in .gitignore); a missing key just
leaves the corresponding field None, which each provider's make_provider()
turns into a ProviderConfigError at construction time, not at import time here.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

AGNES_MODEL = "agnes-2.5-flash"
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"
OPENAI_COMPAT_MODELS = ("gpt-5.6-luna", "gpt-5.6-terra")
GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.7-flash")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    ollama_host: str = "http://127.0.0.1:11434"

    agnes_api_key: str | None = None

    openai_api_key: str | None = None
    openai_base_url: str | None = None

    google_api_key: str | None = None


def load_settings() -> Settings:
    return Settings()
