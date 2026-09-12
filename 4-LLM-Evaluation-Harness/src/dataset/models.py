"""Golden-case schema: one validated `Case` per line of a `datasets/golden/*.jsonl`
file. All models use `extra="forbid"`, so a typo'd or renamed field in a case file
is a validation error at load time, not a silently-ignored field. See loader.py for
where these models are parsed from JSONL and aggregated into per-file errors.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: str
    system: str | None = None
    context: str | None = None


class CaseExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str | None = None
    contains_any: list[str] | None = None
    contains_all: list[str] | None = None
    regex: str | None = None
    # Only gates on JSON *validity* (src/metrics/rules.py: json_parse_ok) -- there is
    # no schema registry, so this name is not resolved or checked against anything.
    json_schema_name: str | None = None
    forbidden_any: list[str] | None = None


class CaseJudge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rubric_id: str
    required: bool = False


class CaseSkipIf(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # needs_gpu is treated identically to needs_ollama by the runner (see
    # src/runners/candidate.py skip_reason()) -- Ollama is the only local,
    # GPU-backed provider in this repo, so the two conditions coincide.
    needs_ollama: bool = False
    needs_gpu: bool = False
    needs_provider: str | None = None


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    suite: Literal["smoke", "regression", "quality"]
    input: CaseInput
    expected: CaseExpected = Field(default_factory=CaseExpected)
    judge: CaseJudge | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    skip_if: CaseSkipIf | None = None
