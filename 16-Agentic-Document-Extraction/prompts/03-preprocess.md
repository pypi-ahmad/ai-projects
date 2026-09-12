# Phase 3; Preprocess and fixtures

**Implement** `preprocess(path) -> {doc_sha256, mime, base64, width, height, pages: 1}`. No OpenAI calls in this phase.

**Requirements:**
- Accept `png`, `jpg`, `jpeg`, `webp`, `tiff`.
- Accept PDF, page 1 only. Look up `pypdfium2` (or another library that pip-installs cleanly on native Windows); no Poppler, no Docker.
- Cap the long edge at 1600px with Pillow.
- An optional contrast-enhancement flag, default off.

**Fixtures:** `tests/fixtures/make_invoice_png.py` draws a readable invoice image whose numbers match `good_invoice.json` (2 line items, tax, and totals that pass `validate_invoice`). It also emits a dimmer, slightly rotated copy, `tests/fixtures/invoice_distorted.png`, with the same numbers.

**Tests:** missing file raises an error; a PNG returns valid base64; the sha is stable across repeated calls on the same file.

Stop after this phase.
