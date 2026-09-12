from pydantic import BaseModel


class MetricResult(BaseModel):
    # score/passed are None for informational metrics (length_tokens_approx,
    # latency_ms) that carry no pass/fail signal, not for a metric that ran and
    # failed -- a failed metric always has score=0.0, passed=False.
    name: str
    score: float | None
    passed: bool | None
    detail: str | None = None


class CaseScore(BaseModel):
    case_id: str
    metrics: list[MetricResult]
