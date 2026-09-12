"""The common return shape every provider module in src/providers/ must
produce, so src/api/app.py::chat can handle all four providers identically.
Open src/providers/registry.py next to see how a provider is selected."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProviderResult:
    text: str
    in_tokens: int
    out_tokens: int
