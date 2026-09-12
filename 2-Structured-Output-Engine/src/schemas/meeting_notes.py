"""Built-in schema: meeting minutes with attendees, decisions, and nested
action items. See schemas/__init__.py for how it's registered and
docs/SCHEMAS.md for the pattern to follow when adding another."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict, Field


class ActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="What needs to be done.")
    owner: str = Field(description="Person responsible for this action item.")
    due: datetime.date = Field(description="Date this action item is due.")


class MeetingNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a provider's output must match this exactly, not just include it

    title: str = Field(description="Meeting title or subject.")
    date: datetime.date = Field(description="Date the meeting took place.")
    attendees: list[str] = Field(description="Names of people who attended.")
    decisions: list[str] = Field(description="Decisions made during the meeting.")
    action_items: list[ActionItem] = Field(description="Follow-up tasks assigned during the meeting.")


MEETING_NOTES_EXAMPLE = MeetingNotes(
    title="Q1 Planning",
    date=datetime.date(2026, 1, 10),
    attendees=["Ada Lovelace", "Grace Hopper"],
    decisions=["Ship Phase 2 by end of month"],
    action_items=[
        ActionItem(description="Draft schema registry", owner="Ada Lovelace", due=datetime.date(2026, 1, 20)),
    ],
)
