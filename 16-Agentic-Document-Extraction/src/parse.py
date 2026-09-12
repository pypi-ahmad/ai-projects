"""Active layout-parsing entry point. `parse_document` fans a page range out
across a bounded thread pool and calls `parse_page` (a thin wrapper over
src/extract.py's `_invoke_structured`/`ParsePage`) once per page, then writes
`data/parse/<doc_sha>.json` itself -- this is the only unconditionally-called
consumer of src/extract.py's model-call plumbing in the active graph (see
src/graph.py).

Must not: let one page's failure abort the others, or let a failure escape
as anything other than a `PageDiagnostic` entry (see `parse_payload`'s
exception handling below) -- the active graph's contract is that a partial
or fully-failed parse is reported, never raised.

Next: src/markdown.py, which renders whatever `ParseResult` this produces.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import ContentFilterFinishReasonError

from src.extract import _build_llm, _image_message, _invoke_structured
from src.preprocess import preprocess_pages
from src.prompts import render_prompt
from src.models import DEFAULT_MODEL, MODEL_RATES
from src.schema import ParsePage, ParseResult
from src.diagnostics import ExtractionCallError, PageDiagnostic

# Bounds concurrent per-page calls -- each page is an independent
# single-image request (see docs/ARCHITECTURE.md), so this is a latency win
# with no batching/accuracy tradeoff. The value 50 matches the concurrency
# cap used historically in scripts/evaluate_prompts.py's live evaluation
# runs (docs/PROMPT-EVALUATION.md, docs/PROMPTS.md); whether 50 specifically
# was chosen for a rate-limit or cost reason beyond that isn't recorded
# anywhere in this repo.
MAX_PARALLEL_PAGES = 50

def parse_page(
    image_b64: str, mime: str, page_number: int, width_px: int, height_px: int,
    *, diagnostics: list[PageDiagnostic] | None = None, model: str = DEFAULT_MODEL,
) -> ParsePage:
    llm = _build_llm(model=model)
    text = render_prompt(
        "parse-page", page_number=page_number, width_px=width_px, height_px=height_px
    )
    result = _invoke_structured(
        llm, ParsePage, [_image_message(text, image_b64, mime)], call_name="parse_page", diagnostics=diagnostics
    )
    # We already know the true page/geometry from preprocessing; only the
    # model's `blocks` are worth trusting.
    return result.model_copy(update={"page": page_number, "width_px": width_px, "height_px": height_px})


def parse_document(
    path: str | Path, *, start_page: int = 1, end_page: int | None = None,
    model: str = DEFAULT_MODEL,
) -> ParseResult:
    """Layout-parse every page in [start_page, end_page] (1-based, inclusive;
    end_page=None means through the last page -- there is no page cap).

    Pages are parsed concurrently (bounded to MAX_PARALLEL_PAGES at a time):
    each page is an independent single-image call, so this is a latency win
    with no accuracy tradeoff (unlike batching several pages into one call,
    which would risk the model conflating content across pages).
    """
    if model not in MODEL_RATES:
        raise ValueError("Unsupported model")
    pages_payload = preprocess_pages(path, start_page=start_page, end_page=end_page)
    doc_sha = pages_payload[0]["doc_sha256"]

    def parse_payload(payload: dict) -> tuple[ParsePage | None, PageDiagnostic]:
        diagnostics = []
        try:
            page = parse_page(
                payload["base64"],
                payload["mime"],
                payload["page"],
                payload["width"],
                payload["height"],
                diagnostics=diagnostics,
                model=model,
            )
            diagnostic = diagnostics[-1] if diagnostics else PageDiagnostic(outcome="parsed")
            return page, diagnostic.model_copy(update={"page": payload["page"]})
        except ExtractionCallError as exc:
            return None, exc.diagnostic.model_copy(update={"page": payload["page"]})
        except ContentFilterFinishReasonError:
            return None, PageDiagnostic(page=payload["page"], outcome="content_filtered", requested_model=model)
        except Exception:
            return None, PageDiagnostic(page=payload["page"], outcome="invalid_response", requested_model=model)

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_PAGES) as pool:
        outcomes = list(pool.map(parse_payload, pages_payload))

    pages = [page for page, _ in outcomes if page is not None]
    content_filtered_pages = [
        diagnostic.page for _, diagnostic in outcomes if diagnostic.outcome == "content_filtered"
    ]
    result = ParseResult(
        doc_sha=doc_sha,
        pages=pages,
        content_filtered_pages=content_filtered_pages,
        page_diagnostics=[diagnostic for _, diagnostic in outcomes],
    )

    out_dir = Path("data/parse")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{doc_sha}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")

    return result


def _main() -> None:
    parser = argparse.ArgumentParser(description="Parse a document's pages into layout blocks.")
    parser.add_argument("--path", required=True, help="Path to an invoice image or PDF")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, default=None, help="Omit for through the last page")
    args = parser.parse_args()

    result = parse_document(args.path, start_page=args.start_page, end_page=args.end_page)
    print(f"doc_sha: {result.doc_sha}")
    print(f"pages parsed: {len(result.pages)}")
    print(f"written to data/parse/{result.doc_sha}.json")


if __name__ == "__main__":
    _main()
