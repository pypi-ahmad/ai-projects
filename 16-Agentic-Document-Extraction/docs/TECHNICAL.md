# Technical notes

Stack choices, invariants, error handling, and on-disk formats that aren't
obvious from reading a single file in isolation. For the active/dormant
graph shape, see [docs/ARCHITECTURE.md](ARCHITECTURE.md).

## Stack, and why

| Package | Used for | Why (where the code makes it obvious) |
|---|---|---|
| `langgraph` | The `StateGraph` in `src/graph.py` | One node-graph per document run; no multi-agent orchestration needed. |
| `langchain-openai` / `langchain-core` | `ChatOpenAI` client construction, `HumanMessage`/`convert_to_openai_messages` in `src/extract.py` | Gives a `reasoning_effort` field on `ChatOpenAI` (verified against the installed `langchain-openai==1.6.2` — see [docs/MODEL.md](MODEL.md)) and the standard multimodal message shape, but the actual completion call bypasses LangChain's own invoke path — see "Why raw responses" below. |
| `openai` (installed, **not** in `requirements.txt`) | `llm.root_client.chat.completions.with_raw_response.create(...)` in `_invoke_structured`, and exception types (`APIStatusError`, `APIConnectionError`, `ContentFilterFinishReasonError`) | Needed for the raw HTTP response (status code, headers, request id) that `_invoke_structured` reads before trusting the parsed content. It's a transitive dependency of `langchain-openai`; it is imported directly in `src/extract.py` and `scripts/evaluate_prompts.py` but has no pinned version of its own in `requirements.txt`. |
| `pydantic` | Every schema in `src/schema.py` and `src/diagnostics.py` | Strict-mode structured outputs (see below) plus local validation of whatever the model returns. |
| `pillow` | `src/preprocess.py`, `src/annotate.py` | Rasterizes/resizes every page to one PNG shape, and (per the in-source comment in `annotate.py`) writes the annotated multi-page PDF itself via `Image.save(..., "PDF", save_all=True, ...)` — no `pypdf`/`reportlab` dependency at all. |
| `pypdfium2` | `src/preprocess.py` (`_render_pdf_page_range`, `count_pages`) | Chosen specifically (comment in `requirements.txt`) because it installs as a native Windows wheel with no Poppler/Docker dependency. |
| `streamlit` | `src/ui/app.py`, `src/ui/clipboard.py` | The entire UI; `clipboard.py` uses `st.components.v2.component` (CCv2) for a small JS clipboard-copy widget. |
| `python-dotenv` | `load_dotenv()` in `src/extract.py` | Loads `.env` (`OPENAI_API_KEY` etc.) into the process environment. |
| `pytest` (installed, **not** in `requirements.txt`) | The whole `tests/` suite | Not listed anywhere in the repo's own dependency manifest — how it ended up in this checkout's `.venv` is not recorded in the tree. |

## Invariants worth knowing before you touch this code

- **Pages are 1-based**, and `end_page=None` always means "through the last
  page" — there is no fixed page cap anywhere in `preprocess.py`, `parse.py`,
  or `graph.py`. This was a deliberate removal (see
  [docs/ARCHITECTURE.md](ARCHITECTURE.md)), not an oversight.
- **Bounding boxes are normalized to `[0, 1]`**, always exactly 4 values
  `(x0, y0, x1, y1)`, enforced by `_require_xyxy_len` (a shared
  `field_validator` in `src/schema.py`) on both `BBox.xyxy` and the dormant
  `Region.bbox_xyxy`. They're typed as `tuple[float, ...]` rather than a
  fixed-length tuple specifically because OpenAI's strict `json_schema` mode
  rejects `prefixItems` — see the schema-shaping rules in
  [docs/MODEL.md](MODEL.md). Multiply by `(width, height, width, height)` to
  get pixel coordinates.
- **Concurrency bound:** `src/parse.py` parses pages with a
  `ThreadPoolExecutor(max_workers=MAX_PARALLEL_PAGES)`, `MAX_PARALLEL_PAGES =
  50`. Each page is an independent single-image call, so this is a pure
  latency win — there's no cross-page batching that could conflate content
  between pages.
- **`src/usage.py`'s accumulator is a plain module-level list**, not
  contextvar/per-run isolated. The in-source comment marks this explicitly:
  safe because `list.append` is atomic under the GIL for concurrent *pages
  within one document*, but not safe for multiple documents' graphs running
  concurrently in the same process. This is a single-user desktop tool that
  processes one document at a time, so `run_graph()` just calls
  `usage.reset()` before each run.
