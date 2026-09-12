"""Schemas for config/gate.yaml, baselines/current.json, and one gate check
failure. See evaluate.py for how these are checked and accept.py for how a
Baseline is built and written.
"""

from pydantic import BaseModel

from src.eval.models import RunSummary


class GateConfig(BaseModel):
    """config/gate.yaml. All thresholds are optional -- a gate only checks
    what it's configured to check.
    """

    min_rule_pass_rate: float | None = None
    min_judge_overall: float | None = None
    max_p95_latency_ms: float | None = None
    max_regression_delta: float | None = None
    allow_missing_judge: bool = False


class BaselineConfig(BaseModel):
    candidate_provider: str | None = None
    candidate_model: str | None = None
    judge_provider: str | None = None
    judge_model: str | None = None
    dataset_path: str
    dataset_hash: str


class Baseline(BaseModel):
    summary: RunSummary
    config: BaselineConfig


class GateFailure(BaseModel):
    check: str
    message: str
