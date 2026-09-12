# Compliance and audit

**Current state: the active graph (`preprocess -> parse`) makes no
arithmetic claim about a document and writes no audit trail.** It produces
only a layout parse (Markdown/HTML/JSON) and an annotated PDF/PNGs — read-only
reference artifacts for a human, not a proposed structured result that
anything gates. The control-plane design described below — math validation
and human review gating a commit, with an audit line per decision — is
implemented in `src/validate.py`, `src/audit.py`, and the removed
`commit`/`review` nodes, but none of it runs today. See
[docs/ARCHITECTURE.md](ARCHITECTURE.md#dormant-the-invoice-extractionvalidation-graph)
for why it's unwired. This project is not LandingAI's ADE product and not
Reducto.

## No silent fixes (dormant design, preserved for re-wiring)

The design: the model proposes an `Invoice`; `src/validate.py` is the only
authority on whether it's correct, and nothing rewrites a number to make the
math balance. A document would either:

- pass validation and be written to `data/committed/`, or
- fail after all retries and be written to `data/review/` for a human, or
- be accepted by a human reviewer in the UI, which would set
  `human_override=True` and require a reviewer name — that decision itself
  audited, never silent.

None of `data/committed/`, `data/review/`, or a human-override path exists
in the active graph or UI today.

## What's actually written today

Layout parsing (`data/parse/<doc_sha>.json` + `.md`) and the annotated PDF
plus per-page PNGs (`data/annotated/<doc_sha>.pdf`,
`data/annotated/<doc_sha>/page_NNN.png`) are written on every run that
reaches `parse`, whatever the outcome — parsing is best-effort, so a partial
or failed parse just means fewer pages/blocks are in the output rather than
nothing being written. There's no separate commit/review step: `parse` is
the last node, and it doesn't gate its own output on anything.

## Audit trail: not currently written

`src/audit.py`'s `write_audit_line` would append JSON lines to
`data/audit/YYYYMMDD.jsonl` (one file per UTC day), but no node in the
active graph calls it — no audit line is written by any run today. The
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

- Source images live only under `data/inbox/` and never leave the machine
  except in the model call itself.
- Layout parse output (`data/parse/`) and the annotated PDF/PNGs
  (`data/annotated/`) are also derived directly from the source document's
  content, so they follow the same rule.
- `data/crops/`, `data/committed/`, and `data/review/` are not written by the
  active graph — cropping, commit, and review are all dormant (see above).
  Any files already present under those paths predate the pipeline being
  unwired.
- `.gitignore` excludes `data/inbox/*`, `data/crops/*`, `data/parse/*`,
  `data/annotated/*`, `.env`, and `.venv` so scanned documents, their
  derivatives, and secrets are never committed to source control.
- Nothing in this project uploads a document anywhere other than the
  configured `OPENAI_BASE_URL` endpoint for parsing/extraction calls.
