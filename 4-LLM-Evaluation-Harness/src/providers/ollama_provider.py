"""Ollama provider: local, no API key required."""

import logging

import ollama

from src.config import load_settings
from src.providers.base import ProviderSpec
from src.providers.retry import call_with_retries

DEFAULT_MODEL = "granite4.1:3b"
ALLOWED_MODELS = ("granite4.1:3b", "qwen3.5:2b", "qwen3.5:0.8b")

logger = logging.getLogger(__name__)


def is_5xx(exc: Exception) -> bool:
    return isinstance(exc, ollama.ResponseError) and exc.status_code >= 500


class OllamaProvider:
    def __init__(self) -> None:
        self._client = ollama.Client(host=load_settings().ollama_host)

    def complete(
        self, *, system: str | None, user: str, model: str, think: bool | None = None
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        def _call() -> str:
            response = self._client.chat(model=model, messages=messages, think=think)
            return response.message.content or ""

        return call_with_retries(_call, is_retryable=is_5xx)

    def unload(self, model: str) -> None:
        """Evicts `model` from VRAM immediately instead of waiting for Ollama's
        own idle keep_alive timeout -- best-effort, never fails the caller's run.
        """
        try:
            self._client.generate(model=model, prompt="", keep_alive=0)
        except Exception:
            logger.warning("failed to unload %s", model)


def make_provider() -> OllamaProvider:
    return OllamaProvider()


SPEC = ProviderSpec(
    factory=make_provider, default_model=DEFAULT_MODEL, allowed_models=ALLOWED_MODELS
)
