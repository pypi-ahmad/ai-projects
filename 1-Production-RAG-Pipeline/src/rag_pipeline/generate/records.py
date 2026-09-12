"""Result schema for generate."""

from dataclasses import dataclass, field


@dataclass
class GenerateResult:
    answer_markdown: str
    citations: list[dict] = field(default_factory=list)
    model: str = ""
    latency_ms: float = 0.0
    retrieval_trace: list[dict] = field(default_factory=list)
