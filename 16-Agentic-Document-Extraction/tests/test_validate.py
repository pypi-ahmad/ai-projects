"""Contract tests for the dormant src.validate arithmetic checks
(docs/VALIDATE.md) -- not exercised by the active graph (see
docs/ARCHITECTURE.md), but kept green so the logic stays verified
independently of any UI/graph wiring.

Next: src/validate.py.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schema import Invoice, LineItem
from src.validate import merge_line_item, validate_invoice


def _good_invoice() -> Invoice:
    return Invoice(
        invoice_number="INV-1001",
        vendor="Acme Supplies",
        invoice_date="2026-09-01",
        currency="USD",
        line_items=[
            LineItem(description="Widget A", quantity=3, unit_price=10.00, amount=30.00),
            LineItem(description="Widget B", quantity=2, unit_price=25.00, amount=50.00),
        ],
        subtotal=80.00,
        tax=8.00,
        grand_total=88.00,
    )


def test_good_invoice_passes():
    report = validate_invoice(_good_invoice())
    assert report.ok
    assert report.errors == []


def test_tax_mismatch_fails():
    inv = _good_invoice().model_copy(update={"grand_total": 100.00})
    report = validate_invoice(inv)
    assert not report.ok
    assert any(e.code == "grand_total_mismatch" for e in report.errors)


def test_line_amount_mismatch_fails():
    good = _good_invoice()
    bad_item = LineItem(description="Widget A", quantity=3, unit_price=10.00, amount=999.00)
    inv = good.model_copy(update={"line_items": [bad_item, good.line_items[1]]})
    report = validate_invoice(inv)
    assert not report.ok
    assert any(e.code == "line_item_math[0]" for e in report.errors)


def test_empty_line_items_fails():
    inv = _good_invoice().model_copy(update={"line_items": []})
    report = validate_invoice(inv)
    assert not report.ok
    assert report.errors[0].code == "empty_line_items"


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Invoice.model_validate({**_good_invoice().model_dump(), "unexpected": 1})


def test_merge_line_item_does_not_mutate():
    inv = _good_invoice()
    original_items = inv.line_items
    new_item = LineItem(description="Widget A", quantity=3, unit_price=11.00, amount=33.00)

    merged = merge_line_item(inv, 0, new_item)

    assert inv.line_items is original_items
    assert inv.line_items[0].amount == 30.00
    assert merged.line_items[0].amount == 33.00