- **Strict `json_schema` structured outputs constrain how every Pydantic
  model sent to the LLM can be written**: every property must be in
  `required` (no field may rely on a Python default to be "optional" — use a
  nullable type instead), and no `prefixItems`/fixed-length tuples. Both
  constraints are explained in the module-level comment at the top of
  `src/schema.py` and in full in [docs/MODEL.md](MODEL.md).
- **`doc_sha256`** (SHA-256 of the raw uploaded file bytes) is the key every
  derived artifact is filed under — see "Persistence paths" below.

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
- **Every LLM call outcome is classified**, not just pass/fail:
  `_invoke_structured` in `src/extract.py` maps every path — HTTP success
  with a refusal, HTTP success with `finish_reason != "stop"`, HTTP success
  with content-filter annotations, `APIStatusError`, `APIConnectionError`,
  and "anything else" — onto one `PageDiagnostic.outcome` value (`parsed`,
  `content_filtered`, `refused`, `incomplete`, `invalid_response`,
  `http_error`, `transport_error`). This is the taxonomy the UI's "API
  diagnostics" expander and `ParseResult.page_diagnostics` both read.
- **Untrusted-data boundary: model/provider output.** `src/diagnostics.py`'s
  `safe_identifier()` is the gate between raw provider data (headers, model
  strings, request ids) and anything recorded in a `PageDiagnostic` — it
  rejects anything that isn't a narrow `[A-Za-z0-9_.:/-]` token, anything
  matching an API-key/bearer/token pattern, and anything containing the
  value of any environment variable whose name contains `KEY`/`TOKEN`/
  `SECRET`/`PASSWORD`. Response bodies, refusal text, and prompt/completion
  text itself are never put into diagnostics at all — only classification
  metadata is. Module docstring: *"Allowlisted API metadata; response text
  never enters diagnostics."*
- **Untrusted-data boundary: model *content*.** The dormant `src/validate.py`
  is explicit that it never corrects a value — a failing arithmetic check is
  reported, not silently fixed, because the model's proposed `Invoice` is
  data to check, not a value Python is allowed to edit
  (`merge_line_item`/`validate_invoice` never mutate their input; see
  [docs/COMPLIANCE.md](COMPLIANCE.md), "No silent fixes").

## Persistence paths

All paths are relative to the repo root and keyed by `doc_sha` (the source
file's SHA-256) unless noted. `.gitignore` excludes everything under
`data/` except `.gitkeep` placeholders, plus `.env` and `.venv/`.

| Path | Written by | When |
|---|---|---|
| `data/inbox/<original filename>` | `src/ui/app.py` on upload | Every upload, before Parse is clicked. |
| `data/parse/<doc_sha>.json` | `parse_document` (`src/parse.py`) | Every `parse` run that reaches the point of having pages, even a partial one. |
| `data/parse/<doc_sha>.md` | `save_markdown_for_doc` (`src/markdown.py`), called from `node_parse` | Same as above. |
| `data/annotated/<doc_sha>.pdf` + `.meta.json` | `annotate_document` (`src/annotate.py`) | Same run, unless annotation itself throws (caught and skipped, PDF omitted). |
| `data/annotated/<doc_sha>/page_NNN.png` | `annotate_document` | Same call as the PDF, one file per rendered page. |
| `data/crops/<doc_sha>/<region.id>.png` | `crop_and_extract` (`src/extract.py`) | **Dormant** — only reachable from the unwired `maybe_crop` node. |
| `data/committed/<doc_sha>.json` | would-be `commit` node (removed from `graph.py`) | **Dormant** — not written by any active code today; the two files present in this checkout under `data/committed/` predate the pipeline being unwired (see [docs/COMPLIANCE.md](COMPLIANCE.md)). |
| `data/review/<doc_sha>.json` | would-be `review` node (removed from `graph.py`) | **Dormant**, same caveat. |
| `data/audit/YYYYMMDD.jsonl` | `write_audit_line` (`src/audit.py`) | **Dormant** — no active node calls it; the file present in this checkout predates the unwiring. |

## Not covered here

Prompt template contract and the runtime prompt-editing workflow are in
[docs/PROMPTS.md](PROMPTS.md). Model selection, pricing, and the exact
structured-output request shape are in [docs/MODEL.md](MODEL.md). What's
actually logged/gated versus dormant is in
[docs/COMPLIANCE.md](COMPLIANCE.md).
