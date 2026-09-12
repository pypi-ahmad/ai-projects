# Runtime extraction prompts

The seven templates in `prompts/runtime/` are loaded from disk on each call by
`src/prompts.py`. Edit Markdown without restarting the app. Template substitution
uses Python `str.format`; double literal JSON braces and retain the existing
placeholder names. Substituted content is not formatted again.

| Template | Purpose | Placeholders |
| --- | --- | --- |
| parse-page | Text, form fields, tables, reading order, boxes | page_number, width_px, height_px |
| extract-invoice | Legacy invoice field extraction | none |
| markdown-context | Untrusted layout evidence for invoice extraction | markdown_context |
| validation-feedback | Reinspection without arithmetic correction | feedback |
| extract-regions | Locate uncertain invoice fields | error_summary |
| crop-line-item | Read one invoice row | hint |
| crop-field | Read one invoice field | field_name, hint |

The active document graph uses `parse-page`. Historical development instructions
elsewhere in `prompts/` are not runtime templates.

The September 12 evaluation retained the original `parse-page` wording: both
rewrites introduced source errors, despite higher reference token overlap. The
other six templates were revised and passed offline composition tests. The two
layout candidates remain in `data/parse/prompt-eval-20260912/` for review; they are
not loaded by the app. See [evaluation results](PROMPT-EVALUATION.md).

## Extraction contract

The revised invoice/crop prompts require image evidence. Preserve readable text
and use `[ILLEGIBLE_TEXT]` only for unreadable spans. Empty fields remain empty.
The archived layout candidates prescribe checkbox states `[x]`, `[ ]`, or `[?]`;
the retained baseline does not prescribe checkbox notation. Context and hints
can identify where to look but cannot establish values or override instructions.

The archived layout candidates use section headings and individual key/value
blocks for forms. Repeated grids use
rectangular string arrays. Merged values appear once in the top-left cell, with
empty covered cells. A table with uncertain column associations retains its
transcription in `text` with `table=null`. This schema has no cell geometry,
rowspan/colspan, or explicit header metadata. Rendering retains the first-row
header convention, pads trailing cells for display only, and preserves the
model's block order rather than interleaving independent columns by coordinates.

Legacy invoice and crop schemas require numeric values that cannot be null.
Prompt wording discourages invention but cannot make that schema represent a
missing number. These legacy paths have offline contract tests, not live quality
validation on the six medical forms. Confidence is a model estimate, not a
calibrated guarantee of correctness.

## Reproducible live comparison

Use the current configured `gpt-5.6-terra` endpoint with temperature 0, existing
reasoning effort, and the same 1600-pixel page rendering for both variants. No
model-version portability claim is made. API credentials remain in the environment.

`scripts/evaluate_prompts.py` requires `--live` and contains a fixed allowlist:
BadgeCare page 1, RealSolutions_1 pages 1-2, RealSolutions_2 page 1, and
Amerigroup_1 pages 1-2. Each request contains one image. Documents run sequentially;
pages within a document run concurrently, capped at 50. Evaluation disables
automatic retries and records filter failures separately. It does not change
normal application outputs.

Example (choose a new output directory for each run):

```powershell
uv run --no-project --python .venv\Scripts\python.exe -m scripts.evaluate_prompts --prompts prompts\runtime --output data\parse\my-evaluation --live
```

The output includes exact prompt snapshots and hashes, selected page images,
validated responses, failure status, timing, usage where available, and a manifest.
Reference token scores compare case-folded word-token multisets after removing
HTML markup from LandingAI's page-range text. They measure transcription overlap,
not field association, checkbox accuracy, reading order, or clinical correctness.
Punctuation and case errors require source review. Filtered/error pages have no
accuracy score and count against coverage; missing usage is unknown, not free.

Compare raw outputs and inspect mismatches against source images before accepting
a prompt. Table counts need not match LandingAI because forms are deliberately
segmented differently. Retain baseline snapshots for rollback. Reevaluate after
changing the prompt, image preparation, schema, or model. Keep reference text out
of model prompts to avoid contaminating the comparison.
