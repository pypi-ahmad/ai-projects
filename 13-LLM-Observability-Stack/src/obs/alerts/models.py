"""Alert row schema. See docs/SCHEMA.md.

Data model only, no persistence (store.py) or evaluation (rules.py,
evaluator.py). `acked` has no reverse operation anywhere in this codebase -
once true, nothing sets it back to false.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from obs.alerts.config import Severity


class Alert(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    rule: str
    severity: Severity
    route: str | None
    model: str | None
    window: str
    value: float
    threshold: float
    trace_ids: list[str]
    ts: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    acked: bool = False
