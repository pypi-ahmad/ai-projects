"""Which provider serves which model -- the fixed catalog from the project
spec, not something tenants or admins configure per model.

`dispatch()` is the only entry point route code should use; it's wrapped
by src/api/deps.py::get_dispatcher so src/api/app.py::chat gets it via
`Depends(...)` and tests can substitute a fake instead."""

from __future__ import annotations

from collections.abc import Callable

from src.providers.base import ProviderResult

MODEL_PROVIDERS: dict[str, str] = {
    "granite4.1:3b": "ollama",
    "qwen3.5:2b": "ollama",
    "qwen3.5:0.8b": "ollama",
    "qwen3-vl:2b": "ollama",
    "qwen3-embedding:0.6b": "ollama",
    "qwen3-embedding:4b": "ollama",
    "translategemma:4b": "ollama",
    "AuditAid/PaddleOCR-VL-1.6-0.9B": "ollama",
    "agnes-2.5-flash": "agnes",
    "gpt-5.6-luna": "openai_compatible",
    "gpt-5.6-terra": "openai_compatible",
    "gemini-3.5-flash-lite": "gemini",
    "gemini-3.7-flash": "gemini",
}

Dispatcher = Callable[[str, str, list[dict], int | None], ProviderResult]


def dispatch(provider: str, model: str, messages: list[dict], max_tokens: int | None) -> ProviderResult:
    # Imported lazily so importing the registry (e.g. to read MODEL_PROVIDERS)
    # never requires the provider SDKs to be importable.
    from src.providers import agnes_provider, gemini_provider, ollama_provider, openai_compatible_provider

    complete = {
        "ollama": ollama_provider.complete,
        "agnes": agnes_provider.complete,
        "openai_compatible": openai_compatible_provider.complete,
        "gemini": gemini_provider.complete,
    }[provider]
    return complete(model, messages, max_tokens)
