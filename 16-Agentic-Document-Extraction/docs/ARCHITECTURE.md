# Architecture

A single LangGraph `StateGraph` per document. No multi-agent chat, no
background workers.

## Active graph

```mermaid
flowchart TD
    P[preprocess] --> PA[parse]
    PA --> END((END))
```

| Node | Responsibility |
|---|---|
| `preprocess` | Load the file, normalize to a capped-size image, compute `doc_sha256`. |
| `parse` | Layout-parses pages `start_page..end_page` (1-based, `end_page=None` = through the last page -- no fixed cap) into `ParseBlock`s, one concurrent call per page (bounded to `MAX_PARALLEL_PAGES`, since each page is an independent single-image call), via the shared `_build_llm`/`_invoke_structured` helpers in `src/extract.py`. Renders the result to Markdown and to a self-contained HTML page (`src/markdown.py`), and generates the annotated PDF plus one PNG per page (`src/annotate.py`). Best-effort throughout: a page or annotation failure is recorded in `parse_error`/`page_diagnostics` rather than raised. |

`run_graph()` resets the token-usage accumulator (`src/usage.py`) before each
run and attaches the accumulated `token_usage` list to the returned state.
There is no `commit`/`review` split today: `parse` -> `END` regardless of
outcome, and nothing is written to `data/committed/` or `data/review/`.

### Drawing on PDFs without a PDF library

`src/annotate.py` doesn't use `pypdf` or `reportlab`. Every page is already
rasterized to a PIL image for the rest of this pipeline (`preprocess_pages`,
via `pypdfium2` for PDFs), and Pillow itself can write a multi-page PDF
straight from a list of images (`Image.save(path, "PDF", save_all=True,
append_images=[...])`). So boxes are drawn with `ImageDraw` on those same
rasterized pages, then saved as a PDF with Pillow — no new dependency, and
no risk of the fragility that comes with overlaying onto an original PDF's
own vector content. The same rasterized pages are also saved individually as
`data/annotated/<doc_sha>/page_NNN.png`, so the UI can show an inline
preview without a PDF-viewer widget.

## Main types and state

| Type | Lives in | Holds |
|---|---|---|
| `GraphState` (TypedDict) | `src/graph.py` | The graph's own state: `image_path`, `start_page`/`end_page`, `model`, `doc_sha`, `base64_image`/`mime`, `parse_result`, `markdown`, `parse_error`, `annotated_pdf_path`, `status`. |
| `ParseResult` / `ParsePage` / `ParseBlock` / `BBox` | `src/schema.py` | The active schema: one `ParsePage` (with `blocks: list[ParseBlock]`) per page; `BBox.xyxy` and (dormant) `Region.bbox_xyxy` are normalized 0-1 coordinates, always exactly 4 values, enforced by a `field_validator`. |
| `PageDiagnostic` | `src/diagnostics.py` | Per-page call outcome (`parsed`/`content_filtered`/`refused`/`incomplete`/`invalid_response`/`http_error`/`transport_error`), HTTP status, sanitized request/model ids, token counts, filter annotations — never raw response text, headers, or credentials. |
| Token usage accumulator | `src/usage.py` | A plain module-level `list[dict]`, reset by `run_graph()` at the start of each run. Not per-run-isolated — see the `# ponytail:` comment in that file for the single-document-at-a-time assumption this relies on. |
| `Invoice` / `LineItem` / `Region` / `ValidationReport` (dormant) | `src/schema.py` | The unwired invoice contract — see below. |

There is no database and no session store beyond Streamlit's own
`st.session_state` (the sidebar's page-range widgets, the last parse result,
and the running session token-usage list, all keyed in `src/ui/app.py`).

## External systems

- **One OpenAI-compatible HTTP endpoint** — the only external system this
  project talks to. `OPENAI_API_KEY` (required) and `OPENAI_BASE_URL`
  (optional, for a gateway other than api.openai.com) configure it; every
  call goes through `_build_llm`/`_invoke_structured` in `src/extract.py`.
  See [docs/MODEL.md](MODEL.md) for the exact request shape.
- Nothing else: no database, no message queue, no other third-party API, no
  outbound network call besides that one endpoint.

## Dormant: the invoice extraction/validation graph

The graph used to continue past `parse` into an `extract -> validate ->
maybe_crop -> commit`/`review` cycle built on one contract: a vision model
*proposes* an `Invoice`, and `src/validate.py`'s plain-Python arithmetic
checks are the only authority on whether it's correct. That contract doesn't
fit real prior-auth documents — they have no `subtotal`/`grand_total` for
Python to check — so this half of the graph is **not wired into
`build_graph()`**. The code and its tests are untouched on disk for when a
validation model that actually fits prior-auth forms is defined:

| Node (not wired) | Lives in | Would have done |
|---|---|---|
| `extract` | `src/extract.py` (`extract_invoice`) | Vision LLM proposes an `Invoice`, given the image and (if available) the parsed Markdown as extra context. On a retry, prior validation errors are passed back as feedback. |
| `validate` | `src/validate.py` | Pure Python arithmetic check, no LLM involved. Would increment `retry_count` and record the error on failure. See [docs/VALIDATE.md](VALIDATE.md). |
| `maybe_crop` | `src/regions.py` + `src/extract.py` (`extract_regions`/`crop_and_extract`) | Runs at most once per `extract` attempt. For a failing line item, prefers a bbox the layout parser already found over asking the model again; falls back to a dedicated regions call for anything not already covered. Crops those regions and re-extracts just those fields. See [docs/REGIONS.md](REGIONS.md). |
| `commit` | removed from `graph.py` | Would write `data/committed/<doc_sha>.json` (the `Invoice` plus `markdown_path`/`annotated_pdf_path`) and an audit line via `src/audit.py`. |
| `review` | removed from `graph.py` | Would write `data/review/<doc_sha>.json` (invoice + last validation report + `markdown_path`/`annotated_pdf_path`) and an audit line. |

The routing that graph used to run (preserved here for whoever re-wires it):

From `validate`:
1. `report.ok` -> `commit`.
2. not ok, this `extract` attempt not yet cropped -> `maybe_crop`.
3. not ok, already cropped this attempt, `retry_count < max_retries` ->
   `extract` again (`cropped_this_iter` resets to `False`).
4. not ok, already cropped this attempt, `retry_count >= max_retries` ->
   `review`.

From `maybe_crop`:
- Crop applied -> back to `validate`, to check whether it fixed the problem.
- Nothing worth cropping -> routes directly to the decision `validate` would
  have made (`extract` again or `review`), rather than re-running `validate`
  and double-counting `retry_count`.

`retry_count` was initialized once by `preprocess` and never reset by it on
later visits — only `validate` incremented it, and only on a genuine
failure. The "retry `extract`" transition (from either `validate` or
`maybe_crop`) reset `cropped_this_iter` to `False`. Cropping was a
best-effort accuracy aid, not a required step: if the model returned no
bounding boxes, `maybe_crop` was a no-op and validation just failed forward
into the retry/review path.

`src/audit.py`'s `write_audit_line` is likewise unwired — no node in the
active graph calls it. See [docs/COMPLIANCE.md](COMPLIANCE.md) for what is
and isn't logged today, and
[docs/ADR-0001-UNWIRE-INVOICE-PIPELINE.md](ADR-0001-UNWIRE-INVOICE-PIPELINE.md)
for why this graph was unwired rather than deleted or adapted in place.
