"""Dormant arithmetic validator for the invoice control plane (see
docs/ARCHITECTURE.md, docs/VALIDATE.md): the sole authority on whether an
`Invoice` is internally consistent (line-item math, subtotal, grand total).
Not called by the active graph -- `ParsePage`/`ParseBlock` has no arithmetic
contract for this module to check.

Must not: mutate the `Invoice` it's given, or correct a wrong number to make
the math balance -- `validate_invoice`/`merge_line_item` both return new
values, and a failing check is reported for a human/model to fix, never
silently rewritten (see docs/COMPLIANCE.md's "no silent fixes").

Next: docs/VALIDATE.md for the exact rule list, or src/regions.py for what a
field failing here would trigger.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.schema import Invoice, LineItem, ValidationErrorItem, ValidationReport

# Absorbs floating-point noise and cent rounding without hiding a genuinely
# wrong number -- see docs/VALIDATE.md.
TOLERANCE = 0.05


def validate_invoice(inv: Invoice) -> ValidationReport:
    """Pure arithmetic check. Never mutates `inv` or any of its fields."""
    errors: list[ValidationErrorItem] = []

    if not inv.line_items:
        errors.append(
            ValidationErrorItem(code="empty_line_items", msg="invoice has no line items")
        )
        return ValidationReport(ok=False, errors=errors)

    for i, item in enumerate(inv.line_items):
        expected = item.quantity * item.unit_price
        if abs(expected - item.amount) > TOLERANCE:
            errors.append(
                ValidationErrorItem(
                    code=f"line_item_math[{i}]",
                    msg=(
                        f"line_items[{i}]: quantity*unit_price "
                        f"({expected:.2f}) != amount ({item.amount:.2f})"
                    ),
                    expected=expected,
                    actual=item.amount,
                )
            )

    amounts_sum = sum(item.amount for item in inv.line_items)
    if abs(amounts_sum - inv.subtotal) > TOLERANCE:
        errors.append(
            ValidationErrorItem(
                code="subtotal_mismatch",
                msg=(
                    f"sum(line_items.amount) ({amounts_sum:.2f}) != "
                    f"subtotal ({inv.subtotal:.2f})"
                ),
                expected=amounts_sum,
                actual=inv.subtotal,
            )
        )

    expected_total = inv.subtotal + inv.tax
    if abs(expected_total - inv.grand_total) > TOLERANCE:
        errors.append(
            ValidationErrorItem(
                code="grand_total_mismatch",
                msg=(
                    f"subtotal+tax ({expected_total:.2f}) != "
                    f"grand_total ({inv.grand_total:.2f})"
                ),
                expected=expected_total,
                actual=inv.grand_total,
            )
        )

    return ValidationReport(ok=not errors, errors=errors)


def merge_line_item(inv: Invoice, index: int, item: LineItem) -> Invoice:
    """Return a new Invoice with line_items[index] replaced by `item`. Does not mutate `inv`."""
    new_items = list(inv.line_items)
    new_items[index] = item
    return inv.model_copy(update={"line_items": new_items})


def _main() -> None:
    parser = argparse.ArgumentParser(description="Validate an invoice JSON file.")
    parser.add_argument("--json", required=True, help="Path to an Invoice JSON file")
    args = parser.parse_args()

    with open(args.json, "r", encoding="utf-8") as f:
        data = json.load(f)

    inv = Invoice.model_validate(data)
    report = validate_invoice(inv)
    print(report.model_dump_json(indent=2))
    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    _main()
