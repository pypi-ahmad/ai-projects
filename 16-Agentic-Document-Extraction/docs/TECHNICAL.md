# Technical notes

This document covers stack choices, invariants, error handling, and on-disk
formats that span more than one file. For the active and dormant graph shape,
see [docs/ARCHITECTURE.md](ARCHITECTURE.md).

## Stack choices

| Package | Used for | Why (where the code makes it obvious) |
|---|---|---|
| `langgraph` | The `StateGraph` in `src/graph.py` | One node-graph per document run; no multi-agent orchestration needed. |
| `langchain-openai` / `langchain-core` | `ChatOpenAI` client construction, `HumanMessage`/`convert_to_openai_messages` in `src/extract.py` | Gives a `reasoning_effort` field on `ChatOpenAI` (verified against the installed `langchain-openai==1.6.2`; see [docs/MODEL.md](MODEL.md)) and the standard multimodal message shape. The completion call uses the raw SDK client so HTTP status, headers, and provider metadata remain available for diagnostics. |
| `openai` (installed, **not** in `requirements.txt`) | `llm.root_client.chat.completions.with_raw_response.create(...)` in `_invoke_structured`, and exception types (`APIStatusError`, `APIConnectionError`, `ContentFilterFinishReasonError`) | Needed for the raw HTTP response (status code, headers, request id) that `_invoke_structured` reads before trusting the parsed content. It's a transitive dependency of `langchain-openai`; it is imported directly in `src/extract.py` and `scripts/evaluate_prompts.py` but has no pinned version of its own in `requirements.txt`. |
| `pydantic` | Every schema in `src/schema.py` and `src/diagnostics.py` | Strict-mode structured outputs (see below) plus local validation of whatever the model returns. |
| `pillow` | `src/preprocess.py`, `src/annotate.py` | Rasterizes/resizes every page to one PNG shape, and (per the in-source comment in `annotate.py`) writes the annotated multi-page PDF itself via `Image.save(..., "PDF", save_all=True, ...)`; no `pypdf`/`reportlab` dependency at all. |
| `pypdfium2` | `src/preprocess.py` (`_render_pdf_page_range`, `count_pages`) | Chosen specifically (comment in `requirements.txt`) because it installs as a native Windows wheel with no Poppler/Docker dependency. |
| `streamlit` | `src/ui/app.py`, `src/ui/clipboard.py` | The entire UI; `clipboard.py` uses `st.components.v2.component` (CCv2) for a small JS clipboard-copy widget. |
| `python-dotenv` | `load_dotenv()` in `src/extract.py` | Loads `.env` (`OPENAI_API_KEY` etc.) into the process environment. |
| `pytest` (installed, **not** in `requirements.txt`) | The whole `tests/` suite | Not listed anywhere in the repo's own dependency manifest; how it ended up in this checkout's `.venv` is not recorded in the tree. |

## Invariants

- **Pages are 1-based**, and `end_page=None` always means "through the last
  page"; there is no fixed page cap anywhere in `preprocess.py`, `parse.py`,
  or `graph.py`. This was a deliberate removal (see
  [docs/ARCHITECTURE.md](ARCHITECTURE.md)), not an oversight. Invalid ranges
  are rejected rather than clamped; raster inputs expose only page 1.
- **Default image preparation:** PDFs render at 200 DPI, then each page is
  capped at a 1,600-pixel long edge. Aspect ratio is retained and small raster
  inputs are not upscaled. The 300-DPI / 3,200-pixel profile is available to
  the evaluator, not a promoted app default; see
  [the Sol comparison](SOL-RESOLUTION-EVALUATION.md).
- **Bounding boxes use normalized `[0, 1]` coordinates.** Exactly four
  values `(x0, y0, x1, y1)` are enforced by `_require_xyxy_len` (a shared
  `field_validator` in `src/schema.py`) on both `BBox.xyxy` and the dormant
  `Region.bbox_xyxy`. They're typed as `tuple[float, ...]` rather than a
  fixed-length tuple specifically because OpenAI's strict `json_schema` mode
  rejects `prefixItems`; see the schema-shaping rules in
  [docs/MODEL.md](MODEL.md). Multiply by `(width, height, width, height)` to
  get pixel coordinates. The schema checks length, not coordinate range or
  ordering; annotation skips out-of-range or degenerate boxes.
- **Concurrency bound:** `src/parse.py` parses pages with a
  `ThreadPoolExecutor(max_workers=MAX_PARALLEL_PAGES)`, `MAX_PARALLEL_PAGES =
  50`. Each page is an independent single-image call. Completion events are
  reported as futures finish; returned pages and diagnostics are sorted into
  source order. There is no cross-page image batching.
- **Usage is per-run.** The graph owns an explicit ledger, passed into every
  page call. Streamlit keeps session totals; no process-wide reset can erase
  another run's usage. LangGraph custom progress events reach the UI on its
  script thread, never from page workers.
- **Strict `json_schema` structured outputs constrain how every Pydantic
  model sent to the LLM can be written**: every property must be in
  `required` (no field may rely on a Python default to be "optional"; use a
  nullable type instead), and no `prefixItems`/fixed-length tuples. Both
  constraints are explained in the module-level comment at the top of
  `src/schema.py` and in full in [docs/MODEL.md](MODEL.md).
