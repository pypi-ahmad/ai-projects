# Runtime extraction prompts

`src/prompts.py` loads the seven templates in `prompts/runtime/` from disk for
each call, so Markdown edits take effect without restarting the app. Template
substitution uses Python `str.format`; double literal JSON braces and keep the
existing placeholder names. Substituted content is not formatted again.

| Template | Purpose | Placeholders |
| --- | --- | --- |
| parse-page | Text, form fields, tables, reading order, boxes | page_number, width_px, height_px |
| extract-invoice | Legacy invoice field extraction | none |
| markdown-context | Untrusted layout evidence for invoice extraction | markdown_context |
| validation-feedback | Reinspection without arithmetic correction | feedback |
| extract-regions | Locate uncertain invoice fields | error_summary |
| crop-line-item | Read one invoice row | hint |
| crop-field | Read one invoice field | field_name, hint |

The active document graph uses `parse-page`. The other files in `prompts/` are
historical development instructions rather than runtime templates.

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

Archived layout candidates use section headings and individual key/value blocks
for forms. Repeated grids use rectangular string arrays. Merged values appear
once in the top-left cell, with empty covered cells. Tables with uncertain column
associations retain their transcription in `text` with `table=null`. The schema
has no cell geometry, rowspan/colspan, or explicit header metadata. Rendering
uses the first row as a header, pads trailing cells for display only, and keeps
the model's block order instead of interleaving independent columns by coordinate.

Legacy invoice and crop schemas require numeric values that cannot be null.
Prompt wording discourages invention but cannot make that schema represent a
missing number. These legacy paths have offline contract tests, not live quality
validation on the six medical forms. Confidence is a model estimate, not a
calibrated guarantee of correctness.

## Reproducible live comparisons

The current resolution experiment is `scripts/evaluate_resolution.py`: five
pages, sequential baseline/candidate requests, at most ten calls, and a $2
estimated-cost guard. It excludes the known filtered BadgeCare page, disables
retries, fixes medium reasoning, caps completion tokens at 8,192, and stops on
unknown usage. The reservation is an estimate rather than a provider-enforced
spending limit. Its metric gate cannot replace visual source review or
automatically promote a default. See
[the Sol results and command](SOL-RESOLUTION-EVALUATION.md).

### Separate prompt-comparison evaluator

Use the current configured `gpt-6-sol` endpoint with temperature omitted, existing
reasoning effort, and the same 1600-pixel page rendering for both variants. No
model-version portability claim is made. API credentials remain in the environment.

`scripts/evaluate_prompts.py` requires `--live` and contains a fixed allowlist:
BadgeCare page 1, RealSolutions_1 pages 1-2, RealSolutions_2 page 1, and
Amerigroup_1 pages 1-2. Each request contains one image. Documents run sequentially;
pages within a document run concurrently, capped at 50. Evaluation disables
automatic retries and records filter failures separately. It does not have the
resolution evaluator's ten-request/$2 guard or completion-token cap. It does not
change normal application outputs. An allowlist is not authorization for another
paid run: obtain approval and use `--skip-filtered-from` with a previous manifest
to omit known filtered pages before rendering or sending them.

Example after authorization (replace the previous-manifest path with the real
record and choose a new output directory):

```powershell
uv run --no-project --python .venv\Scripts\python.exe -m scripts.evaluate_prompts --prompts prompts\runtime --output data\parse\my-evaluation --skip-filtered-from data\parse\previous-evaluation\manifest.json --live
```

The output includes exact prompt snapshots and hashes, selected page images,
validated responses, failure status, timing, usage where available, and a manifest.
Reference token scores compare case-folded word-token multisets after removing
HTML markup from LandingAI's page-range text. They measure transcription overlap,
not field association, checkbox accuracy, reading order, or clinical correctness.
Punctuation and case errors need source review. Filtered or error pages have no
accuracy score and count against coverage; missing usage is unknown and is not free.

Compare raw outputs and inspect mismatches against source images before accepting
a prompt. Table counts need not match LandingAI because forms are deliberately
segmented differently. Retain baseline snapshots for rollback. Reevaluate after
changing the prompt, image preparation, schema, or model. Keep reference text out
of model prompts to avoid contaminating the comparison.
