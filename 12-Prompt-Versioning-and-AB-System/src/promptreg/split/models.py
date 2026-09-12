"""Experiment / arm / assignment / resolution data types."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Status = Literal["draft", "running", "paused", "stopped"]

BUCKET_SPACE = 100


class Arm(BaseModel):
    name: str
    version: int
    weight: int = Field(ge=0)


def validate_arms(arms: list[Arm]) -> None:
    if not arms:
        msg = "experiment needs at least one arm"
        raise ValueError(msg)
    total = sum(arm.weight for arm in arms)
    if total != BUCKET_SPACE:
        msg = f"arm weights must sum to {BUCKET_SPACE}, got {total}"
        raise ValueError(msg)
    names = [arm.name for arm in arms]
    if len(names) != len(set(names)):
        msg = f"arm names must be unique: {names}"
        raise ValueError(msg)


class Experiment(BaseModel):
    id: int
    name: str
    prompt_name: str
    status: Status
    arms: list[Arm]
    sticky_salt: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _check_arms(self) -> Experiment:
        validate_arms(self.arms)
        return self


class Assignment(BaseModel):
    experiment_id: int
    user_key: str
    arm: str
    version: int
    created_at: datetime


class Resolution(BaseModel):
    version: int
    arm: str | None
    experiment_id: int | None
    reason: str
