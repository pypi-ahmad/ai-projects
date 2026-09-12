"""Judge rubric definitions loaded from rubrics/*.yaml."""

from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

_WEIGHT_TOLERANCE = 1e-6


class RubricDimension(BaseModel):
    name: str
    description: str
    weight: float


class Rubric(BaseModel):
    id: str
    version: int
    dimensions: list[RubricDimension]

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "Rubric":
        total = sum(d.weight for d in self.dimensions)
        if abs(total - 1.0) > _WEIGHT_TOLERANCE:
            raise ValueError(f"rubric {self.id!r} dimension weights sum to {total}, expected 1.0")
        return self


def load_rubric(rubrics_dir: Path, rubric_id: str) -> Rubric:
    path = rubrics_dir / f"{rubric_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no rubric file for {rubric_id!r} at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Rubric.model_validate(data)
