# Compliance and audit

**The active graph (`preprocess -> parse`) makes no arithmetic claim about a
document and writes no audit trail.** It produces a layout parse
(Markdown/HTML/JSON) and annotated PDF/PNGs for a human reader. The former
control-plane design, where math validation and human review gated a commit and
wrote an audit line, remains in `src/validate.py`, `src/audit.py`, and the
removed `commit`/`review` nodes. The active graph does not use it. See
[docs/ARCHITECTURE.md](ARCHITECTURE.md#dormant-the-invoice-extractionvalidation-graph)
for why it's unwired. This project is not LandingAI's ADE product and not
Reducto.

## No silent fixes (dormant design, preserved for re-wiring)

In the dormant design, the model proposes an `Invoice` and `src/validate.py`
decides whether its arithmetic is correct. Nothing rewrites numbers to balance
the math. A document would:

- pass validation and be written to `data/committed/`, or
- fail after all retries and be written to `data/review/` for a human, or
- be accepted by a human reviewer in the UI, which would set
  `human_override=True` and require a reviewer name; that decision itself
  audited, never silent.

None of `data/committed/`, `data/review/`, or a human-override path exists
in the active graph or UI today.

## What's actually written today

Graph runs use `data/parse/runs/<run_id>/`. Parse JSON contains successful
pages and per-page diagnostics, including when every requested page fails.
Preprocessing or filesystem failures can prevent that JSON write.

Markdown is written only when at least one page parsed. Afterward, annotation
can produce `annotated/<doc_sha>.pdf`, its metadata sidecar, and
`annotated/<doc_sha>/page_NNN.png`. An all-failed parse produces neither Markdown
nor annotation. Annotation failure does not discard the parse/Markdown, though
incomplete annotation files may remain. The UI uses only the current result's
returned artifact paths, not leftover files from previous runs.

These are extraction-success conditions, not correctness approval. There is
still no separate commit/review step or arithmetic gate.

## Audit trail: not currently written

`src/audit.py`'s `write_audit_line` would append JSON lines to
`data/audit/YYYYMMDD.jsonl` (one file per UTC day), but no node in the
active graph calls it; no audit line is written by any run today. The
schema below is what it would write if a node called it again:

| Field | Meaning |
|---|---|
| `ts` | ISO-8601 timestamp |
| `doc_sha` | `doc_sha256` of the source file |
| `node` | which node wrote the line (`commit`, `review`, or `human_override`) |
| `retry_count` | how many extract attempts happened |
| `error_codes` | validation error codes from the last report (`[]` if none) |
| `model` | the model name used |

## Data handling

- The UI saves uploads under `data/inbox/` with a content hash and extension.
  CLI/Python callers can supply source files elsewhere. Prepared page images
  are sent to the configured model endpoint; the source file itself stays local.
- Graph outputs under `data/parse/runs/`, standalone helper outputs under
  `data/parse/` or `data/annotated/`, and evaluation artifacts contain source
  document content and require the same handling as the originals.
- `data/crops/`, `data/committed/`, and `data/review/` are not written by the
  active graph; cropping, commit, and review are all dormant (see above).
  Any files already present under those paths predate the pipeline being
  unwired.
- Project and parent ignore rules exclude known runtime artifact directories,
  `.env`, and `.venv` from ordinary staging. Ignore rules do not protect files
  that are already tracked or force-added. Check staged content before publication.
  The app retains artifacts until someone removes them.
- Nothing in this project uploads a document anywhere other than the
  configured `OPENAI_BASE_URL` endpoint for parsing/extraction calls.
