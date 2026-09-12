"""Built-in schema: a vendor invoice with nested line items. See
schemas/__init__.py for how it's registered and docs/SCHEMAS.md for the
pattern to follow when adding another."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CAD = "CAD"
    AUD = "AUD"


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="What this line item is for.")
    quantity: float = Field(gt=0, description="Quantity billed.")
    unit_price: float = Field(ge=0, description="Price per unit, in the invoice's currency.")
    amount: float = Field(ge=0, description="Total for this line (quantity * unit_price).")


class InvoiceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a provider's output must match this exactly, not just include it

    vendor: str = Field(description="Name of the vendor or supplier issuing the invoice.")
    currency: Currency = Field(description="ISO currency code for all monetary amounts on this invoice.")
    line_items: list[LineItem] = Field(description="Individual billed items.")
    totals: float = Field(ge=0, description="Total amount due across all line items.")
    invoice_date: date = Field(description="Date the invoice was issued.")


INVOICE_DRAFT_EXAMPLE = InvoiceDraft(
    vendor="Acme Supplies",
    currency=Currency.USD,
    line_items=[
        LineItem(description="Widgets", quantity=10, unit_price=2.5, amount=25.0),
        LineItem(description="Shipping", quantity=1, unit_price=5.0, amount=5.0),
    ],
    totals=30.0,
    invoice_date=date(2026, 1, 15),
)
