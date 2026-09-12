# Validation rules (dormant)

**Status: not wired into the active graph.** `src/validate.py` is intact and
tested, but `src/graph.py` doesn't call it — the active graph is just
`preprocess -> parse`. See
[docs/ARCHITECTURE.md](ARCHITECTURE.md#dormant-the-invoice-extractionvalidation-graph)
for why, and [docs/COMPLIANCE.md](COMPLIANCE.md) for what actually runs
today. The rules below describe what this code still does when called
directly (e.g. from its tests), kept for a future prior-auth-appropriate
validation model.

All checks use an absolute tolerance of **0.05** (currency units) to absorb
floating-point noise and cent rounding, not to hide genuinely wrong numbers.

Given an `Invoice` with `line_items`, `subtotal`, `tax`, `grand_total`:

1. **Per line item**: `abs(quantity * unit_price - amount) <= 0.05`
2. **Subtotal**: `abs(sum(item.amount for item in line_items) - subtotal) <= 0.05`
3. **Grand total**: `abs(subtotal + tax - grand_total) <= 0.05`
4. **Non-empty**: an invoice with zero `line_items` is never `ok`, regardless
   of what the totals say.

Any failing check appends a `ValidationErrorItem(code, msg, expected, actual)`
to the report; `ValidationReport.ok` is `True` only if every check passes.

## Exercising this directly

`tests/fixtures/make_invoice_png.py` generates `invoice.png` with numbers
matching `good_invoice.json` — a synthetic invoice that passes every check
above, for exercising this validator (and the rest of the dormant path)
directly via its tests, since there's no UI route to it today. The same
script's `invoice_distorted.png` was meant to exercise a retry path in the
dormant extract/validate cycle, but no currently-listed test file loads it.

## What this does *not* do

- It does not correct a wrong number. If `amount` disagrees with
  `quantity * unit_price`, that's a validation failure to route back to the
  model (or a human) — Python never edits the value to make the math work.
  See [docs/COMPLIANCE.md](docs/COMPLIANCE.md).
- It does not check the number formats, currency codes, or vendor identity —
  arithmetic only.
