"""Built-in schema: a person's contact info (name/email/phone/tags). See
schemas/__init__.py for how it's registered and docs/SCHEMAS.md for the
pattern to follow when adding another."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ContactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a provider's output must match this exactly, not just include it

    name: str = Field(description="Full name of the contact.")
    email: EmailStr = Field(description="Contact's email address.")
    phone: str | None = Field(default=None, description="Phone number, if known.")
    tags: list[str] = Field(default_factory=list, description="Free-form labels for this contact.")


CONTACT_RECORD_EXAMPLE = ContactRecord(
    name="Ada Lovelace",
    email="ada@example.com",
    phone="+1-555-0100",
    tags=["mathematician", "vip"],
)
