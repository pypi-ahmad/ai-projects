from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

_Score = Annotated[float, Field(ge=0.0, le=1.0)]


class JudgeVerdict(BaseModel):
    """What the judge model's JSON response must validate as. `pass` is a
    Python keyword, so the attribute is `passed` with alias "pass" -- both
    the alias and the plain name are accepted on input.
    """

    model_config = ConfigDict(populate_by_name=True)

    scores: dict[str, _Score]
    overall: _Score
    passed: bool = Field(alias="pass")
    rationale: str
    evidence_spans: list[str] = Field(default_factory=list)


class JudgeRecord(BaseModel):
    """One line of judge_scores.jsonl: a validated JudgeVerdict's fields
    flattened alongside run metadata, or a judge_error placeholder when
    judging a required case never produced a valid verdict.
    """

    case_id: str
    rubric_id: str
    judge_provider: str
    judge_model: str
    same_model_warning: bool = False
    status: Literal["ok", "judge_error"]
    scores: dict[str, float] = Field(default_factory=dict)
    overall: float | None = None
    passed: bool | None = None
    rationale: str | None = None
    evidence_spans: list[str] = Field(default_factory=list)
    error: str | None = None
