"""Support ticket -> structured JSON label: the Pydantic models and jsonl (de)serialization every
other module builds on. Must not contain generation, scoring, or CLI logic — those live in
generate.py/baseline.py/bakeoff.py. See docs/TASK.md for the task writeup; open generate.py next."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

Priority = Literal["low", "medium", "high", "urgent"]
Product = Literal["billing", "account", "mobile_app", "web_app", "api", "integrations"]
Sentiment = Literal["positive", "neutral", "negative"]
NextAction = Literal["escalate", "request_info", "resolve", "refund", "schedule_callback"]


class TicketTarget(BaseModel):
    priority: Priority
    product: Product
    sentiment: Sentiment
    next_action: NextAction


class GeneratedRow(BaseModel):
    """One teacher-generated row: ticket text plus its label, before splitting."""

    ticket: str
    priority: Priority
    product: Product
    sentiment: Sentiment
    next_action: NextAction


class TicketExample(BaseModel):
    input: str
    target: TicketTarget
    split: Literal["train", "val", "test"]
    source: Literal["synthetic"] = "synthetic"
    teacher_model: str


# Models are told not to wrap output in markdown but sometimes do anyway; this strips a leading
# ```/```json fence (and any trailing ```) before parsing, rather than treating it as invalid.
def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


def _load_json(raw: str) -> dict:
    try:
        return json.loads(_strip_fence(raw))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e


def parse_generated_row(raw: str) -> GeneratedRow:
    """Parse and validate one teacher response (ticket text + label). Raises ValueError on bad
    JSON or schema mismatch."""
    try:
        return GeneratedRow.model_validate(_load_json(raw))
    except ValidationError as e:
        raise ValueError(f"schema mismatch: {e}") from e


def parse_ticket_target(raw: str) -> TicketTarget:
    """Parse and validate one model response (label only, no ticket text). Raises ValueError on
    bad JSON or schema mismatch."""
    try:
        return TicketTarget.model_validate(_load_json(raw))
    except ValidationError as e:
        raise ValueError(f"schema mismatch: {e}") from e


def load_examples(path: Path) -> list[TicketExample]:
    """Load one TicketExample per non-blank line of a jsonl file."""
    with Path(path).open("r", encoding="utf-8") as f:
        return [TicketExample.model_validate_json(line) for line in f if line.strip()]
