"""Parses a judge model's raw response text into a validated JudgeVerdict.
Both JSON-decode failures and schema-validation failures are normalized to
plain ValueError, so pipeline.py can catch one exception type to decide
whether to trigger the repair pass (repair.py).
"""

import json

from pydantic import ValidationError

from src.judge.models import JudgeVerdict


def parse_verdict(raw_text: str) -> JudgeVerdict:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    try:
        return JudgeVerdict.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"schema mismatch: {exc}") from exc
