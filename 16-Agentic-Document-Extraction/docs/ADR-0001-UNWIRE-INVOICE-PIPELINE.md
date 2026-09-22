# ADR-0001: Unwire the invoice extraction/validation pipeline

- **Status:** Accepted (already implemented)
- **Date:** 2026-09-12

## Context

This project was originally built around one trust mechanism: a vision
model *proposes* an `Invoice` (vendor, line items, subtotal, tax,
grand_total), and `src/validate.py` is the sole authority on whether it's
correct: it checks that `quantity * unit_price == amount` per line item,
that line items sum to `subtotal`, and that `subtotal + tax == grand_total`
(all within a 0.05 tolerance). A document only reaches `data/committed/`
by passing those checks or by an explicit, named human override; otherwise
it goes to `data/review/`. `maybe_crop` exists purely to give the model a
second, tighter-cropped look at a field that failed validation or came back
low-confidence, before falling back to a full retry.

The project's real target documents turned out to be prior-authorization
medical forms (BadgeCare Plus and Amerigroup/RealSolutions-style intake forms,
see the evaluation corpus in `docs/PROMPT-EVALUATION.md` and
`docs/CONTENT-FILTER-DIAGNOSTICS.md`), not invoices. These forms are
key/value fields, checkboxes, and tables of patient/provider/diagnosis
information. They have no subtotal, no grand total, no arithmetic
relationship between any two fields. `src/validate.py` has nothing useful to
to evaluate. Running the invoice validator against a prior-auth extraction
would be meaningless: either every document trivially "fails" (no numeric
fields to reconcile) or the check is vacuously skipped, and either way the
resulting `commit`/`review` split and its audit trail would assert a
correctness guarantee the system never actually checked.

## Decision

Remove the `extract -> validate -> maybe_crop -> commit`/`review` portion of
the graph from `build_graph()` in `src/graph.py`. The active graph is now:

```
preprocess -> parse -> END
```

`parse` handles layout parsing, Markdown/HTML rendering, and PDF/PNG annotation.
It does not depend on the invoice arithmetic contract, so it remains active.
The current product is a best-effort layout reading for a human to compare with
the source.

The removed code is **unwired, not deleted**:

- `src/extract.py`'s `extract_invoice`, `extract_regions`, and
  `crop_and_extract` (its `_build_llm`/`_image_message`/`_invoke_structured`
  helpers are still active; `parse.py` uses them too)
- `src/validate.py` in full
- `src/regions.py` in full
- The `Invoice`, `LineItem`, `Region`, and `ValidationReport` models in
  `src/schema.py`
- `src/audit.py` (`write_audit_line`), which nothing calls today

Their existing tests keep running (see `tests/test_validate.py`,
`tests/test_regions.py`, `tests/test_extract.py`), so this code stays
verified even while it's disconnected from the graph. Full detail on what
each piece would have done, and the exact routing it used, is in
[docs/ARCHITECTURE.md](ARCHITECTURE.md#dormant-the-invoice-extractionvalidation-graph).

## Alternatives considered

1. **Keep the invoice validator active for prior-auth documents anyway.**
   Rejected: `Invoice` and a prior-auth form share no schema, and running
   arithmetic checks against fields that don't exist doesn't produce a
   meaningful `ok`/`fail` signal; it would just be a decorative control
   plane, worse than having none because it looks like a guarantee.
2. **Delete the invoice code instead of unwiring it.** Rejected: the
   propose-then-verify pattern, the shared `_invoke_structured` call
   helper, the strict-`json_schema` shaping rules (`docs/MODEL.md`), and
   the diagnostics/audit-line plumbing are all reusable once a validation
   model that actually fits prior-auth forms exists. Deleting them would
   mean re-deriving that plumbing from scratch later for no benefit now.
3. **Design and ship a prior-auth-specific validation model in the same
   change.** Deferred, not rejected: doing this requires the user to
   specify the target form-field schema, what should stand in for "check
   the math" on a non-arithmetic form, and how PHI in prior-auth documents
   should be handled differently from the invoice-era assumptions in
   [docs/COMPLIANCE.md](COMPLIANCE.md#data-handling). None of that is
   answered yet, so this ADR only covers removing a validation model that
   no longer fits; it does not introduce a replacement.

## Consequences

**Positive**

- The active product no longer implies a correctness guarantee
  (`data/committed/` vs. `data/review/`, an audit trail) that it can't
  actually back for its real document type: a compliance-relevant
  correction that affects behavior (see the rewrite of
  [docs/COMPLIANCE.md](COMPLIANCE.md)).
- Layout parsing, Markdown/HTML rendering, and annotated-PDF output keep
  shipping value today without waiting on the harder validation-design
  question.
- The invoice pipeline's code, tests, and the schema-shaping knowledge in
  `docs/MODEL.md` are preserved for reuse once a prior-auth validation
  model is defined.

**Negative / follow-up work**

- There is currently **no automated correctness check** on anything the
  active graph extracts. Output must be treated as a best-effort
  transcription for a human to read, not a verified structured result.
- There is currently **no commit/review split and no audit trail** for
  prior-auth documents: `src/audit.py` is unwired, so nothing is logged
  per run beyond what the UI shows in-session.
- The invoice→prior-auth pivot remains blocked on three open questions:
  the target structured schema per form type, what validation model
  replaces arithmetic checking, and PHI-specific data-handling
  requirements. This ADR removes the old model; it does not resolve those
  questions.
- `src/extract.py`/`validate.py`/`regions.py` are unit-tested in isolation
  but not exercised end-to-end against the current UI/graph; re-verify
  integration behavior before re-wiring any of them.

## References

- `src/graph.py` (the unwiring itself and its inline rationale)
- [docs/ARCHITECTURE.md](ARCHITECTURE.md#dormant-the-invoice-extractionvalidation-graph)
- [docs/COMPLIANCE.md](COMPLIANCE.md)
- [docs/VALIDATE.md](VALIDATE.md)
- [docs/REGIONS.md](REGIONS.md)
- [docs/MODEL.md](MODEL.md)