- **`doc_sha256`** (SHA-256 of the raw uploaded file bytes) identifies the document;
  a separate unique run id isolates each run's artifacts; see "Persistence paths" below.

## Error handling

- **Best-effort, not fail-fast.** `node_parse` in `src/graph.py` wraps the
  entire parse step in `try/except Exception`; a failure becomes
  `parse_error`/`status: "parse_failed"` in the returned state rather than
  an exception the caller has to catch. Per-page failures inside
  `parse_document` (`src/parse.py`) are caught individually in
  `parse_payload`, so one bad page doesn't drop the rest of the document.
  Annotation failure is caught separately again (`node_parse`'s inner
  `try/except` around `annotate_document`) and only skips the PDF, not the
  Markdown.
- **Early failures can raise.** Unsupported models are rejected before calls.
  `node_preprocess` does not catch file/rendering exceptions. Direct
  `parse_document` calls can also raise during preprocessing or persistence.
  The UI checks upload readability/ranges and catches graph exceptions.
- **Every LLM call outcome is classified.** `_invoke_structured` in
  `src/extract.py` maps every path; HTTP success
  with a refusal, HTTP success with `finish_reason != "stop"`, HTTP success
  with content-filter annotations, `APIStatusError`, `APIConnectionError`,
  and "anything else"; onto one `PageDiagnostic.outcome` value (`parsed`,
  `content_filtered`, `refused`, `incomplete`, `invalid_response`,
  `http_error`, `transport_error`). This is the taxonomy the UI's "API
  diagnostics" expander and `ParseResult.page_diagnostics` both read.
- **Untrusted-data boundary: model/provider output.** `src/diagnostics.py`'s
  `safe_identifier()` is the gate between raw provider data (headers, model
  strings, request ids) and anything recorded in a `PageDiagnostic`; it
  rejects anything that isn't a narrow `[A-Za-z0-9_.:/-]` token, anything
  matching an API-key/bearer/token pattern, and anything containing the
  value of any environment variable whose name contains `KEY`/`TOKEN`/
  `SECRET`/`PASSWORD`. Response bodies, refusal text, and prompt/completion
  text itself are never put into diagnostics at all; only classification
  metadata is. Module docstring: *"Allowlisted API metadata; response text
  never enters diagnostics."*
- **Untrusted-data boundary: model *content*.** The dormant `src/validate.py`
  is explicit that it never corrects a value; a failing arithmetic check is
  reported, not silently fixed, because the model's proposed `Invoice` is
  data to check, not a value Python is allowed to edit
  (`merge_line_item`/`validate_invoice` never mutate their input; see
  [docs/COMPLIANCE.md](COMPLIANCE.md), "No silent fixes").

## Persistence paths

Runtime paths are relative to the working directory; normal commands run from
this project folder. Graph runs use a unique `run_id`, with artifact names
based on the source file's SHA-256. Project and parent ignore rules cover the
listed runtime artifact directories, `.env`, and `.venv/`; they do not blanket
ignore every possible path under `data/`.

| Path | Written by | When |
|---|---|---|
| `data/inbox/<sha256><extension>` | `src/ui/app.py` on upload | When the current session sees a new content hash/extension, before Parse is clicked. |
| `data/parse/runs/<run_id>/<doc_sha>.json` | `parse_document` (`src/parse.py`) | Every `parse` run that reaches the point of having pages, even a partial one. |
| `data/parse/runs/<run_id>/<doc_sha>.md` | `save_markdown_for_doc` (`src/markdown.py`), called from `node_parse` | Only when at least one page parsed and Markdown persistence succeeds. |
| `data/parse/runs/<run_id>/annotated/<doc_sha>.pdf` + `.meta.json` | `annotate_document` (`src/annotate.py`) | After a successful Markdown write, when at least one page parsed. Annotation errors are caught; incomplete files may remain. |
| `data/parse/runs/<run_id>/annotated/<doc_sha>/page_NNN.png` | `annotate_document` | Same call as the PDF, one file per rendered page. |
| `data/crops/<doc_sha>/<region.id>.png` | `crop_and_extract` (`src/extract.py`) | **Dormant**; only reachable from the unwired `maybe_crop` node. |
| `data/committed/<doc_sha>.json` | would-be `commit` node (removed from `graph.py`) | **Dormant**; not written by the active graph. Existing files are not evidence of a current commit/review gate. |
| `data/review/<doc_sha>.json` | would-be `review` node (removed from `graph.py`) | **Dormant**, same caveat. |
| `data/audit/YYYYMMDD.jsonl` | `write_audit_line` (`src/audit.py`) | **Dormant**; no active node calls it. |

## Related documentation

Prompt template contract and the runtime prompt-editing workflow are in
[docs/PROMPTS.md](PROMPTS.md). Model configuration, pricing, and the exact
structured-output request shape are in [docs/MODEL.md](MODEL.md). What's
actually logged/gated versus dormant is in
[docs/COMPLIANCE.md](COMPLIANCE.md).

Standalone parse/Markdown/annotation helpers retain their original output-directory
defaults; graph runs pass their isolated directory explicitly. The UI renders
Markdown and JSON from its in-memory result, and reads only returned artifact
paths. Same-name uploads with different bytes reset page counts and old results.
Invalid ranges and corrupt uploads are rejected before extraction.
