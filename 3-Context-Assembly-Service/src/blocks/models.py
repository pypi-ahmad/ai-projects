"""
ContextBlock and ContextRequest — the input data model for the assembler.
No LLM, no packing logic here. See src/blocks/tokenizer.py for token counting and
src/budget/allocator.py for how these fields (priority, droppable, compressible,
family) actually drive keep/drop/compress decisions.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
import yaml

# "system" and "user" are packing-exempt: src/budget/allocator.py force-keeps them
# before applying any family cap. Only "memory" | "docs" | "tools" are capped/droppable.
Family = Literal["memory", "docs", "tools", "system", "user"]

_WINDOWS_YAML = Path(__file__).parent.parent.parent / "data" / "model_windows.yaml"
# Process-lifetime cache, keyed by nothing (single table) — loaded once on first
# resolve_window() call. Editing model_windows.yaml on disk has no effect until restart.
_windows_cache: Optional[dict[str, Any]] = None


def _load_windows() -> dict[str, Any]:
    global _windows_cache
    if _windows_cache is None:
        with open(_WINDOWS_YAML, encoding="utf-8") as f:
            _windows_cache = yaml.safe_load(f).get("models", {})
    return _windows_cache


@dataclass
class ContextBlock:
    """A single candidate block of context text with all metadata needed for packing."""

    id: str
    family: Family
    text: str
    priority: int = 0
    token_count: Optional[int] = None       # populated by TokenCounter.count_block()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: Optional[str] = None            # file path, tool name, or memory key
    droppable: bool = True                  # may be omitted to fit budget
    compressible: bool = False              # may be summarised before dropping
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def new(family: Family, text: str, **kwargs: Any) -> "ContextBlock":
        """Convenience factory that generates a random id."""
        return ContextBlock(id=uuid.uuid4().hex, family=family, text=text, **kwargs)


@dataclass
class ContextRequest:
    """All inputs to one assembly call."""

    blocks: list[ContextBlock]
    user_message: str
    model_name: Optional[str] = None
    context_window: Optional[int] = None   # required when model_name not in table
    reserve_output_tokens: Optional[int] = None   # None → BudgetPolicy default
    reserve_system_tokens: Optional[int] = None   # None → BudgetPolicy default
    policy: str = "default"

    def resolve_window(self) -> int:
        """
        Return the effective context window in tokens.
        Precedence: explicit context_window > model_windows.yaml lookup.
        Raises ValueError when neither source can provide a value.
        """
        if self.context_window is not None:
            return self.context_window
        if self.model_name:
            entry = _load_windows().get(self.model_name, {})
            w = entry.get("context_window") if isinstance(entry, dict) else None
            if w is not None:
                return int(w)
        raise ValueError(
            f"context_window unknown for model {self.model_name!r}. "
            "Either add it to data/model_windows.yaml or pass context_window "
            "explicitly in ContextRequest."
        )
