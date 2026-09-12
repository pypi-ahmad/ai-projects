"""RunSummary is the on-disk shape of reports/<run>/summary.json -- the
sole input src.gate reads to decide pass/fail. See summarize.py for how one
is built from a run's candidates/rule_scores/judge_scores files.
"""

from pydantic import BaseModel, Field


class GroupSummary(BaseModel):
    n_cases: int
    n_error: int
    mean_rule_pass_rate: float | None
    mean_judge_overall: float | None
    p95_latency_ms: float | None


class RunSummary(BaseModel):
    run_id: str
    dataset_path: str
    dataset_hash: str
    n_cases: int
    n_error: int
    mean_rule_pass_rate: float | None
    mean_judge_overall: float | None
    p95_latency_ms: float | None
    by_suite: dict[str, GroupSummary] = Field(default_factory=dict)
    by_tag: dict[str, GroupSummary] = Field(default_factory=dict)
