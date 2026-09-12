"""Shared provider interface so callers (CLI, runner, later Streamlit) can swap
providers uniformly.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class ProviderConfigError(Exception):
    """Raised when a provider's required env var(s) are missing. Callers
    should catch this and print a clear message instead of crashing.
    """


class Provider(Protocol):
    def complete(
        self, *, system: str | None, user: str, model: str, think: bool | None = None
    ) -> str:
        """Runs one system+user completion, returns the raw response text.

        `think` is a hint to disable a model's extended "thinking"/chain-of-thought
        output (only meaningful for Ollama's thinking-capable models, e.g. the
        qwen3.5 family) -- other providers accept and ignore it. Judge and repair
        calls pass `think=False`: a thinking model can otherwise spend its entire
        output budget on chain-of-thought and never emit the final JSON verdict.
        """


@runtime_checkable
class Unloadable(Protocol):
    """Providers backed by a local model that can be evicted from VRAM
    implement this (currently only OllamaProvider). Checked via
    `isinstance(provider, Unloadable)` rather than `hasattr` so it's both
    correct at runtime and provable by a static type checker.
    """

    def unload(self, model: str) -> None: ...


@dataclass
class ProviderSpec:
    """One entry in `src.providers.registry.PROVIDERS`. `factory` is deferred
    (called only once a provider is actually selected) so constructing the
    registry never eagerly reads env vars or raises `ProviderConfigError` for
    providers the caller isn't using. `allowed_models` is the source of truth
    callers validate a `--model` argument against before calling `factory`.
    """

    factory: Callable[[], Provider]
    default_model: str
    allowed_models: tuple[str, ...]
