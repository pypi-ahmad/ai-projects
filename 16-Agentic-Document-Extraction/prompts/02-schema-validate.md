# Phase 2: Schema and validation

**Implement** the Pydantic schemas and the arithmetic validator. No OpenAI calls, no graph wiring in this phase.

**Schemas** (Pydantic v2, `extra` forbidden on every model):

```python
class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    amount: float

class Invoice(BaseModel):
    invoice_number: str
    vendor: str | None = None
    invoice_date: str | None = None
    currency: str | None = None
    line_items: list[LineItem]
    subtotal: float
    tax: float
    grand_total: float

class Region(BaseModel):
    id: str
    field_or_line_index: str
    conf: float
    bbox_xyxy: tuple[float, float, float, float]
    reason: str | None = None

class ValidationErrorItem(BaseModel):
    code: str
    msg: str
    expected: float | None = None
    actual: float | None = None

class ValidationReport(BaseModel):
    ok: bool
    errors: list[ValidationErrorItem]
```

**Functions:**
- `validate_invoice(inv: Invoice) -> ValidationReport`; an invoice with empty `line_items` is never `ok`; never mutate the input or its values.
- `merge_line_item(inv, index, item)`; used later for crop-based updates.

**Tests** (`tests/test_validate.py`): a passing invoice; a tax mismatch; a line whose `amount != quantity * unit_price`; an empty-`line_items` invoice.

**CLI:** `python -m src.validate --json tests/fixtures/good_invoice.json`

**Fixture:** hand-write `tests/fixtures/good_invoice.json` so its numbers match the invoice image Phase 3 will render.

Stop after this phase.
