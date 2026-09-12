# Phase 5 — LangGraph wiring

**Implement** the LangGraph state machine wiring `src/extract.py` and `src/validate.py` together.

**State fields:** `image_path`, `doc_sha`, `base64_image`, `mime`, `extracted_data`, `regions`, `validation_error`, `report`, `retry_count`, `max_retries`, `cropped_this_iter`, `status`, `human_override`.

**Nodes:**
- `preprocess` — sets `retry_count = 0` only on the very first visit; never resets it on a later visit.
- `extract`
- `validate` — uses `src.validate`; on failure, increments `retry_count` and sets `validation_error` to a string describing the failure.
- `maybe_crop` — if the report isn't ok and `cropped_this_iter` is false: call `extract_regions`; if any region is cropable, `crop_and_extract`, merge the result into the invoice, and set `cropped_this_iter = True`.
- `commit` — write `data/committed/<doc_sha>.json` plus an audit line.
- `review` — write `data/review/<doc_sha>.json` (invoice plus the last report) plus an audit line.

**Routing from `validate`:**
1. `ok` → `commit`.
2. not ok, `cropped_this_iter` false → `maybe_crop` → back to `validate`.
3. not ok, already cropped, `retry_count < max_retries` → `extract` (reset `cropped_this_iter`).
4. not ok, already cropped, `retry_count >= max_retries` → `review`.

`max_retries` defaults to 3.

**Audit:** append to `data/audit/YYYYMMDD.jsonl`: `ts`, `doc_sha`, `node`, `retry_count`, `error_codes`, `model="gpt-5.6-terra"`.

**CLI:** `python -m src.graph --path tests/fixtures/invoice.png --max-retries 3`

**Tests** (stub `extract`/`validate`):
1. First extract fails math; the crop-and-merge pass fixes it → commits.
2. No regions returned; the second extract attempt passes → commits, `retry_count == 1`.
3. Always fails → goes to review after `max_retries`; no commit file is written.

Stop after this phase.
