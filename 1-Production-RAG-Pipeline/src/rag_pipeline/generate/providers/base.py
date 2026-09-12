"""Shared provider interface so callers (CLI, Streamlit) can swap providers uniformly."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class ProviderConfigError(Exception):
    """Raised when a provider's required env var(s) are missing. Callers
    should catch this and print a clear message instead of crashing.
    """


class Provider(Protocol):
    def complete(self, *, system: str, user: str, model: str) -> str:
        """Runs one system+user completion, returns the raw response text."""


@dataclass
class ProviderSpec:
    factory: Callable[[], Provider]
    default_model: str
    allowed_models: tuple[str, ...]
