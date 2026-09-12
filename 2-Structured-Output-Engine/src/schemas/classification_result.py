"""Built-in schema: a labeled classification with a confidence score and a
rationale. See schemas/__init__.py for how it's registered and
docs/SCHEMAS.md for the pattern to follow when adding another."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Label(str, Enum):
    """Placeholder label set for demonstrating enum validation. Replace with
    the real category set for a given classification task."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a provider's output must match this exactly, not just include it

    label: Label = Field(description="Classification category assigned to the input.")
    confidence: float = Field(ge=0, le=1, description="Model's confidence in this label, from 0 to 1.")
    rationale: str = Field(max_length=200, description="Brief explanation for why this label was chosen.")


CLASSIFICATION_RESULT_EXAMPLE = ClassificationResult(
    label=Label.POSITIVE,
    confidence=0.92,
    rationale="Customer praised the fast response time.",
)
