"""Shared result/error types for every provider adapter in this package.

route/executor.py's fallback loop catches only ProviderError, so every
complete() implementation must wrap any failure (HTTP error, timeout,
malformed response, etc.) as ProviderError or a subclass — never let a raw
exception escape complete().
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ProviderResult:
    text: str
    in_tokens: int
    out_tokens: int
    approximate: bool = False  # True when tokens were estimated by tiktoken
    # because the provider response did not include a usage/token count.


class ProviderError(Exception):
    """Provider call failed; executor moves to next fallback."""


class MissingKeyError(ProviderError):
    """Required API key absent from environment."""
