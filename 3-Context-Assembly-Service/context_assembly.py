"""
Context Assembly Service — legacy flat, single-pass packer (Phase 1/2 API).

Superseded by the src/ pipeline (src/budget/allocator.py + src/assembly/packer.py),
which adds per-family caps and a 3-pass borrow step; this module has neither — it
packs strictly in priority order until the budget is full. Kept for
test_context_assembly.py and for callers that only need one flat budget with no
family caps.

Offline path: tiktoken cl100k_base; no model required.
Compression: providers.py chain (Ollama → Agnes AI → OpenAI-compat → Gemini).
"""
from __future__ import annotations
import os, json
from dataclasses import dataclass, field
from typing import Literal, Optional
import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")

Family = Literal["memory", "docs", "tools"]


def count(text: str) -> int:
    return len(_ENC.encode(text))


@dataclass
class Block:
    name: str
    text: str
    family: Family
    priority: int = 0       # higher = keep first
    compress: bool = False  # attempt compression before dropping


@dataclass
class Decision:
    name: str
    family: str
    action: Literal["kept", "compressed", "dropped"]
    reason: str
    tokens_original: int
    tokens_used: int


@dataclass
class AssemblyResult:
    text: str
    token_count: int
    budget: int
    decisions: list[Decision] = field(default_factory=list)

    @property
    def utilization(self) -> float:
        return self.token_count / self.budget if self.budget else 0.0

    @property
    def kept(self) -> list[Decision]:
        return [d for d in self.decisions if d.action == "kept"]

    @property
    def compressed(self) -> list[Decision]:
        return [d for d in self.decisions if d.action == "compressed"]

    @property
    def dropped(self) -> list[Decision]:
        return [d for d in self.decisions if d.action == "dropped"]


def assemble(
    blocks: list[Block],
    budget: int,
    separator: str = "\n\n",
    use_compress: bool = False,
) -> AssemblyResult:
    """
    Pack blocks into budget (tokens). High-priority blocks kept first.
    Overflow blocks: compress via provider chain (if use_compress and block.compress)
    or drop. Every decision is recorded with a human-readable reason.
    """
    _compress = None
    if use_compress:
        from providers import compress as _compress  # lazy: not needed offline

    ordered = sorted(blocks, key=lambda b: b.priority, reverse=True)
    parts: list[str] = []
    decisions: list[Decision] = []
    used = 0

    for bl in ordered:
        tok = count(bl.text)
        if used + tok <= budget:
            parts.append(bl.text)
            decisions.append(Decision(
                bl.name, bl.family, "kept",
                f"fits: {tok} tok used, {budget - used - tok} remaining",
                tok, tok,
            ))
            used += tok
        elif bl.compress and use_compress and _compress is not None:
            headroom = budget - used
            summary = _compress(bl.text, headroom)
            if summary:
                stok = count(summary)
                if used + stok <= budget:
                    parts.append(summary)
                    decisions.append(Decision(
                        bl.name, bl.family, "compressed",
                        f"compressed {tok}→{stok} tok to fit {headroom} tok headroom",
                        tok, stok,
                    ))
                    used += stok
                    continue
            decisions.append(Decision(
                bl.name, bl.family, "dropped",
                f"overflow: {tok} tok, headroom {headroom}; compress failed or summary still too large",
                tok, 0,
            ))
        else:
            headroom = budget - used
            decisions.append(Decision(
                bl.name, bl.family, "dropped",
                f"overflow: {tok} tok exceeds {headroom} tok headroom",
                tok, 0,
            ))

    return AssemblyResult(
        text=separator.join(parts),
        token_count=used,
        budget=budget,
        decisions=decisions,
    )
