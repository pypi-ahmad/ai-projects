"""Schema for data/eval/qa.jsonl and eval results."""

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    id: str
    question: str
    relevant_chunk_ids: list[str] | None = None
    relevant_sources: list[dict] | None = None  # [{"source_path": ..., "page": ...}, ...]
    gold_answer: str | None = None


@dataclass
class EvalCaseResult:
    id: str
    question: str
    recall_at_k: float | None  # None if the case has no labeled relevant set
    citation_hit_rate: float | None  # None if the answer cited nothing
    latency_ms: float
    faithfulness: float | None = None  # None unless a judge model was used


@dataclass
class EvalReport:
    k: int
    judge_model: str | None
    cases: list[EvalCaseResult] = field(default_factory=list)

    @property
    def mean_recall_at_k(self) -> float | None:
        values = [c.recall_at_k for c in self.cases if c.recall_at_k is not None]
        return sum(values) / len(values) if values else None

    @property
    def mean_citation_hit_rate(self) -> float | None:
        values = [c.citation_hit_rate for c in self.cases if c.citation_hit_rate is not None]
        return sum(values) / len(values) if values else None

    @property
    def mean_latency_ms(self) -> float:
        return sum(c.latency_ms for c in self.cases) / len(self.cases) if self.cases else 0.0

    @property
    def mean_faithfulness(self) -> float | None:
        values = [c.faithfulness for c in self.cases if c.faithfulness is not None]
        return sum(values) / len(values) if values else None
