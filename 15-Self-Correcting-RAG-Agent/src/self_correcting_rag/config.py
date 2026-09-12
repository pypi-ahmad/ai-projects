"""Environment-driven settings and the fixed model/provider allowlists for this agent."""

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Ollama tags confirmed present via `ollama list` on this machine on 2026-09-12.
# Re-verify before adding to this dict -- a wrong tag fails `ollama pull` loudly, but a
# wrong org/name can also silently resolve to someone else's unrelated model.
ALLOWED_OLLAMA_MODELS: dict[str, str] = {
    "granite4.1:3b": "final cited answer (default)",
    "qwen3.5:2b": "rewrite / critique JSON (fallback)",
    "qwen3.5:0.8b": "rewrite / critique JSON (default)",
    "qwen3-vl:2b": "OCR layout & figure captions (fallback)",
    "qwen3-embedding:0.6b": "dense embed (default)",
    "qwen3-embedding:4b": "dense embed (fallback, only with VRAM headroom)",
    "translategemma:4b": "web fallback query translation (non-English only)",
    "AuditAid/PaddleOCR-VL-1.6-0.9B": "OCR ingest (optional)",
}

OPENAI_COMPAT_MODELS = ("gpt-5.6-luna", "gpt-5.6-terra")
GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.7-flash")
AGNES_MODEL = "agnes-2.5-flash"
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    ollama_host: str = "http://127.0.0.1:11434"

    # NOTE: the configured Windows variable is AGNESAI_API_KEY (not AGNES_API_KEY) --
    # verified present in this process's environment; do not rename without re-checking.
    agnesai_api_key: str | None = None

    openai_api_key: str | None = None
    openai_base_url: str | None = None

    google_api_key: str | None = None

    # Reserved for the web fallback step (Phase 4's WebSearch interface). No
    # concrete search provider is wired to these yet -- see docs/LOOP.md.
    search_api_key: str | None = None
    search_base_url: str | None = None

    def available_providers(self) -> list[str]:
        """Providers whose required env vars are present, in UI display order."""
        providers = ["ollama"]
        if self.agnesai_api_key:
            providers.append("agnes")
        if self.openai_api_key and self.openai_base_url:
            providers.append("openai_compatible")
        if self.google_api_key:
            providers.append("gemini")
        return providers

    def resolve_web_enabled(self, requested: bool) -> bool:
        """Startup-time gate: web fallback can only be enabled if
        SEARCH_API_KEY is configured, regardless of what was requested (a
        CLI flag, a UI toggle). Never silently trusts the request alone.
        """
        if requested and not self.search_api_key:
            logger.warning("SEARCH_API_KEY is not set; forcing web_enabled=False at startup")
            return False
        return requested


def load_settings() -> Settings:
    return Settings()


if __name__ == "__main__":
    settings = load_settings()
    assert "ollama" in settings.available_providers()
    assert len(ALLOWED_OLLAMA_MODELS) == 8
    print("Available providers:", settings.available_providers())
    print("Allowed Ollama models:", list(ALLOWED_OLLAMA_MODELS))
    print("OK")
