"""Ollama provider: local, no API key required. Handles rewrite/critique/answer roles --
pass the role's model explicitly per call (e.g. model="qwen3.5:0.8b" for critique,
model="granite4.1:3b" for the final answer).

complete() does not unload the model afterward -- that VRAM discipline (only one Ollama
model resident at a time) is the caller's responsibility; see llm/vram.py.
"""

import ollama

from self_correcting_rag.config import load_settings
from self_correcting_rag.llm.base import ProviderSpec

DEFAULT_MODEL = "granite4.1:3b"
ALLOWED_MODELS = ("granite4.1:3b", "qwen3.5:2b", "qwen3.5:0.8b")


class OllamaProvider:
    def __init__(self) -> None:
        self._client = ollama.Client(host=load_settings().ollama_host)

    def complete(self, *, system: str, user: str, model: str) -> str:
        response = self._client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.message.content or ""


def make_provider() -> OllamaProvider:
    return OllamaProvider()


SPEC = ProviderSpec(
    factory=make_provider, default_model=DEFAULT_MODEL, allowed_models=ALLOWED_MODELS
)
