"""Typed contracts for the self-correction loop's LLM-produced JSON and the
trace of what it did. `agent/critique.py` enforces the decision rules on top
of `CritiqueResult` -- this module only defines shape and range constraints.
Next: agent/loop.py, which is what actually populates AgentTrace/AgentResult.
"""

from typing import Literal

from pydantic import BaseModel, Field

Stage = Literal["rewrite", "retrieve", "critique", "web", "generate", "error"]


class RewriteResult(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=3)
    rationale: str


class CritiqueResult(BaseModel):
    grounded: float = Field(ge=0.0, le=1.0)
    coverage: float = Field(ge=0.0, le=1.0)
    missing: list[str] = Field(default_factory=list)
    decision: Literal["answer", "retry", "web", "abstain"]
    rationale: str


class LoopPolicy(BaseModel):
    """Defaults match docs/LOOP.md -- change there and here together."""

    confidence_threshold: float = 0.6
    max_iters: int = 2
    web_enabled: bool = False
    # False (default): strip an illegal [S#]/[W#] citation and lower confidence.
    # True: abstain entirely instead of returning a partially-cleaned answer.
    citation_fail_closed: bool = False


class AgentStep(BaseModel):
    iteration: int
    stage: Stage
    summary: str
    detail: dict = Field(default_factory=dict)


class AgentTrace(BaseModel):
    steps: list[AgentStep] = Field(default_factory=list)

    def record(self, *, iteration: int, stage: Stage, summary: str, **detail: object) -> None:
        self.steps.append(
            AgentStep(iteration=iteration, stage=stage, summary=summary, detail=detail)
        )


class AgentResult(BaseModel):
    """Fixed return schema for run(): `answer` is None on abstain, with
    `reason` explaining why; both are populated on a normal answer.
    """

    answer: str | None
    reason: str | None = None
    confidence: float | None = None
    citations: list[str] = Field(default_factory=list)
    trace: AgentTrace
