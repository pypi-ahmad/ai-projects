# Prompt evaluation: September 12, 2026

This is a historical evaluation record. The current runtime has one rewritten
`gpt-6-sol` prompt in `prompts/runtime/parse-page.md`; the prompt files discussed
below are no longer part of the application.

Decision: keep the baseline layout prompt used in this run. Both revised prompts improved
form segmentation and reference-token overlap, but they introduced incorrect
values. The corrective candidate transposed a facility tax identifier that the
baseline read correctly, so it failed the source-grounding acceptance gate. No
third tuning round ran.

Six other runtime prompts were revised at the time. That version preserved reading
order, escaped table cells safely, retained line breaks, and padded ragged rows for
display. The ignored local artifact directory contains the captured candidates and
results when those files are available in the checkout.

## Live scope and controls

| Document | Pages |
| --- | --- |
| Masked BadgeCare Plus_1 | 1 |
| Masked_Amerigroup_RealSolutions_1 | 1 to 2 |
| Masked_Amerigroup_RealSolutions_2 | 1 |
| Masked Amerigroup_1 | 1 to 2 |

There were 17 page invocations: six baseline, six candidate, and five corrective.
BadgeCare page 1 was content-filtered in baseline and candidate, then skipped
entirely in the corrective round. No other pages were submitted. No content-filter
retry, bypass, model change, or reference-text injection was used.

These runs used the pre-migration default model and temperature 0. They do not
validate the current `gpt-6-sol` configuration. The runs used the same reasoning
setting recorded in each manifest, the same 1600-pixel rendering,
one image per request, and concurrency capped at 50. Those historical runs
set the LangChain wrapper's retry field after constructing its SDK client;
inspection later showed the underlying client still allowed two transient
retries. The exact historical HTTP attempt count was not captured. The evaluator
now sets retries to zero on the actual SDK client. Documents ran sequentially;
their pages ran concurrently.

## Measurements

Results below cover the five successfully parsed pages. The sixth page counts
against coverage and has no transcription score.

| Measurement | Baseline | Candidate | Corrective |
| --- | ---: | ---: | ---: |
| Reference token F1, mean across pages | 95.10% | 95.69% | 95.68% |
| Source value spot checks matched | 20/27 | 18/27 | 20/27 |
| Ragged extracted tables | 6 | 0 | 0 |
| Extracted table blocks | 6 | 0 | 0 |
| Invalid bounding boxes | 0 | 0 | 0 |
| Reported input tokens | 13,745 | 17,060 | 17,585 |
| Reported output tokens | 8,643 | 15,674 | 15,733 |
| Mean successful-page latency | 18.03 s | 26.49 s | 27.28 s |

Token overlap ignores punctuation, case, sequence, and field associations. It
does not measure extraction accuracy. Spot checks were selected after inspection
to diagnose errors; they measure visible value presence rather than exhaustive
association accuracy or performance on unseen documents. Filtered requests gave
no usage, so token totals include reported usage only. Timing comes from single
runs and is not a latency benchmark.

The candidates turned these form sections into fields instead of tables. The zero
ragged-table count therefore does not prove better extraction of genuine repeated-row
tables. Live true-grid and merged-cell accuracy remain unmeasured on this corpus.
Renderer behavior is covered separately by offline tests.

## Source review findings

- Fax cover: both candidates retained reference text; the corrective candidate
  kept the left recipient fields before the right sender fields. The renderer now
  preserves supplied order instead of interleaving columns by top coordinate.
- Typed RealSolutions form: individual fields and checkbox groups replaced ragged
  tables. A facility identifier remained misread in all three runs.
- Handwritten RealSolutions form: the first candidate introduced new name/code
  errors. The corrective candidate recovered several but still misread other
  handwriting. One requested code improved, while several values remained unsafe
  to treat as verified.
- Amerigroup page 1: section/field separation improved, but member/referring
  identifiers remained incorrect. The corrective candidate introduced the new
  facility-identifier transposition that blocks promotion.
- Amerigroup page 2: dates and handwritten code punctuation still required review.
  The candidates also normalized a marked patient-type line instead of preserving
  its literal mark. Checkbox notation alone does not prove faithful transcription.

LandingAI uses richer table-cell structures and may describe logos or represent
forms differently. Reference disagreement was checked against source images;
reference tokens were not assumed correct. The results do not support a universal
accuracy claim.

## Artifacts and checks

Local artifacts live under `data/parse/prompt-eval-20260912/`:

- `comparison.html`: source images, escaped LandingAI Markdown, and all three
  extracted outputs; private document data stays in this ignored local directory.
- `summary.json`: aggregate measurements and the selected source-value checks.
- `baseline/`, `candidate/`, `corrective/`: page JSON/images/Markdown/HTML, manifests,
  and exact prompt snapshots with hashes.
- `baseline-prompts/`: original seven templates for comparison and rollback.

The six non-layout prompt revisions passed offline rendering and composition tests.
They were not live-tested on invoices because authorization covered only the listed
medical-document pages. Required numeric fields in the legacy schemas could not
represent missing values, and prompt wording did not change that limitation.

At the time of this evaluation, the full offline suite passed 63 tests, including column ordering, table escaping,
empty/ragged/multiline cells, Unicode/braces in templates, the exact live allowlist,
skipping filtered pages, and existing partial-failure behavior. Runtime layout
prompt bytes were checked against the baseline snapshot after rollback.
